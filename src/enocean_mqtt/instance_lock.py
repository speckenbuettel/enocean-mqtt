"""Operating-system-backed singleton protection for the gateway runtime."""

from __future__ import annotations

import fcntl
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO


class InstanceAlreadyRunningError(RuntimeError):
    """Raised when another gateway process owns the singleton lock."""


def default_lock_path() -> Path:
    """Return a stable, user-private lock path shared by all invocations."""

    runtime_directory = Path(f"/run/user/{os.getuid()}")
    if runtime_directory.is_dir() and os.access(runtime_directory, os.W_OK):
        return runtime_directory / "enocean-mqtt.lock"
    return Path.home() / ".cache" / "enocean-mqtt" / "runtime.lock"


def _owner_metadata() -> dict[str, object]:
    return {
        "pid": os.getpid(),
        "started_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "command": [sys.executable, *sys.argv],
    }


def _read_owner(lock_file: TextIO) -> str:
    lock_file.seek(0)
    content = lock_file.read().strip()
    if not content:
        return "owner details unavailable"
    try:
        owner = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(owner, dict):
        return content
    pid = owner.get("pid", "unknown")
    started_at = owner.get("started_at", "unknown")
    command = owner.get("command", [])
    command_text = " ".join(str(value) for value in command)
    return f"pid={pid}, started_at={started_at}, command={command_text}"


@contextmanager
def instance_lock(path: Path | None = None) -> Iterator[Path]:
    """Hold an exclusive non-blocking process lock for the runtime lifetime."""

    lock_path = path or default_lock_path()
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            owner = _read_owner(lock_file)
            raise InstanceAlreadyRunningError(
                f"another instance owns {lock_path} ({owner})"
            ) from exc

        try:
            lock_file.seek(0)
            lock_file.truncate()
            json.dump(_owner_metadata(), lock_file, separators=(",", ":"))
            lock_file.flush()
            yield lock_path
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
