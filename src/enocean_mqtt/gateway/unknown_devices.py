"""Runtime registry for unknown EnOcean devices."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

UNKNOWN_DEVICE_CSV_FIELDS = [
    "sender_id",
    "rorg",
    "telegrams",
    "first_seen",
    "last_seen",
    "last_rssi_dbm",
    "last_data",
]


@dataclass(slots=True)
class UnknownDeviceRecord:
    """Runtime information for one unknown sender ID."""

    sender_id: str
    rorg: str | None = None
    telegrams: int = 0
    first_seen: float | None = None
    last_seen: float | None = None
    last_rssi_dbm: int | None = None
    last_data: str | None = None

    def update(
        self,
        *,
        timestamp: float | None,
        rorg: str | None,
        dbm: int | None,
        data: str | None,
    ) -> None:
        """Update runtime statistics from a telegram."""

        self.telegrams += 1

        if self.first_seen is None:
            self.first_seen = timestamp

        self.last_seen = timestamp
        self.rorg = rorg or self.rorg
        self.last_rssi_dbm = dbm
        self.last_data = data

    def to_payload(self) -> dict[str, Any]:
        """Return MQTT payload representation."""

        return {
            "sender_id": self.sender_id,
            "rorg": self.rorg,
            "telegrams": self.telegrams,
            "first_seen": _timestamp_to_iso(self.first_seen),
            "last_seen": _timestamp_to_iso(self.last_seen),
            "last_rssi_dbm": self.last_rssi_dbm,
            "last_data": self.last_data,
        }

    def to_csv_row(self) -> dict[str, str | int | float | None]:
        """Return CSV row representation."""

        return {
            "sender_id": self.sender_id,
            "rorg": self.rorg,
            "telegrams": self.telegrams,
            "first_seen": _timestamp_to_iso(self.first_seen),
            "last_seen": _timestamp_to_iso(self.last_seen),
            "last_rssi_dbm": self.last_rssi_dbm,
            "last_data": self.last_data,
        }


class UnknownDeviceRegistry:
    """In-memory registry for unknown sender IDs."""

    def __init__(self) -> None:
        self._records: dict[str, UnknownDeviceRecord] = {}

    def observe(
        self,
        *,
        sender_id: str,
        timestamp: float | None,
        rorg: str | None,
        dbm: int | None,
        data: str | None,
    ) -> UnknownDeviceRecord:
        """Record one telegram from an unknown device."""

        normalized_sender_id = sender_id.strip().upper()

        record = self._records.get(normalized_sender_id)

        if record is None:
            record = UnknownDeviceRecord(sender_id=normalized_sender_id)
            self._records[normalized_sender_id] = record

        record.update(
            timestamp=timestamp,
            rorg=rorg,
            dbm=dbm,
            data=data,
        )

        return record

    def remove(self, sender_id: str) -> bool:
        """Remove sender ID from unknown device registry."""

        normalized_sender_id = sender_id.strip().upper()

        return (
            self._records.pop(normalized_sender_id, None)
            is not None
        )

    def count_devices(self) -> int:
        """Return number of unknown sender IDs."""

        return len(self._records)

    def count_telegrams(self) -> int:
        """Return number of telegrams from unknown sender IDs."""

        return sum(record.telegrams for record in self._records.values())

    def records(self) -> list[UnknownDeviceRecord]:
        """Return sorted unknown device records."""

        return [
            self._records[sender_id]
            for sender_id in sorted(self._records)
        ]

    def export_csv(self, path: str | Path) -> None:
        """Export unknown device records to CSV."""

        csv_path = Path(path)

        if not csv_path.parent.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)

        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=UNKNOWN_DEVICE_CSV_FIELDS,
            )

            writer.writeheader()

            for record in self.records():
                writer.writerow(record.to_csv_row())


def _timestamp_to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None

    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="milliseconds")
