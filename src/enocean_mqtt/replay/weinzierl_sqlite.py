"""Weinzierl ENOLOG SQLite replay adapter."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from enocean_mqtt.replay.models import ReplayTelegram

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
HEX_BYTE_PATTERN = re.compile(r"\b[0-9A-Fa-f]{2}\b")
DEFAULT_ERP1_STATUS = "00"
DEFAULT_DESTINATION_ID = "FFFFFFFF"


@dataclass(slots=True)
class WeinzierlRecord:
    """Normalized data extracted from one Weinzierl log row."""

    telegram_id: int
    timestamp: str | None
    direction: str | None
    source_address: str | None
    destination_address: str | None
    service: str | None
    rorg: str | None
    payload_hex: str | None
    sender_id: str | None
    raw_erp1_hex: str | None
    raw_frame_hex: str | None
    al_data: str | None
    status: str


class WeinzierlSQLiteReplay:
    """Replay telegrams from Weinzierl ``.enolog`` SQLite databases."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def iter_telegrams(
        self,
        limit: int | None = None,
    ) -> Iterator[ReplayTelegram]:
        """Yield normalized replay telegrams from ``telegram_log``."""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row

        try:
            query = (
                "SELECT id, number, protocol, service, source_address, "
                "destination_address, al_data, direction, telegram_string, "
                "timestamp "
                "FROM telegram_log "
                "ORDER BY id ASC"
            )

            if limit is not None:
                query += f" LIMIT {int(limit)}"

            rows = connection.execute(query)

            for row in rows:
                record = _row_to_record(row)

                if record is None:
                    continue

                yield ReplayTelegram(
                    telegram_id=record.telegram_id,
                    timestamp=record.timestamp,
                    protocol="weinzierl-knx-enocean",
                    telegram_type="0",
                    direction=record.direction,
                    eno_id=record.sender_id,
                    eno_rorg=record.rorg,
                    eno_data=record.payload_hex,
                    eno_rssi=None,
                    raw_frame_data=record.raw_frame_hex,
                    raw_apdu_data=record.raw_erp1_hex,
                    properties={
                        "source_address": record.source_address or "",
                        "destination_address": record.destination_address or "",
                        "service": record.service or "",
                        "al_data": record.al_data or "",
                    },
                    source="weinzierl_sqlite",
                    destination_id=DEFAULT_DESTINATION_ID,
                    status=record.status,
                    subtelegram_count=None,
                )

        finally:
            connection.close()


def _row_to_record(row: sqlite3.Row) -> WeinzierlRecord | None:
    """Convert one Weinzierl row into a replay record."""

    telegram_string = row["telegram_string"]

    if not telegram_string:
        return None

    bytes_hex = _extract_hex_bytes(telegram_string)

    if len(bytes_hex) < 10:
        return None

    # Preserve the previously working parser semantics:
    # <payload:4><rorg:1><unknown:1><sender:4>
    # Example:
    # 29 00 ... 96 00 00 0A A5 46 05 13 9B 47
    payload_bytes = bytes_hex[-10:-6]
    rorg = bytes_hex[-6].upper()
    sender_bytes = bytes_hex[-4:]

    sender_id = "".join(sender_bytes).upper()
    payload_hex = "".join(payload_bytes).upper()

    raw_erp1_hex = _build_normalized_erp1_telegram(
        rorg=rorg,
        payload_bytes=payload_bytes,
        sender_bytes=sender_bytes,
        status=DEFAULT_ERP1_STATUS,
    )

    return WeinzierlRecord(
        telegram_id=int(row["id"]),
        timestamp=_convert_weinzierl_timestamp(row["timestamp"]),
        direction=_normalize_direction(row["direction"]),
        source_address=row["source_address"],
        destination_address=row["destination_address"],
        service=row["service"],
        rorg=rorg,
        payload_hex=payload_hex,
        sender_id=sender_id,
        raw_erp1_hex=raw_erp1_hex,
        raw_frame_hex=telegram_string,
        al_data=row["al_data"],
        status=DEFAULT_ERP1_STATUS,
    )


def _build_normalized_erp1_telegram(
    rorg: str,
    payload_bytes: list[str],
    sender_bytes: list[str],
    status: str,
) -> str:
    telegram_bytes = [
        rorg,
        *payload_bytes,
        *sender_bytes,
        status,
    ]

    return " ".join(byte.upper() for byte in telegram_bytes)


def _extract_hex_bytes(value: str | None) -> list[str]:
    if not value:
        return []

    return HEX_BYTE_PATTERN.findall(value)


def _convert_weinzierl_timestamp(value: int | str | None) -> str | None:
    if value is None or value == "":
        return None

    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return None

    timestamp = FILETIME_EPOCH + timedelta(microseconds=ticks / 10)

    return timestamp.isoformat()


def _normalize_direction(value: str | None) -> str | None:
    if value is None:
        return None

    direction = value.strip().lower()

    if direction == "rx":
        return "rx"

    if direction == "tx":
        return "tx"

    return direction or None
