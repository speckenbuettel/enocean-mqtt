"""Aggregated telegram activity API for the Metrics Web UI."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "sqlite" / "enocean-mqtt.sqlite"
DEFAULT_DEVICES_FILE = PROJECT_ROOT / "config" / "devices.json"

_ACTIVITY_RANGES: dict[str, tuple[int, int]] = {
    "1h": (60 * 60, 5 * 60),
    "24h": (24 * 60 * 60, 60 * 60),
    "3d": (3 * 24 * 60 * 60, 3 * 60 * 60),
    "7d": (7 * 24 * 60 * 60, 6 * 60 * 60),
}


def create_telegram_activity_router(
    *,
    database_path: str | Path = DEFAULT_DATABASE,
    devices_file: str | Path = DEFAULT_DEVICES_FILE,
) -> APIRouter:
    """Create the API route for server-side telegram activity aggregation."""

    router = APIRouter(tags=["Bus Monitor Metrics"])
    database = Path(database_path)
    devices = Path(devices_file)

    @router.get("/api/v1/busmonitor/metrics/telegram-activity")
    def get_telegram_activity(
        range_key: str = Query("24h", alias="range"),
    ) -> dict[str, Any]:
        if range_key not in _ACTIVITY_RANGES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported activity range: {range_key}",
            )
        return build_telegram_activity(
            database_path=database,
            devices_file=devices,
            range_key=range_key,
        )

    return router


def build_telegram_activity(
    *,
    database_path: Path,
    devices_file: Path,
    range_key: str,
    end_timestamp: float | None = None,
) -> dict[str, Any]:
    """Aggregate RX/TX telegrams into fixed buckets directly in SQLite.

    RX is split into known and unknown senders. TX is deliberately exposed as
    one total series because known/unknown is a sender classification and is
    not meaningful for gateway-originated traffic.
    """

    duration_seconds, bucket_seconds = _ACTIVITY_RANGES[range_key]
    end = float(end_timestamp if end_timestamp is not None else time.time())
    start = end - duration_seconds
    bucket_count = duration_seconds // bucket_seconds
    known_sender_ids = _load_known_sender_ids(devices_file)

    buckets = [
        {
            "start": _iso_timestamp(start + index * bucket_seconds),
            "start_unix": start + index * bucket_seconds,
            "rx": {"known": 0, "unknown": 0},
            "tx": 0,
        }
        for index in range(bucket_count)
    ]

    if not database_path.exists():
        return _activity_payload(
            range_key=range_key,
            start=start,
            end=end,
            bucket_seconds=bucket_seconds,
            buckets=buckets,
            available=False,
            issues=["SQLite database does not exist."],
        )

    placeholders = ", ".join("?" for _ in known_sender_ids)
    if known_sender_ids:
        category_sql = (
            "CASE "
            "WHEN lower(direction) = 'rx' "
            f"AND upper(sender_id) IN ({placeholders}) THEN 'known' "
            "WHEN lower(direction) = 'rx' THEN 'unknown' "
            "ELSE 'total' END"
        )
    else:
        category_sql = (
            "CASE WHEN lower(direction) = 'rx' THEN 'unknown' ELSE 'total' END"
        )

    query = f"""
        SELECT
            CAST((timestamp_unix - ?) / ? AS INTEGER) AS bucket_index,
            lower(direction) AS direction,
            {category_sql} AS category,
            COUNT(*) AS telegram_count
        FROM telegrams
        WHERE timestamp_unix >= ?
          AND timestamp_unix < ?
          AND lower(direction) IN ('rx', 'tx')
        GROUP BY bucket_index, direction, category
        ORDER BY bucket_index
    """

    parameters: list[Any] = [start, bucket_seconds]
    parameters.extend(known_sender_ids)
    parameters.extend([start, end])

    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Telegram activity query failed: {exc}",
        ) from exc

    for row in rows:
        index = int(row["bucket_index"])
        if index < 0 or index >= bucket_count:
            continue
        count = int(row["telegram_count"] or 0)
        direction = str(row["direction"] or "")
        category = str(row["category"] or "")
        if direction == "rx" and category in {"known", "unknown"}:
            buckets[index]["rx"][category] += count
        elif direction == "tx":
            buckets[index]["tx"] += count

    return _activity_payload(
        range_key=range_key,
        start=start,
        end=end,
        bucket_seconds=bucket_seconds,
        buckets=buckets,
        available=True,
        issues=[],
    )


def _activity_payload(
    *,
    range_key: str,
    start: float,
    end: float,
    bucket_seconds: int,
    buckets: list[dict[str, Any]],
    available: bool,
    issues: list[str],
) -> dict[str, Any]:
    return {
        "range": range_key,
        "from": _iso_timestamp(start),
        "to": _iso_timestamp(end),
        "bucket_seconds": bucket_seconds,
        "bucket_count": len(buckets),
        "available": available,
        "buckets": buckets,
        "issues": issues,
    }


def _load_known_sender_ids(devices_file: Path) -> list[str]:
    try:
        payload = json.loads(devices_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(devices, list):
        return []

    sender_ids = {
        normalized
        for device in devices
        if isinstance(device, dict)
        if (normalized := _normalize_sender_id(device.get("device_id")))
    }
    return sorted(sender_ids)


def _normalize_sender_id(value: Any) -> str | None:
    if value is None:
        return None
    normalized = (
        str(value)
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace(":", "")
        .upper()
    )
    if normalized.startswith("0X"):
        normalized = normalized[2:]
    return normalized or None


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
