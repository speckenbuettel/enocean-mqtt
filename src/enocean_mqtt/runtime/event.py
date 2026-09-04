"""Unified runtime telegram event model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransmissionStatus = Literal["accepted", "disabled", "failed"]


@dataclass(frozen=True, slots=True)
class RadioSendResult:
    """Outcome of handing one generated telegram to an EnOcean interface."""

    interface_id: str | None
    transmission: TransmissionStatus
    error: str | None = None


@dataclass(slots=True)
class RuntimeTelegramEvent:
    """Unified runtime telegram event representation.

    This object provides a stable internal event abstraction between:
    - replay runtimes
    - live serial runtimes
    - gateway decoding
    - busmonitor publishing
    - TX runtimes
    - SQLite persistence
    - Web API history queries
    - future OBS adapters
    """

    timestamp_local: str | None
    timestamp_unix: float | None

    direction: str
    runtime_mode: str = "live"

    sender_id: str | None = None
    destination_id: str | None = None

    rorg: str | None = None
    data: str | None = None

    erp1_status: str | None = None

    raw_telegram: str | None = None

    repeater_count: int | None = None
    repeater_permitted: bool | None = None
    hash_type: str | None = None
    contains_teach_in: bool | None = None

    subtelegram_count: int | None = None
    rssi_dbm: int | None = None

    port: str | None = None
    interface_id: str | None = None
    transmission: TransmissionStatus | None = None


def tx_event_to_mqtt_payload(event: RuntimeTelegramEvent) -> dict[str, object]:
    """Serialize a TX event according to the canonical MQTT model."""

    return {
        "timestamp_local": event.timestamp_local,
        "timestamp_unix": event.timestamp_unix,
        "direction": "tx",
        "rorg": event.rorg,
        "sender_id": event.sender_id,
        "destination_id": event.destination_id,
        "data": event.data,
        "teach_in": bool(event.contains_teach_in),
        "erp1_status": event.erp1_status,
        "raw_telegram": event.raw_telegram,
        "subtelegram_count": event.subtelegram_count,
        "interface_id": event.interface_id,
        "port": event.port,
        "transmission": event.transmission,
    }
