"""Project version loading."""

from __future__ import annotations

from pathlib import Path


def load_project_version(version_file: str | Path = "VERSION") -> str:
    """Read the project version from VERSION, falling back to ``unknown``."""
    path = Path(version_file)
    if not path.is_file():
        return "unknown"

    version = path.read_text(encoding="utf-8").strip()
    return version or "unknown"
