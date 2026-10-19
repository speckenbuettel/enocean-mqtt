"""Passive gateway channel projections from retained RX or process-local RX."""

from __future__ import annotations

import sqlite3
import time
from collections import Counter, deque
from pathlib import Path
from threading import RLock
from typing import Any

from enocean_mqtt.devices.gateway_decode import decode_gateway_payload
from enocean_mqtt.devices.gateways import ExternalGateway, GatewayRegistry, gateway_revision
from enocean_mqtt.runtime.event import RuntimeTelegramEvent

OUTCOME_COUNTERS = {
    "decoded": "decoded_commands_total", "no_profile": "unassigned_telegrams_total",
    "invalid_profile": "decode_errors_total", "malformed_payload": "decode_errors_total",
    "unsupported_variant": "unsupported_telegrams_total", "teach_in": "teach_in_telegrams_total",
    "not_applicable": "other_telegrams_total",
}
_lock = RLock()
_started_at = time.time()
_live: dict[str, dict[str, dict[str, Any]]] = {}


def _hex(value: Any) -> str | None:
    if value is None:
        return None
    return value.hex().upper() if isinstance(value, bytes) else str(value).replace(" ", "").upper()


def _record(
    rows: dict[str, dict[str, Any]], event: dict[str, Any], profile: str | None,
    cache: dict[tuple, tuple],
) -> None:
    sender = _hex(event.get("sender_id"))
    if not sender:
        return
    payload, rorg, status = (_hex(event.get(key)) for key in ("data", "rorg", "erp1_status"))
    key = (profile, payload, rorg, status)
    if key not in cache:
        cache[key] = decode_gateway_payload(profile, payload, rorg, status)
    outcome, _, error = cache[key]
    item = rows.setdefault(sender, {
        "sender_id": sender, "first_seen": None, "last_seen": None,
        "last_rssi_dbm": None, "last_data": None, "last_raw_telegram": None,
        "metrics": Counter(), "decode_status": None, "decode_error": None,
        "_event_times": deque(maxlen=10000),
    })
    metrics = item["metrics"]
    metrics["rx_telegrams_total"] += 1
    metrics[OUTCOME_COUNTERS[outcome]] += 1
    repeater = event.get("repeater_count")
    category = ("original" if repeater in (0, 15) else
                "repeated" if repeater in (1, 2) else "unclassified")
    metrics[f"{category}_telegrams_total"] += 1
    timestamp = event.get("timestamp_unix")
    if timestamp is not None:
        item["_event_times"].append(timestamp)
        item["first_seen"] = (min(item["first_seen"], timestamp)
                              if item["first_seen"] is not None else timestamp)
    if item["last_seen"] is None or (timestamp is not None and timestamp >= item["last_seen"]):
        item.update({
            "last_seen": timestamp, "last_rssi_dbm": event.get("rssi_dbm"),
            "last_data": payload, "last_raw_telegram": _hex(event.get("raw_telegram")),
            "rorg": rorg, "decode_status": outcome, "decode_error": error,
        })


def record_gateway_rx(
    registry: GatewayRegistry, event: RuntimeTelegramEvent, legacy_profile: str | None = None,
) -> None:
    if (event.direction != "rx" or getattr(event, "runtime_mode", "live") == "replay"
            or not event.sender_id):
        return
    gateway = registry.resolve(event.sender_id)
    if gateway is None:
        return
    profile = gateway.sender_summary(event.sender_id, legacy_profile)["profile"]
    values = {key: getattr(event, key, None) for key in (
        "sender_id", "data", "rorg", "erp1_status", "timestamp_unix", "rssi_dbm",
        "raw_telegram", "repeater_count",
    )}
    with _lock:
        rows = _live.setdefault(str(registry.path.resolve()), {})
        _record(rows, values, profile, {})


def gateway_projection(
    gateway: ExternalGateway, registry: GatewayRegistry, database: Path,
    legacy_profiles: dict[str, str | None], active_window_seconds: int,
    rate_window_seconds: int = 3600, peak_window_seconds: int = 900,
) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    source = "process_local"
    issues: list[str] = []
    if database.exists():
        try:
            with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
                connection.row_factory = sqlite3.Row
                columns = {row[1] for row in connection.execute("PRAGMA table_info(telegrams)")}
                if not {"sender_id", "direction", "timestamp_unix", "data", "rorg",
                        "runtime_mode"} <= columns:
                    raise ValueError(
                        "Stored channel history lacks required provenance; using process-local RX."
                    )
                desired = ("sender_id", "timestamp_unix", "data", "rorg", "erp1_status",
                           "raw_telegram", "rssi_dbm", "repeater_count")
                select = ", ".join(
                    name if name in columns else f"NULL AS {name}" for name in desired
                )
                query = f"SELECT {select} FROM telegrams WHERE direction = 'rx' "
                query += "AND UPPER(sender_id) BETWEEN ? AND ? "
                if "runtime_mode" in columns:
                    query += "AND COALESCE(runtime_mode, 'live') != 'replay' "
                query += "ORDER BY timestamp_unix ASC"
                cache: dict[tuple, tuple] = {}
                for raw in connection.execute(query, (
                    gateway.base_id, f"{int(gateway.base_id, 16) + gateway.sender_count - 1:08X}",
                )):
                    event = dict(raw)
                    sender = _hex(event["sender_id"]) or ""
                    profile = gateway.sender_summary(sender, legacy_profiles.get(sender))["profile"]
                    _record(rows, event, profile, cache)
            source = "sqlite_retained"
        except (sqlite3.Error, ValueError) as exc:
            issues.append(str(exc))
    if source == "process_local":
        with _lock:
            from copy import deepcopy
            rows = {
                sender: deepcopy(item)
                for sender, item in _live.get(str(registry.path.resolve()), {}).items()
                if gateway.contains(sender)
            }
    now = time.time()
    rate_window_seconds = max(1, rate_window_seconds)
    peak_window_seconds = max(1, peak_window_seconds)

    def rates(timestamps: list[float], total: int) -> dict[str, Any]:
        ordered = sorted(timestamps)
        left = 0
        peak = 0
        for right, timestamp in enumerate(ordered):
            while timestamp - ordered[left] >= peak_window_seconds:
                left += 1
            peak = max(peak, right - left + 1)
        return {
            "telegrams_per_minute": round(
                sum(now - rate_window_seconds <= stamp <= now for stamp in ordered)
                * 60 / rate_window_seconds, 4,
            ),
            "peak_telegrams_per_minute": round(peak * 60 / peak_window_seconds, 4),
            "rate_samples_complete": len(ordered) == total,
        }

    channel_rows = []
    all_times: list[float] = []
    for sender in sorted(set(rows) | {
        f"{int(gateway.base_id, 16) + channel.offset:08X}" for channel in gateway.channels
    }):
        channel = gateway.channel(sender)
        observation = rows.get(sender, {})
        counts = observation.get("metrics", {})
        event_times = list(observation.get("_event_times", []))
        all_times.extend(event_times)
        metrics = {name: counts.get(name, 0) for name in {
            "rx_telegrams_total", *OUTCOME_COUNTERS.values(), "original_telegrams_total",
            "repeated_telegrams_total", "unclassified_telegrams_total",
        }}
        channel_rows.append({
            **gateway.sender_summary(sender, legacy_profiles.get(sender)),
            **{key: value for key, value in observation.items() if not key.startswith("_")},
            "name": channel.name if channel else None,
            "description": channel.description if channel else None,
            "observed": bool(observation), "metrics": metrics,
            "rates": rates(event_times, metrics["rx_telegrams_total"]),
            "telegrams": metrics["rx_telegrams_total"],
            "active": (now - observation["last_seen"] <= active_window_seconds
                       if observation.get("last_seen") is not None else None),
            "last_telegram": {"data": observation.get("last_data"),
                             "raw_telegram": observation.get("last_raw_telegram")},
        })
    totals = {name: sum(item["metrics"][name] for item in channel_rows)
              for name in {"rx_telegrams_total", *OUTCOME_COUNTERS.values(),
                           "original_telegrams_total", "repeated_telegrams_total",
                           "unclassified_telegrams_total"}}
    totals.update({
        "configured_channels_total": len(gateway.channels),
        "known_channels_total": sum(bool(channel.profile) for channel in gateway.channels),
        "observed_channels_total": len(rows), "sender_capacity": gateway.sender_count,
        "unknown_channels_total": sum(
            item["assignment_status"] == "unknown" for item in channel_rows
        ),
        "active_channels_total": sum(item["active"] is True for item in channel_rows),
    })
    first = [item["first_seen"] for item in rows.values() if item["first_seen"] is not None]
    last = [item["last_seen"] for item in rows.values() if item["last_seen"] is not None]
    return {
        **gateway.model_dump(), "revision": gateway_revision(gateway),
        "observed_channels": channel_rows, "metrics": totals,
        "rates": rates(all_times, totals["rx_telegrams_total"]),
        "observation": {
            "source": source, "runtime_mode": "live", "to": now,
            "from": min(first) if first else None, "last_seen": max(last) if last else None,
            "started_at": _started_at if source == "process_local" else None,
            "classification_basis": ("current_registry" if source == "sqlite_retained"
                                     else "at_observation"),
            "coverage": ("retention_and_storage_bounded" if source == "sqlite_retained"
                         else "process_local_only"),
            "active_window_seconds": active_window_seconds,
            "rate_window_seconds": rate_window_seconds, "peak_window_seconds": peak_window_seconds,
            "rate_sample_limit_per_channel": 10000,
        }, "issues": issues,
    }
