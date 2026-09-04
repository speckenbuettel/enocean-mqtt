"""ESP3 RADIO_ERP1 telegram normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from enocean_mqtt.esp3.packets import ESP3Packet, ESP3PacketType, build_esp3_frame
from enocean_mqtt.replay.models import ReplayTelegram

BROADCAST_DESTINATION_ID = "FFFFFFFF"


class ESP3RadioError(Exception):
    """Raised when a radio packet cannot be normalized."""


@dataclass(frozen=True, slots=True)
class RadioERP1Telegram:
    """Normalized RADIO_ERP1 telegram extracted from an ESP3 packet."""

    rorg: str
    data: str
    sender_id: str
    status: str
    destination_id: str = BROADCAST_DESTINATION_ID
    subtelegram_count: int | None = None
    rssi_dbm: int | None = None
    security_level: int | None = None
    tick_count: int | None = None
    dbm: int = 0xFF

    @property
    def raw_telegram(self) -> str:
        """Return canonical ERP1 telegram hex."""

        return f"{self.rorg}{self.data}{self.sender_id}{self.status}"


def packet_to_radio_erp1(packet: ESP3Packet) -> RadioERP1Telegram:
    """Extract an ERP1 radio telegram from a RADIO_ERP1 packet."""

    if packet.packet_type != ESP3PacketType.RADIO_ERP1:
        raise ESP3RadioError(
            f"Unsupported packet type for RADIO_ERP1 normalization: {packet.packet_type_name}"
        )

    if len(packet.data) < 6:
        raise ESP3RadioError("RADIO_ERP1 data is too short")

    rorg = packet.data[0]
    payload = packet.data[1:-5]
    sender = packet.data[-5:-1]
    status = packet.data[-1]

    destination_id = BROADCAST_DESTINATION_ID
    subtelegram_count = None
    rssi_dbm = None
    security_level = None
    tick_count = None
    dbm = 0xFF

    if packet.optional_data:
        if len(packet.optional_data) >= 1:
            subtelegram_count = packet.optional_data[0]

        if len(packet.optional_data) >= 5:
            destination_id = packet.optional_data[1:5].hex().upper()

        if len(packet.optional_data) >= 6:
            dbm = packet.optional_data[5]
            rssi_dbm = -dbm

        if len(packet.optional_data) >= 7:
            security_level = packet.optional_data[6]

        if len(packet.optional_data) >= 11:
            tick_count = int.from_bytes(packet.optional_data[7:11], byteorder="big")

    return RadioERP1Telegram(
        rorg=f"{rorg:02X}",
        data=payload.hex().upper(),
        sender_id=sender.hex().upper(),
        status=f"{status:02X}",
        destination_id=destination_id,
        subtelegram_count=subtelegram_count,
        rssi_dbm=rssi_dbm,
        security_level=security_level,
        tick_count=tick_count,
        dbm=dbm,
    )


def build_radio_erp1_packet(telegram: RadioERP1Telegram) -> ESP3Packet:
    """Build a RADIO_ERP1 ESP3 packet from a raw telegram."""

    data = (
        _hex_bytes(telegram.rorg, expected_length=1)
        + _hex_bytes(telegram.data)
        + _hex_bytes(telegram.sender_id, expected_length=4)
        + _hex_bytes(telegram.status, expected_length=1)
    )
    optional_data = (
        bytes([_byte_or_default(telegram.subtelegram_count, 0x03)])
        + _hex_bytes(telegram.destination_id, expected_length=4)
        + bytes([telegram.dbm])
        + bytes([_byte_or_default(telegram.security_level, 0x00)])
    )
    frame = build_esp3_frame(
        packet_type=ESP3PacketType.RADIO_ERP1,
        data=data,
        optional_data=optional_data,
    )

    return ESP3Packet(
        packet_type=ESP3PacketType.RADIO_ERP1,
        data=data,
        optional_data=optional_data,
        raw_frame=frame,
    )


def build_radio_erp1_frame(telegram: RadioERP1Telegram) -> bytes:
    """Build a RADIO_ERP1 ESP3 frame from a raw telegram."""

    return build_radio_erp1_packet(telegram).raw_frame


def radio_erp1_to_replay_telegram(
    telegram: RadioERP1Telegram,
    *,
    telegram_id: int,
    port: str | None = None,
    interface_id: str | None = None,
    timestamp: datetime | None = None,
) -> ReplayTelegram:
    """Convert a normalized RADIO_ERP1 telegram into the shared runtime model."""

    timestamp_value = timestamp or datetime.now(tz=UTC)

    return ReplayTelegram(
        telegram_id=telegram_id,
        timestamp=timestamp_value.isoformat(),
        protocol="ESP3",
        telegram_type="0",
        direction="rx",
        eno_id=telegram.sender_id,
        eno_rorg=telegram.rorg,
        eno_data=telegram.data,
        eno_rssi=(
            str(telegram.rssi_dbm)
            if telegram.rssi_dbm is not None
            else None
        ),
        raw_frame_data=None,
        raw_apdu_data=telegram.raw_telegram,
        properties={},
        source="esp3_serial",
        destination_id=telegram.destination_id,
        status=telegram.status,
        port=port,
        optional_data=None,
        subtelegram_count=telegram.subtelegram_count,
        security_level=telegram.security_level,
        tick_count=telegram.tick_count,
        interface_id=interface_id,
    )


def _hex_bytes(value: str, expected_length: int | None = None) -> bytes:
    normalized = value.replace(" ", "").upper()

    if len(normalized) % 2:
        raise ESP3RadioError(f"Hex value must have an even length: {value}")

    try:
        parsed = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ESP3RadioError(f"Invalid hex value: {value}") from exc

    if expected_length is not None and len(parsed) != expected_length:
        raise ESP3RadioError(
            f"Expected {expected_length} bytes, got {len(parsed)} for {value}"
        )

    return parsed


def _byte_or_default(value: int | None, default: int) -> int:
    return default if value is None else value
