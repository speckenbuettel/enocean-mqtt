"""Busmonitor-layer export helpers.

This module intentionally exports raw/normalized telegram information only.
No semantic device state or EEP decoding is performed here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from enocean_mqtt.replay.models import ReplayTelegram
from enocean_mqtt.runtime.event import RuntimeTelegramEvent, tx_event_to_mqtt_payload
from enocean_mqtt.time import build_timestamp_fields

LIVE_TELEGRAM_SOURCES = {"esp3_serial", "mqtt_inject"}


class TimestampFields(TypedDict):
    """Normalized timestamp fields."""

    timestamp_local: str
    timestamp_unix: float


class ERP1Status(TypedDict):
    """Decoded ERP1 status fields."""

    repeater_count: int
    repeater_permitted: bool
    hash_type: str
    contains_teach_in: bool


def replay_telegram_to_runtime_event(
    telegram: ReplayTelegram,
) -> RuntimeTelegramEvent:
    """Convert ReplayTelegram into unified RuntimeTelegramEvent."""

    timestamp_fields = _build_timestamp_fields(telegram.timestamp)

    normalized_raw_telegram = _build_canonical_raw_telegram(
        rorg=telegram.eno_rorg,
        data=telegram.payload_hex,
        sender_id=telegram.sender_id,
        status=telegram.status,
    )

    if normalized_raw_telegram is None:
        normalized_raw_telegram = telegram.raw_apdu_data or telegram.raw_frame_data

    erp1_status_hex = _extract_erp1_status(
        normalized_raw_telegram,
        telegram.status,
    )

    erp1_status = _decode_erp1_status(
        erp1_status_hex,
    )

    runtime_mode = "live" if telegram.source in LIVE_TELEGRAM_SOURCES else "replay"

    return RuntimeTelegramEvent(
        timestamp_local=timestamp_fields["timestamp_local"],
        timestamp_unix=timestamp_fields["timestamp_unix"],
        direction=telegram.normalized_direction or "rx",
        runtime_mode=runtime_mode,
        sender_id=telegram.sender_id,
        destination_id=telegram.destination_id or "FFFFFFFF",
        rorg=telegram.eno_rorg,
        data=telegram.payload_hex,
        erp1_status=erp1_status_hex,
        raw_telegram=normalized_raw_telegram,
        repeater_count=(erp1_status["repeater_count"] if erp1_status else None),
        repeater_permitted=(erp1_status["repeater_permitted"] if erp1_status else None),
        contains_teach_in=(erp1_status["contains_teach_in"] if erp1_status else None),
        hash_type=(erp1_status["hash_type"] if erp1_status else None),
        subtelegram_count=telegram.subtelegram_count,
        rssi_dbm=_safe_rssi(telegram.eno_rssi),
        port=telegram.port,
        interface_id=telegram.interface_id,
    )


def runtime_event_to_payload(
    event: RuntimeTelegramEvent,
) -> dict[str, Any]:
    """Convert RuntimeTelegramEvent into MQTT payload."""

    if event.direction == "tx":
        return tx_event_to_mqtt_payload(event)

    payload: dict[str, Any] = {
        "timestamp_local": event.timestamp_local,
        "timestamp_unix": event.timestamp_unix,
        "direction": event.direction,
        "runtime_mode": event.runtime_mode,
        "rorg": event.rorg,
        "sender_id": event.sender_id,
        "destination_id": event.destination_id,
        "data": event.data,
        "erp1_status": event.erp1_status,
        "erp1_status_decoded": _event_erp1_status_decoded(event),
        "raw_telegram": event.raw_telegram,
        "teach_in": _decode_teach_in(event.rorg, event.data),
        "subtelegram_count": event.subtelegram_count,
        "rssi_dbm": event.rssi_dbm,
        "port": event.port,
        "interface_id": event.interface_id,
        "transmission": event.transmission,
    }

    return {key: value for key, value in payload.items() if value is not None}


def _build_canonical_raw_telegram(
    rorg: str | None,
    data: str | None,
    sender_id: str | None,
    status: str | None,
) -> str | None:
    """Build canonical ERP1 telegram.

    Format:
    <RORG><DATA><SENDER_ID><STATUS>
    """

    if not rorg or not data or not sender_id:
        return None

    status_byte = (status or "00").upper()

    telegram_hex = rorg.upper() + data.upper() + sender_id.upper() + status_byte

    return " ".join(telegram_hex[index : index + 2] for index in range(0, len(telegram_hex), 2))


def _extract_erp1_status(
    raw_telegram: str | None,
    fallback_status: str | None,
) -> str | None:
    """Extract ERP1 status byte from canonical telegram."""

    if raw_telegram:
        parts = raw_telegram.strip().split()

        if parts:
            return parts[-1].upper()

    if fallback_status:
        return fallback_status.upper()

    return None


def _event_erp1_status_decoded(
    event: RuntimeTelegramEvent,
) -> dict[str, Any] | None:
    erp1_status_decoded: dict[str, Any] = {
        "repeater_count": event.repeater_count,
        "repeater_permitted": event.repeater_permitted,
        "hash_type": event.hash_type,
        "contains_teach_in": event.contains_teach_in,
    }

    if not any(value is not None for value in erp1_status_decoded.values()):
        return None

    return {key: value for key, value in erp1_status_decoded.items() if value is not None}


def _decode_teach_in(
    rorg: str | None,
    data: str | None,
) -> dict[str, Any] | None:
    if rorg is None or data is None:
        return None

    normalized_rorg = rorg.upper()
    normalized_data = data.replace(" ", "").upper()

    if normalized_rorg == "A5" and len(normalized_data) == 8:
        try:
            payload = int(normalized_data, 16)
        except ValueError:
            return None

        db0 = payload & 0xFF

        if db0 & 0x08:
            return None

        func = (payload >> 26) & 0x3F
        type_value = (payload >> 19) & 0x7F
        manufacturer_id = (payload >> 8) & 0x7FF
        lrn_type = bool(db0 & 0x80)

        return {
            "detected": True,
            "method": (
                "4bs_unidirectional_with_eep" if lrn_type else "4bs_unidirectional_profile_less"
            ),
            "rorg": normalized_rorg,
            "func": f"0x{func:02X}",
            "type": f"0x{type_value:02X}",
            "manufacturer_id": f"0x{manufacturer_id:03X}",
            "db0": f"0x{db0:02X}",
        }

    if normalized_rorg == "D5" and len(normalized_data) == 2:
        try:
            db0 = int(normalized_data, 16)
        except ValueError:
            return None

        if db0 & 0x08:
            return None

        return {
            "detected": True,
            "method": "1bs_teach_in",
            "rorg": normalized_rorg,
            "db0": f"0x{db0:02X}",
        }

    return None


def _build_timestamp_fields(
    timestamp: str | None,
) -> TimestampFields:
    """Build unified timestamp fields."""

    if not timestamp:
        fields = build_timestamp_fields()
    else:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        fields = build_timestamp_fields(parsed)

    return {
        "timestamp_local": str(fields["timestamp_local"]),
        "timestamp_unix": float(fields["timestamp_unix"]),
    }


def _decode_erp1_status(
    status: str | None,
) -> ERP1Status | None:
    """Decode ERP1 status byte into protocol-oriented fields."""

    if status is None:
        return None

    try:
        value = int(status, 16)
    except ValueError:
        return None

    return {
        "repeater_count": value & 0b00001111,
        "repeater_permitted": True,
        "hash_type": "checksum",
        "contains_teach_in": bool(value & 0b00100000),
    }


def _safe_rssi(value: str | None) -> int | None:
    """Return RSSI only for plausible dBm values."""

    if value is None or value == "":
        return None

    try:
        parsed = int(value)
    except ValueError:
        return None

    if parsed > 0:
        return None

    return parsed
