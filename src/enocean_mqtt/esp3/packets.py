"""ESP3 packet parsing and encoding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from enocean_mqtt.esp3.crc import crc8

SYNC_BYTE = 0x55


class ESP3PacketType(IntEnum):
    """ESP3 packet type identifiers used by the runtime."""

    RADIO_ERP1 = 0x01
    RESPONSE = 0x02
    RADIO_SUB_TEL = 0x03
    EVENT = 0x04
    COMMON_COMMAND = 0x05
    SMART_ACK_COMMAND = 0x06
    REMOTE_MAN_COMMAND = 0x07
    RADIO_MESSAGE = 0x09
    RADIO_ERP2 = 0x0A


class ESP3Error(Exception):
    """Base class for ESP3 parsing errors."""


class ESP3FrameError(ESP3Error):
    """Raised when an ESP3 frame is structurally invalid."""


class ESP3ChecksumError(ESP3Error):
    """Raised when an ESP3 frame CRC is invalid."""


@dataclass(frozen=True, slots=True)
class ESP3Packet:
    """Parsed ESP3 packet."""

    packet_type: int
    data: bytes
    optional_data: bytes
    raw_frame: bytes

    @property
    def packet_type_name(self) -> str:
        """Return the symbolic packet type name when known."""

        try:
            return ESP3PacketType(self.packet_type).name
        except ValueError:
            return f"UNKNOWN_0x{self.packet_type:02X}"

    @property
    def data_hex(self) -> str:
        """Return compact uppercase data hex."""

        return self.data.hex().upper()

    @property
    def optional_hex(self) -> str:
        """Return compact uppercase optional-data hex."""

        return self.optional_data.hex().upper()

    @property
    def raw_hex(self) -> str:
        """Return compact uppercase full-frame hex."""

        return self.raw_frame.hex().upper()


def parse_esp3_frame(frame: bytes) -> ESP3Packet:
    """Parse and validate one complete ESP3 frame."""

    if len(frame) < 7:
        raise ESP3FrameError("ESP3 frame is too short")

    if frame[0] != SYNC_BYTE:
        raise ESP3FrameError("ESP3 frame does not start with sync byte 0x55")

    data_length = int.from_bytes(frame[1:3], byteorder="big")
    optional_length = frame[3]
    packet_type = frame[4]
    expected_length = 6 + data_length + optional_length + 1

    if len(frame) != expected_length:
        raise ESP3FrameError(
            f"ESP3 frame length mismatch: expected {expected_length}, got {len(frame)}"
        )

    header = frame[1:5]
    crc_header = frame[5]

    if crc8(header) != crc_header:
        raise ESP3ChecksumError("ESP3 header CRC mismatch")

    data_start = 6
    data_end = data_start + data_length
    optional_end = data_end + optional_length
    data = frame[data_start:data_end]
    optional_data = frame[data_end:optional_end]
    crc_data = frame[optional_end]

    if crc8(data + optional_data) != crc_data:
        raise ESP3ChecksumError("ESP3 data CRC mismatch")

    return ESP3Packet(
        packet_type=packet_type,
        data=data,
        optional_data=optional_data,
        raw_frame=frame,
    )


def build_esp3_frame(
    *,
    packet_type: int,
    data: bytes,
    optional_data: bytes = b"",
) -> bytes:
    """Build one complete ESP3 frame."""

    if len(data) > 0xFFFF:
        raise ESP3FrameError("ESP3 data is too large")

    if len(optional_data) > 0xFF:
        raise ESP3FrameError("ESP3 optional data is too large")

    header = (
        len(data).to_bytes(2, byteorder="big")
        + bytes([len(optional_data), packet_type])
    )

    body = data + optional_data

    return (
        bytes([SYNC_BYTE])
        + header
        + bytes([crc8(header)])
        + body
        + bytes([crc8(body)])
    )


class ESP3StreamDecoder:
    """Incrementally decode ESP3 frames from arbitrary byte chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[ESP3Packet]:
        """Feed bytes and return all complete packets decoded from them."""

        self._buffer.extend(chunk)
        packets: list[ESP3Packet] = []

        while True:
            sync_index = self._find_sync()

            if sync_index is None:
                self._buffer.clear()
                break

            if sync_index > 0:
                del self._buffer[:sync_index]

            if len(self._buffer) < 6:
                break

            data_length = int.from_bytes(self._buffer[1:3], byteorder="big")
            optional_length = self._buffer[3]
            frame_length = 6 + data_length + optional_length + 1

            if len(self._buffer) < frame_length:
                break

            frame = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            packets.append(parse_esp3_frame(frame))

        return packets

    def _find_sync(self) -> int | None:
        try:
            return self._buffer.index(SYNC_BYTE)
        except ValueError:
            return None
