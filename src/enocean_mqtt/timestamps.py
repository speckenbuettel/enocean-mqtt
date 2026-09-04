"""Timestamp helper functions."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""

    return datetime.now(UTC)



def unix_timestamp() -> float:
    """Return current UNIX timestamp."""

    return utc_now().timestamp()
