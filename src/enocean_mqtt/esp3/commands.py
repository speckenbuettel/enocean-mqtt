"""ESP3 common-command helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from enocean_mqtt.esp3.packets import ESP3Packet, ESP3PacketType, build_esp3_frame


class CommonCommand(IntEnum):
    """ESP3 common command identifiers used by the transport layer."""

    CO_RD_IDBASE = 0x08


class ResponseCode(IntEnum):
    """ESP3 response return codes."""

    RET_OK = 0x00
    RET_ERROR = 0x01
    RET_NOT_SUPPORTED = 0x02
    RET_WRONG_PARAM = 0x03
    RET_OPERATION_DENIED = 0x04


class ESP3CommandError(Exception):
    """Raised when an ESP3 command response is invalid or failed."""


@dataclass(frozen=True, slots=True)
class ESP3Response:
    """Parsed ESP3 RESPONSE packet."""

    return_code: int
    data: bytes

    @property
    def ok(self) -> bool:
        """Return whether the command completed successfully."""

        return self.return_code == ResponseCode.RET_OK


def build_common_command_frame(
    command: CommonCommand,
    payload: bytes = b"",
) -> bytes:
    """Build an ESP3 COMMON_COMMAND frame."""

    return build_esp3_frame(
        packet_type=ESP3PacketType.COMMON_COMMAND,
        data=bytes([command]) + payload,
    )


def build_read_base_id_frame() -> bytes:
    """Build a COMMON_COMMAND frame requesting the adapter base ID."""

    return build_common_command_frame(CommonCommand.CO_RD_IDBASE)


def packet_to_response(packet: ESP3Packet) -> ESP3Response:
    """Parse an ESP3 RESPONSE packet."""

    if packet.packet_type != ESP3PacketType.RESPONSE:
        raise ESP3CommandError(
            f"Expected RESPONSE packet, got {packet.packet_type_name}"
        )

    if not packet.data:
        raise ESP3CommandError("RESPONSE packet has no return code")

    return ESP3Response(
        return_code=packet.data[0],
        data=packet.data[1:],
    )


def response_to_base_id(response: ESP3Response) -> str:
    """Extract base ID from a successful CO_RD_IDBASE response."""

    if not response.ok:
        raise ESP3CommandError(
            f"CO_RD_IDBASE failed with response code 0x{response.return_code:02X}"
        )

    if len(response.data) < 4:
        raise ESP3CommandError("CO_RD_IDBASE response does not contain a base ID")

    return response.data[:4].hex().upper()
