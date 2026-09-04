"""Replay runtime session model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class ReplaySession:
    """Runtime-independent replay session description."""

    capture_file: str
    interval_seconds: float = 1.0
    limit: int | None = None
    source: str | None = None
    realtime: bool = False
    start: str | None = None
    end: str | None = None
    tx_enabled: bool = False
    state: str = "created"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    statistics: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_cli(
        cls,
        capture_file: str,
        interval_seconds: float,
        limit: int | None = None,
    ) -> ReplaySession:
        """Build a replay session from CLI arguments."""

        return cls(
            capture_file=capture_file,
            interval_seconds=interval_seconds,
            limit=limit,
            source=infer_replay_source(capture_file),
        )

    def mark_running(self) -> None:
        """Mark session as running."""

        self.state = "running"
        self.started_at = datetime.now().astimezone()

    def mark_finished(self) -> None:
        """Mark session as finished."""

        self.state = "finished"
        self.finished_at = datetime.now().astimezone()

    def mark_stopped(self) -> None:
        """Mark session as stopped by runtime command."""

        self.state = "stopped"
        self.finished_at = datetime.now().astimezone()

    def mark_failed(self) -> None:
        """Mark session as failed."""

        self.state = "failed"
        self.finished_at = datetime.now().astimezone()


def infer_replay_source(capture_file: str) -> str:
    """Infer replay source type from capture file suffix."""

    suffix = Path(capture_file).suffix.lower()

    if suffix == ".xml":
        return "dolphinview"

    if suffix == ".enolog":
        return "weinzierl"

    if suffix in {".sqlite", ".db"}:
        return "busmonitor"

    raise ValueError(f"Unsupported replay file type: {suffix}")
