"""Read-only access to retained RX screening evidence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def read_telegram_diagnostics(
    database: Path, limit: int = 100, classification: str | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    empty: dict[str, Any] = {"diagnostics": [], "retained_total": 0, "counts": {}}
    if not database.exists():
        return empty
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='telegram_diagnostics'"
        ).fetchone():
            return empty
        counts = dict(conn.execute(
            "SELECT classification,count(*) FROM telegram_diagnostics GROUP BY classification"
        ).fetchall())
        where = " WHERE classification=?" if classification else ""
        args: tuple[Any, ...] = (classification, limit) if classification else (limit,)
        rows = conn.execute(
            "SELECT diagnostic_id,event_json,assessment_json FROM telegram_diagnostics"
            + where + " ORDER BY diagnostic_id DESC LIMIT ?", args,
        ).fetchall()
        return {
            "diagnostics": [
                {"diagnostic_id": row[0], "event": json.loads(row[1]),
                 "quality": json.loads(row[2])} for row in rows
            ],
            "retained_total": sum(counts.values()), "counts": counts,
        }
