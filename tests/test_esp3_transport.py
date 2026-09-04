from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event
from time import sleep

import pytest

from enocean_mqtt.esp3 import (
    CommonCommand,
    ESP3ChecksumError,
    ESP3CommandError,
    ESP3PacketType,
    ESP3StreamDecoder,
    RadioERP1Telegram,
    ResponseCode,
    build_common_command_frame,
    build_esp3_frame,
    build_radio_erp1_frame,
    build_read_base_id_frame,
    packet_to_radio_erp1,
    packet_to_response,
    parse_esp3_frame,
    radio_erp1_to_replay_telegram,
    response_to_base_id,
)
from enocean_mqtt.esp3.serial_transport import ESP3SerialTransport
from enocean_mqtt.replay.busmonitor_export import replay_telegram_to_runtime_event


def test_parse_radio_erp1_frame() -> None:
    frame = _sample_radio_frame()

    packet = parse_esp3_frame(frame)

    assert packet.packet_type == ESP3PacketType.RADIO_ERP1
    assert packet.data_hex == "F670052523B100"
    assert packet.optional_hex == "01FFFFFFFF4700"

    telegram = packet_to_radio_erp1(packet)

    assert telegram.rorg == "F6"
    assert telegram.data == "70"
    assert telegram.sender_id == "052523B1"
    assert telegram.status == "00"
    assert telegram.destination_id == "FFFFFFFF"
    assert telegram.subtelegram_count == 1
    assert telegram.rssi_dbm == -71
    assert telegram.security_level == 0


def test_build_frame_roundtrip() -> None:
    data = bytes.fromhex("A596000008052523B100")
    optional_data = bytes.fromhex("01FFFFFFFF4700")

    frame = build_esp3_frame(
        packet_type=ESP3PacketType.RADIO_ERP1,
        data=data,
        optional_data=optional_data,
    )

    packet = parse_esp3_frame(frame)

    assert packet.data == data
    assert packet.optional_data == optional_data


def test_build_radio_erp1_tx_frame_uses_expected_optional_defaults() -> None:
    frame = build_radio_erp1_frame(
        RadioERP1Telegram(
            rorg="F6",
            data="30",
            sender_id="FF800001",
            status="30",
        )
    )

    packet = parse_esp3_frame(frame)

    assert packet.packet_type == ESP3PacketType.RADIO_ERP1
    assert packet.data_hex == "F630FF80000130"
    assert packet.optional_hex == "03FFFFFFFFFF00"


def test_stream_decoder_handles_split_frames_and_leading_noise() -> None:
    frame = build_esp3_frame(
        packet_type=ESP3PacketType.RADIO_ERP1,
        data=bytes.fromhex("D509052523B100"),
        optional_data=bytes.fromhex("01FFFFFFFF3F00"),
    )
    decoder = ESP3StreamDecoder()

    assert decoder.feed(b"\x00\x01" + frame[:4]) == []
    packets = decoder.feed(frame[4:])

    assert len(packets) == 1
    assert packets[0].data_hex == "D509052523B100"


def test_common_command_builds_read_base_id_frame() -> None:
    frame = build_read_base_id_frame()
    packet = parse_esp3_frame(frame)

    assert packet.packet_type == ESP3PacketType.COMMON_COMMAND
    assert packet.data == bytes([CommonCommand.CO_RD_IDBASE])
    assert frame == build_common_command_frame(CommonCommand.CO_RD_IDBASE)


def test_response_extracts_base_id() -> None:
    packet = parse_esp3_frame(
        build_esp3_frame(
            packet_type=ESP3PacketType.RESPONSE,
            data=bytes([ResponseCode.RET_OK]) + bytes.fromhex("FF8000007F"),
        )
    )

    response = packet_to_response(packet)

    assert response.ok is True
    assert response_to_base_id(response) == "FF800000"


def test_failed_response_rejects_base_id() -> None:
    response = packet_to_response(
        parse_esp3_frame(
            build_esp3_frame(
                packet_type=ESP3PacketType.RESPONSE,
                data=bytes([ResponseCode.RET_NOT_SUPPORTED]),
            )
        )
    )

    with pytest.raises(ESP3CommandError):
        response_to_base_id(response)


def test_invalid_crc_raises_checksum_error() -> None:
    frame = bytearray(
        build_esp3_frame(
            packet_type=ESP3PacketType.RADIO_ERP1,
            data=bytes.fromhex("F670052523B100"),
        )
    )
    frame[-1] ^= 0xFF

    with pytest.raises(ESP3ChecksumError):
        parse_esp3_frame(bytes(frame))


def test_radio_erp1_converts_to_replay_telegram() -> None:
    packet = parse_esp3_frame(_sample_radio_frame())
    radio_telegram = packet_to_radio_erp1(packet)
    timestamp = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

    replay_telegram = radio_erp1_to_replay_telegram(
        radio_telegram,
        telegram_id=42,
        port="COM3",
        interface_id="usb300_01",
        timestamp=timestamp,
    )

    assert replay_telegram.telegram_id == 42
    assert replay_telegram.protocol == "ESP3"
    assert replay_telegram.source == "esp3_serial"
    assert replay_telegram.direction == "rx"
    assert replay_telegram.eno_rorg == "F6"
    assert replay_telegram.eno_data == "70"
    assert replay_telegram.sender_id == "052523B1"
    assert replay_telegram.status == "00"
    assert replay_telegram.destination_id == "FFFFFFFF"
    assert replay_telegram.eno_rssi == "-71"
    assert replay_telegram.port == "COM3"
    assert replay_telegram.interface_id == "usb300_01"


def test_serial_transport_reads_radio_erp1_with_fake_serial() -> None:
    frame = _sample_radio_frame()
    fake_serial = FakeSerial(chunks=[frame[:4], frame[4:]])
    received = []
    received_event = Event()
    transport = ESP3SerialTransport(
        interface_id="usb300_01",
        port="COM_TEST",
        serial_factory=lambda **_kwargs: fake_serial,
    )

    def handle_telegram(telegram) -> None:
        received.append(telegram)
        received_event.set()

    transport.start(handle_telegram)
    assert received_event.wait(timeout=2.0)
    transport.stop()

    assert len(received) == 1
    assert received[0].source == "esp3_serial"
    assert received[0].eno_rorg == "F6"
    assert received[0].eno_data == "70"
    assert received[0].sender_id == "052523B1"
    assert received[0].port == "COM_TEST"
    assert received[0].interface_id == "usb300_01"
    assert transport.metrics.received_esp3_frames == 1
    assert transport.metrics.received_radio_erp1_telegrams == 1
    assert fake_serial.closed is True


def test_serial_transport_continues_after_telegram_callback_failure() -> None:
    frame = _sample_radio_frame()
    fake_serial = FakeSerial(chunks=[frame, frame])
    callback_attempts = 0
    second_callback = Event()
    transport = ESP3SerialTransport(
        interface_id="usb300_01",
        port="COM_TEST",
        serial_factory=lambda **_kwargs: fake_serial,
    )

    def handle_telegram(_telegram) -> None:
        nonlocal callback_attempts
        callback_attempts += 1
        if callback_attempts == 1:
            raise RuntimeError("persistence failed")
        second_callback.set()

    transport.start(handle_telegram)
    assert second_callback.wait(timeout=2.0)
    transport.stop()

    assert callback_attempts == 2
    assert transport.metrics.received_radio_erp1_telegrams == 2


def test_serial_transport_send_writes_radio_erp1_frame() -> None:
    fake_serial = FakeSerial(chunks=[])
    transport = ESP3SerialTransport(
        interface_id="usb300_01",
        port="COM_TEST",
        serial_factory=lambda **_kwargs: fake_serial,
    )
    transport._serial = fake_serial
    fake_serial.on_write = lambda: transport._response_codes.put(0)

    transport.send(
        RadioERP1Telegram(
            rorg="F6",
            data="30",
            sender_id="FF800001",
            status="30",
        )
    )

    packet = parse_esp3_frame(fake_serial.written[0])

    assert packet.packet_type == ESP3PacketType.RADIO_ERP1
    assert packet.data_hex == "F630FF80000130"
    assert transport.metrics.accepted_radio_erp1_telegrams == 1
    assert transport.metrics.bytes_transmitted == len(fake_serial.written[0])


def test_serial_transport_rejects_failed_tx_response() -> None:
    fake_serial = FakeSerial(chunks=[])
    transport = ESP3SerialTransport(
        interface_id="usb300_01",
        port="COM_TEST",
        serial_factory=lambda **_kwargs: fake_serial,
    )
    transport._serial = fake_serial
    fake_serial.on_write = lambda: transport._response_codes.put(3)

    with pytest.raises(RuntimeError, match="0x03"):
        transport.send(
            RadioERP1Telegram(
                rorg="F6",
                data="30",
                sender_id="FF800001",
                status="30",
            )
        )

    assert transport.metrics.failed_radio_erp1_telegrams == 1


def _sample_radio_frame() -> bytes:
    return build_esp3_frame(
        packet_type=ESP3PacketType.RADIO_ERP1,
        data=bytes.fromhex("F670052523B100"),
        optional_data=bytes.fromhex("01FFFFFFFF4700"),
    )


class FakeSerial:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.written: list[bytes] = []
        self.closed = False
        self.on_write: Callable[[], None] | None = None

    def read(self, _size: int = 1) -> bytes:
        if self.closed:
            return b""

        if self.chunks:
            return self.chunks.pop(0)

        sleep(0.01)
        return b""

    def write(self, data: bytes) -> int:
        self.written.append(data)
        if self.on_write is not None:
            self.on_write()
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_esp3_serial_telegram_converts_to_live_runtime_event() -> None:
    packet = parse_esp3_frame(_sample_radio_frame())
    radio_telegram = packet_to_radio_erp1(packet)
    replay_telegram = radio_erp1_to_replay_telegram(
        radio_telegram,
        telegram_id=42,
        port="COM3",
        interface_id="usb300_01",
        timestamp=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    runtime_event = replay_telegram_to_runtime_event(replay_telegram)

    assert runtime_event.runtime_mode == "live"
    assert runtime_event.port == "COM3"
    assert runtime_event.interface_id == "usb300_01"
