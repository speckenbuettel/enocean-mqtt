"""Serial ESP3 transport adapter."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from queue import Empty, Queue
from typing import Protocol, cast

from enocean_mqtt.esp3.commands import packet_to_response
from enocean_mqtt.esp3.packets import (
    ESP3ChecksumError,
    ESP3PacketType,
    ESP3StreamDecoder,
)
from enocean_mqtt.esp3.radio import (
    RadioERP1Telegram,
    build_radio_erp1_frame,
    packet_to_radio_erp1,
    radio_erp1_to_replay_telegram,
)
from enocean_mqtt.replay.models import ReplayTelegram

LOGGER = logging.getLogger(__name__)

TelegramCallback = Callable[[ReplayTelegram], None]
SERIAL_READ_SIZE = 256


class SerialLike(Protocol):
    """Protocol for pyserial-compatible objects."""

    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class TransportMetrics:
    """Basic ESP3 transport counters."""

    received_esp3_frames: int = 0
    received_radio_erp1_telegrams: int = 0
    accepted_radio_erp1_telegrams: int = 0
    failed_radio_erp1_telegrams: int = 0
    crc_errors: int = 0
    unsupported_packet_types: int = 0
    bytes_received: int = 0
    bytes_transmitted: int = 0
    last_rx_timestamp: float | None = None
    last_tx_timestamp: float | None = None


class ESP3SerialTransport:
    """Read ESP3 RADIO_ERP1 packets from a serial interface."""

    def __init__(
        self,
        *,
        interface_id: str | None = None,
        port: str,
        baudrate: int = 57600,
        base_id: str | None = None,
        timeout_seconds: float = 1.0,
        reconnect_enabled: bool = True,
        reconnect_initial_delay_seconds: int = 5,
        reconnect_max_delay_seconds: int = 60,
        serial_factory: Callable[..., SerialLike] | None = None,
    ) -> None:
        self.interface_id = interface_id or port
        self.port = port
        self.baudrate = baudrate
        self.base_id = base_id
        self.timeout_seconds = timeout_seconds
        self.reconnect_enabled = reconnect_enabled
        self.reconnect_initial_delay_seconds = reconnect_initial_delay_seconds
        self.reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self._serial_factory = serial_factory or _default_serial_factory()
        self._decoder = ESP3StreamDecoder()
        self._telegram_ids = count(1)
        self._stop_event = threading.Event()
        self._send_lock = threading.Lock()
        self._response_codes: Queue[int] = Queue()
        self._thread: threading.Thread | None = None
        self._serial: SerialLike | None = None
        self._status = "initialized"
        self._last_error: str | None = None
        self.metrics = TransportMetrics()

    @property
    def is_running(self) -> bool:
        """Return whether the transport worker thread is alive."""

        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> dict[str, object]:
        """Return current transport status and counters."""

        return {
            "transport": "serial_esp3",
            "interface_id": self.interface_id,
            "port": self.port,
            "base_id": self.base_id,
            "status": self._status,
            "connected": self._status == "connected" and self.is_running,
            "last_error": self._last_error,
            "metrics": {
                "received_esp3_frames": self.metrics.received_esp3_frames,
                "received_radio_erp1_telegrams": (self.metrics.received_radio_erp1_telegrams),
                "accepted_radio_erp1_telegrams": self.metrics.accepted_radio_erp1_telegrams,
                "failed_radio_erp1_telegrams": (self.metrics.failed_radio_erp1_telegrams),
                "crc_errors": self.metrics.crc_errors,
                "unsupported_packet_types": self.metrics.unsupported_packet_types,
                "bytes_received": self.metrics.bytes_received,
                "bytes_transmitted": self.metrics.bytes_transmitted,
                "last_rx_timestamp": self.metrics.last_rx_timestamp,
                "last_tx_timestamp": self.metrics.last_tx_timestamp,
            },
        }

    def start(self, callback: TelegramCallback) -> None:
        """Start reading from the serial interface in a background thread."""

        if self.is_running:
            raise RuntimeError("ESP3 serial transport is already running")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.run_forever,
            args=(callback,),
            daemon=True,
            name=f"enocean-mqtt-esp3-{self.interface_id}",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background reader and close the serial port."""

        self._stop_event.set()
        self._status = "stopped"

        serial_port = self._serial
        if serial_port is not None:
            serial_port.close()

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
            self._serial = None

    def send(self, telegram: RadioERP1Telegram) -> None:
        """Send one RADIO_ERP1 telegram through the serial interface."""

        if self._serial is None:
            raise RuntimeError("ESP3 serial transport is not connected")

        frame = build_radio_erp1_frame(telegram)

        with self._send_lock:
            while True:
                try:
                    self._response_codes.get_nowait()
                except Empty:
                    break

            bytes_written = self._serial.write(frame)
            self.metrics.bytes_transmitted += bytes_written

            if bytes_written != len(frame):
                self.metrics.failed_radio_erp1_telegrams += 1
                raise RuntimeError(f"Incomplete ESP3 write: {bytes_written} of {len(frame)} bytes")

            try:
                response_code = self._response_codes.get(timeout=self.timeout_seconds)
            except Empty as exc:
                self.metrics.failed_radio_erp1_telegrams += 1
                raise TimeoutError("Timed out waiting for ESP3 TX response") from exc

            if response_code != 0:
                self.metrics.failed_radio_erp1_telegrams += 1
                raise RuntimeError(f"ESP3 TX failed with response code 0x{response_code:02X}")

            self.metrics.accepted_radio_erp1_telegrams += 1
            self.metrics.last_tx_timestamp = round(time.time(), 3)

    def run_forever(self, callback: TelegramCallback) -> None:
        """Read ESP3 packets until stopped."""

        reconnect_delay = self.reconnect_initial_delay_seconds

        while not self._stop_event.is_set():
            self._status = "connecting"
            try:
                self._serial = self._serial_factory(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout_seconds,
                )
                self._last_error = None
                self._status = "connected"
                reconnect_delay = self.reconnect_initial_delay_seconds
                LOGGER.info("ESP3 serial transport opened on %s", self.port)
                self._read_connected(callback)
            except (OSError, TypeError) as exc:
                if self._stop_event.is_set():
                    break
                self._status = "error"
                self._last_error = str(exc)
                LOGGER.error("ESP3 serial transport failed on %s: %s", self.port, exc)
            finally:
                if self._serial is not None:
                    self._serial.close()
                    self._serial = None

            if not self.reconnect_enabled or self._stop_event.is_set():
                break

            self._status = "reconnecting"
            if self._stop_event.wait(timeout=reconnect_delay):
                break
            reconnect_delay = min(
                reconnect_delay * 2,
                self.reconnect_max_delay_seconds,
            )

        if self._stop_event.is_set():
            self._status = "stopped"
        LOGGER.info("ESP3 serial transport closed on %s", self.port)

    def _read_connected(self, callback: TelegramCallback) -> None:
        """Read and dispatch packets while the current serial port is open."""

        while not self._stop_event.is_set():
            serial_port = self._serial
            if serial_port is None:
                raise OSError("ESP3 serial transport is not connected")
            chunk = serial_port.read(SERIAL_READ_SIZE)

            if not chunk:
                continue

            self.metrics.bytes_received += len(chunk)

            try:
                packets = self._decoder.feed(chunk)
            except ESP3ChecksumError:
                self.metrics.crc_errors += 1
                LOGGER.warning("Dropping ESP3 frame with invalid CRC")
                continue

            for packet in packets:
                self.metrics.received_esp3_frames += 1

                if packet.packet_type == ESP3PacketType.RESPONSE:
                    response = packet_to_response(packet)
                    self._response_codes.put(response.return_code)
                    continue

                if packet.packet_type != ESP3PacketType.RADIO_ERP1:
                    self.metrics.unsupported_packet_types += 1
                    LOGGER.debug(
                        "Ignoring ESP3 packet type %s",
                        packet.packet_type_name,
                    )
                    continue

                radio_telegram = packet_to_radio_erp1(packet)
                self.metrics.received_radio_erp1_telegrams += 1
                self.metrics.last_rx_timestamp = round(time.time(), 3)
                telegram = radio_erp1_to_replay_telegram(
                    radio_telegram,
                    telegram_id=next(self._telegram_ids),
                    port=self.port,
                    interface_id=self.interface_id,
                )
                try:
                    callback(telegram)
                except Exception:
                    # Persistence, MQTT or decoding callbacks must not kill the
                    # serial reader.  Keep receiving subsequent frames while
                    # preserving the complete failure in the service log.
                    LOGGER.exception(
                        "ESP3 telegram callback failed on interface %s; "
                        "continuing receive loop",
                        self.interface_id,
                    )


def _default_serial_factory() -> Callable[..., SerialLike]:
    import serial  # type: ignore[import-untyped]

    return cast(Callable[..., SerialLike], serial.Serial)
