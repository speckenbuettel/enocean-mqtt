"""Shared, durable sender classification and optional archive exclusions."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator


class ForeignDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_id: str
    exclude_from_sqlite: StrictBool = False

    @field_validator("sender_id")
    @classmethod
    def normalize_sender_id(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[0-9A-F]{8}", value):
            raise ValueError("sender_id must contain exactly eight hexadecimal digits")
        return value


class ForeignDeviceRegistry:
    """Cache reads by file signature; atomically replace the JSON on mutations.

    Readers in separate runtime/Web API processes observe changes without a
    restart. A missing file is an empty registry. Invalid files are never replaced
    implicitly by a mutation.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._signature: tuple[int, int, int] | None = None
        self._devices: dict[str, ForeignDevice] = {}

    def snapshot(self) -> dict[str, ForeignDevice]:
        with self._lock:
            source_path = self.path
            try:
                stat = source_path.stat()
            except FileNotFoundError:
                # Read older installations without discarding classifications or policies.
                source_path = self.path.with_name("external-devices.json")
                try:
                    stat = source_path.stat()
                except FileNotFoundError:
                    self._signature = None
                    self._devices = {}
                    return {}
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if signature != self._signature:
                payload = json.loads(source_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and "foreign_devices" not in payload:
                    payload = {"foreign_devices": payload.get("external_devices")}
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("foreign_devices"), list
                ):
                    raise ValueError("foreign_devices must be a list")
                devices = [
                    ForeignDevice.model_validate(item) for item in payload["foreign_devices"]
                ]
                if len({item.sender_id for item in devices}) != len(devices):
                    raise ValueError("duplicate foreign sender IDs")
                self._devices = {item.sender_id: item for item in devices}
                self._signature = signature
            return {key: value.model_copy() for key, value in self._devices.items()}

    def upsert(self, device: ForeignDevice) -> None:
        with self._lock:
            devices = self.snapshot()
            devices[device.sender_id] = device
            self._write(devices)

    def remove(self, sender_id: str) -> None:
        sender_id = ForeignDevice(sender_id=sender_id).sender_id
        with self._lock:
            devices = self.snapshot()
            devices.pop(sender_id, None)
            self._write(devices)

    def _write(self, devices: dict[str, ForeignDevice]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"foreign_devices": [devices[key].model_dump() for key in sorted(devices)]}
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary = handle.name
                handle.write(json.dumps(payload, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            replacement_path = handle.name
            # Windows indexers/virus scanners can briefly hold either file open.
            for attempt in range(10):
                try:
                    os.replace(replacement_path, self.path)
                    temporary = None
                    break
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) not in (5, 32) or attempt == 9:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        self._signature = None


@lru_cache(maxsize=16)
def foreign_registry(path: str | Path) -> ForeignDeviceRegistry:
    """Use one mutation lock/cache for each registry in this process."""
    return ForeignDeviceRegistry(path)
