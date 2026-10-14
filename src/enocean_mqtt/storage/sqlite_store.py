"""SQLite runtime persistence layer.

SQLite acts as the lightweight historical telegram archive for:
- live busmonitor history
- protocol inspection
- Web API queries
- replay persistence testing
- future OBS integration

The storage layer intentionally operates on RuntimeTelegramEvent.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import RLock

from enocean_mqtt.devices.foreign_registry import foreign_registry
from enocean_mqtt.runtime.event import RuntimeTelegramEvent

SCHEMA_VERSION = 2


class SQLiteRuntimeStore:
    """SQLite persistence backend for runtime telegram events."""

    def __init__(
        self,
        database_path: str,
        max_telegrams: int = 0,
        persist_live: bool = True,
        persist_replay: bool = False,
        foreign_devices_file: str | Path | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.max_telegrams = max_telegrams
        self.persist_live = persist_live
        self.persist_replay = persist_replay
        self._lock = RLock()
        self._foreign_registry = (
            foreign_registry(foreign_devices_file) if foreign_devices_file is not None else None
        )
        self._foreign_registry_error = False

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )

        self.connection.row_factory = sqlite3.Row

        self._initialize_pragmas()
        self._initialize_schema()

    def _initialize_pragmas(self) -> None:
        """Initialize SQLite runtime pragmas."""

        cursor = self.connection.cursor()

        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")

        self.connection.commit()

    def _initialize_schema(self) -> None:
        """Initialize SQLite schema."""

        cursor = self.connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
                schema_version INTEGER NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telegrams (
                telegram_id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp_unix REAL NOT NULL,

                direction TEXT NOT NULL
                    CHECK (direction IN ('rx', 'tx')),

                runtime_mode TEXT NOT NULL
                    CHECK (runtime_mode IN ('live', 'replay')),

                raw_telegram BLOB NOT NULL,

                rorg TEXT,
                sender_id TEXT,
                destination_id TEXT,
                data BLOB,
                erp1_status TEXT,

                repeater_count INTEGER,
                repeater_permitted INTEGER,
                hash_type TEXT,
                contains_teach_in INTEGER,

                subtelegram_count INTEGER,
                rssi_dbm INTEGER,
                port TEXT,

                interface_id TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telegrams_timestamp
            ON telegrams(timestamp_unix)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telegrams_direction_timestamp
            ON telegrams(direction, timestamp_unix)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telegrams_sender_timestamp
            ON telegrams(sender_id, timestamp_unix)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telegrams_rorg_timestamp
            ON telegrams(rorg, timestamp_unix)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telegrams_runtime_mode_timestamp
            ON telegrams(runtime_mode, timestamp_unix)
            """
        )

        cursor.execute("DELETE FROM schema_info")

        cursor.execute(
            "INSERT INTO schema_info(schema_version) VALUES (?)",
            (SCHEMA_VERSION,),
        )

        self.connection.commit()

    @staticmethod
    def _normalize_hex(value: str | None) -> str | None:
        """Normalize hexadecimal string representation."""

        if value is None:
            return None

        normalized = value.replace(" ", "").upper()

        if normalized.startswith("0X"):
            normalized = normalized[2:]

        return normalized

    @classmethod
    def _hex_to_blob(cls, value: str | None) -> bytes | None:
        """Convert hexadecimal string to SQLite BLOB bytes."""

        normalized = cls._normalize_hex(value)

        if normalized is None:
            return None

        return bytes.fromhex(normalized)

    def _should_persist(
        self,
        event: RuntimeTelegramEvent,
    ) -> bool:
        """Return whether event should be persisted."""

        if self._foreign_registry is not None:
            try:
                device = self._foreign_registry.snapshot().get(
                    (event.sender_id or "").strip().upper()
                )
                self._foreign_registry_error = False
                if device is not None and device.exclude_from_sqlite:
                    return False
            except (OSError, ValueError):
                if not self._foreign_registry_error:
                    logging.getLogger(__name__).warning(
                        "Foreign-device registry unavailable; retaining telegrams in SQLite"
                    )
                self._foreign_registry_error = True

        if event.runtime_mode == "live":
            return self.persist_live

        if event.runtime_mode == "replay":
            return self.persist_replay

        return False

    def _apply_retention_cleanup(self) -> None:
        """Apply deterministic bounded telegram retention cleanup."""

        if self.max_telegrams <= 0:
            return

        cleanup_batch = max(
            100,
            int(self.max_telegrams * 0.01),
        )

        cleanup_threshold = (
            self.max_telegrams + cleanup_batch
        )

        cursor = self.connection.cursor()

        cursor.execute(
            "SELECT COUNT(*) AS telegram_count FROM telegrams"
        )

        row = cursor.fetchone()

        if row is None:
            return

        telegram_count = int(row["telegram_count"])

        if telegram_count <= cleanup_threshold:
            return

        delete_count = telegram_count - self.max_telegrams

        cursor.execute(
            """
            DELETE FROM telegrams
            WHERE telegram_id IN (
                SELECT telegram_id
                FROM telegrams
                ORDER BY telegram_id ASC
                LIMIT ?
            )
            """,
            (delete_count,),
        )

        self.connection.commit()

    def persist_event(
        self,
        event: RuntimeTelegramEvent,
    ) -> None:
        """Persist one runtime telegram event."""

        if not self._should_persist(event):
            return

        # RX and TX callbacks run on different threads.  A sqlite3 connection
        # may be shared with check_same_thread=False, but its transactions may
        # not be used concurrently.  Keep insert, commit and retention cleanup
        # in one critical section so one writer cannot commit another writer's
        # transaction.
        with self._lock:
            try:
                cursor = self.connection.cursor()

                cursor.execute(
                    """
                    INSERT INTO telegrams (
                        timestamp_unix,
                        direction,
                        runtime_mode,
                        raw_telegram,
                        rorg,
                        sender_id,
                        destination_id,
                        data,
                        erp1_status,
                        repeater_count,
                        repeater_permitted,
                        hash_type,
                        contains_teach_in,
                        subtelegram_count,
                        rssi_dbm,
                        port,
                        interface_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.timestamp_unix,
                        event.direction,
                        event.runtime_mode,
                        self._hex_to_blob(event.raw_telegram),
                        self._normalize_hex(event.rorg),
                        self._normalize_hex(event.sender_id),
                        self._normalize_hex(event.destination_id),
                        self._hex_to_blob(event.data),
                        self._normalize_hex(event.erp1_status),
                        event.repeater_count,
                        int(event.repeater_permitted)
                        if event.repeater_permitted is not None
                        else None,
                        event.hash_type,
                        int(event.contains_teach_in)
                        if event.contains_teach_in is not None
                        else None,
                        event.subtelegram_count,
                        event.rssi_dbm,
                        event.port,
                        event.interface_id,
                    ),
                )

                self.connection.commit()
                self._apply_retention_cleanup()
            except sqlite3.Error:
                self.connection.rollback()
                raise

    def close(self) -> None:
        """Close SQLite connection."""

        with self._lock:
            self.connection.close()
