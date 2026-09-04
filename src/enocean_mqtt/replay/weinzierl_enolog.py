"""Reader for Weinzierl .enolog capture files."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from enocean_mqtt.replay.models import ReplayTelegram


class WeinzierlEnologReader:
    """Read telegrams from Weinzierl .enolog SQLite capture files."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def open(self) -> sqlite3.Connection:
        """Open SQLite capture database."""

        return sqlite3.connect(self.path)

    def get_telegram_count(self) -> int:
        """Return total telegram count."""

        with self.open() as connection:
            cursor = connection.execute(
                "SELECT COUNT(*) FROM telegram_log"
            )

            row = cursor.fetchone()

        return int(row[0]) if row else 0

    def iter_telegrams(
        self,
        limit: int | None = None,
    ) -> Iterator[ReplayTelegram]:
        """Iterate normalized replay telegrams."""

        query = """
        SELECT
            tl.id,
            tp.attr,
            tp.val
        FROM telegram_log tl
        LEFT JOIN telegram_prop tp
            ON tp.telegram_id = tl.id
        ORDER BY tl.id ASC
        """

        telegrams_returned = 0
        current_telegram_id: int | None = None
        current_properties: dict[str, str] = {}

        with self.open() as connection:
            connection.row_factory = sqlite3.Row

            cursor = connection.execute(query)

            for row in cursor:
                telegram_id = int(row[0])
                attr = row[1]
                value = row[2]

                if current_telegram_id is None:
                    current_telegram_id = telegram_id

                if telegram_id != current_telegram_id:
                    telegram = self._build_telegram(
                        current_telegram_id,
                        current_properties,
                    )

                    if telegram.is_enocean_telegram:
                        yield telegram
                        telegrams_returned += 1

                        if (
                            limit is not None
                            and telegrams_returned >= limit
                        ):
                            return

                    current_telegram_id = telegram_id
                    current_properties = {}

                if attr and value:
                    current_properties[attr] = value

            if current_telegram_id is not None:
                telegram = self._build_telegram(
                    current_telegram_id,
                    current_properties,
                )

                if telegram.is_enocean_telegram:
                    yield telegram

    def _build_telegram(
        self,
        telegram_id: int,
        properties: dict[str, str],
    ) -> ReplayTelegram:
        """Build normalized replay telegram."""

        eno_id = _normalize_sender_id(properties.get("eno.id"))
        eno_rorg = _normalize_rorg(properties.get("eno.eep.rorg"))

        gateway_direction = str(
            properties.get("eno.gateway_direction", "")
        ).strip()

        if gateway_direction in {"1", "rx", "RX"}:
            direction = "rx"
        elif gateway_direction in {"2", "tx", "TX"}:
            direction = "tx"
        else:
            direction = "unknown"

        return ReplayTelegram(
            telegram_id=telegram_id,
            timestamp=properties.get("frame.timestamp"),
            protocol=properties.get("frame.protocol"),
            telegram_type=properties.get("eno.telegram_type"),
            direction=direction,
            eno_id=eno_id,
            eno_rorg=eno_rorg,
            eno_data=properties.get("eno.data"),
            eno_rssi=properties.get("eno.rssi"),
            raw_frame_data=properties.get("frame.data"),
            raw_apdu_data=properties.get("apdu.data"),
            properties=properties.copy(),
        )



def _normalize_sender_id(value: str | None) -> str | None:
    """Normalize Weinzierl sender ID values to 8-digit hex."""

    if value is None or value == "":
        return None

    try:
        return f"{int(value):08X}"
    except ValueError:
        return value.strip().upper()



def _normalize_rorg(value: str | None) -> str | None:
    """Normalize Weinzierl RORG values to hexadecimal notation."""

    if value is None or value == "":
        return None

    normalized = value.strip().upper()

    if len(normalized) == 2:
        return normalized

    try:
        return f"{int(normalized):02X}"
    except ValueError:
        return normalized
