"""MQTT RX telegram injection support."""

from __future__ import annotations

import re
from dataclasses import dataclass

from enocean_mqtt.replay.models import ReplayTelegram

HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]+$")

FIXED_RORG_LENGTHS = {
    "F6": 7,
    "D5": 7,
    "A5": 10,
}


class MQTTInjectError(ValueError):
    """Raised for invalid injected telegrams."""


@dataclass(slots=True)
class InjectedTelegram:
    """Validated injected telegram representation."""

    raw_hex: str
    rorg: str
    data_hex: str
    sender_id: str
    status: str

    def to_replay_telegram(self) -> ReplayTelegram:
        """Build ReplayTelegram compatible with runtime pipeline."""

        return ReplayTelegram(
            telegram_id=0,
            timestamp=None,
            protocol="EnOcean",
            telegram_type="Radio",
            direction="rx",
            eno_id=self.sender_id,
            eno_rorg=self.rorg,
            eno_data=self.data_hex,
            eno_rssi=None,
            raw_frame_data=self.raw_hex,
            raw_apdu_data=self.raw_hex,
            properties={},
            source="mqtt_inject",
            destination_id=None,
            status=self.status,
            port="inject",
        )



def parse_injected_telegram(payload: str) -> InjectedTelegram:
    """Validate and normalize injected ERP1 telegram."""

    compact = "".join(payload.split()).upper()

    if not compact:
        raise MQTTInjectError("empty_payload")

    if not HEX_PATTERN.match(compact):
        raise MQTTInjectError("non_hex_character")

    if len(compact) % 2 != 0:
        raise MQTTInjectError("odd_hex_length")

    telegram_bytes = bytes.fromhex(compact)

    if len(telegram_bytes) < 6:
        raise MQTTInjectError("telegram_too_short")

    rorg = f"{telegram_bytes[0]:02X}"

    expected_length = FIXED_RORG_LENGTHS.get(rorg)

    if expected_length is not None and len(telegram_bytes) != expected_length:
        raise MQTTInjectError(
            f"invalid_length_for_rorg_{rorg}"
        )

    sender_id = telegram_bytes[-5:-1].hex().upper()
    status = f"{telegram_bytes[-1]:02X}"

    data_hex = telegram_bytes[1:-5].hex().upper()

    return InjectedTelegram(
        raw_hex=compact,
        rorg=rorg,
        data_hex=data_hex,
        sender_id=sender_id,
        status=status,
    )
