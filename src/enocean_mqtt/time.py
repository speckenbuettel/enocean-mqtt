"""Canonical timestamp helpers for MQTT payloads."""

from __future__ import annotations

from datetime import datetime


def format_timestamp_local(value: datetime) -> str:
    """Return ISO-8601 timestamp with millisecond precision."""

    return value.astimezone().isoformat(timespec="milliseconds")


def format_timestamp_unix(value: datetime) -> float:
    """Return Unix timestamp rounded to millisecond precision."""

    return round(value.timestamp(), 3)


def build_timestamp_fields(value: datetime | None = None) -> dict[str, float | str]:
    """Build canonical MQTT timestamp fields."""

    timestamp = value or datetime.now().astimezone()

    return {
        "timestamp_local": format_timestamp_local(timestamp),
        "timestamp_unix": format_timestamp_unix(timestamp),
    }
