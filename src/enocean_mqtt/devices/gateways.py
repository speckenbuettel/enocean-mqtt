"""External radio gateways, identified by a bounded sender-ID range."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GatewayRevisionConflict(ValueError):
    """A client attempted to replace a stale gateway configuration."""


def gateway_revision(gateway: ExternalGateway | None) -> str:
    if gateway is None:
        return ""
    return hashlib.sha256(gateway.model_dump_json().encode()).hexdigest()


class GatewayChannel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    offset: int = Field(ge=0, le=127, strict=True)
    name: str | None = None
    description: str | None = None
    profile: str | None = None

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str | None) -> str | None:
        if value is None or not value:
            return None
        value = value.upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]*", value):
            raise ValueError("Invalid profile identifier")
        return value


class ExternalGateway(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_id: str
    name: str = Field(min_length=1)
    manufacturer: str | None = None
    model: str | None = None
    description: str | None = None
    sender_count: int = Field(default=128, ge=1, le=128, strict=True)
    channels: list[GatewayChannel] = Field(default_factory=list)

    @field_validator("base_id")
    @classmethod
    def normalize_base_id(cls, value: str) -> str:
        value = value.upper()
        if not re.fullmatch(r"[0-9A-F]{8}", value):
            raise ValueError("base_id must contain eight hexadecimal digits")
        return value

    @model_validator(mode="after")
    def validate_channels(self) -> ExternalGateway:
        if int(self.base_id, 16) + self.sender_count - 1 > 0xFFFFFFFF:
            raise ValueError("Sender range exceeds the eight-digit sender ID space")
        offsets = [channel.offset for channel in self.channels]
        if len(set(offsets)) != len(offsets):
            raise ValueError("Duplicate channel offsets")
        if any(offset >= self.sender_count for offset in offsets):
            raise ValueError("Channel outside gateway sender range")
        return self

    def contains(self, sender_id: str) -> bool:
        if not re.fullmatch(r"[0-9A-Fa-f]{8}", sender_id):
            return False
        return 0 <= int(sender_id, 16) - int(self.base_id, 16) < self.sender_count

    def channel(self, sender_id: str) -> GatewayChannel | None:
        offset = int(sender_id, 16) - int(self.base_id, 16)
        return next((item for item in self.channels if item.offset == offset), None)

    def sender_summary(self, sender_id: str, legacy_profile: str | None = None) -> dict:
        channel = self.channel(sender_id)
        profile = channel.profile if channel else legacy_profile
        return {
            "device_id": sender_id, "sender_id": sender_id,
            "device_name": channel.name if channel and channel.name else self.name,
            "device_class": "gateway", "gateway_base_id": self.base_id,
            "gateway_name": self.name, "offset": int(sender_id, 16) - int(self.base_id, 16),
            "profile": profile, "configured": channel is not None,
            "assignment_status": "known" if channel and channel.profile else "unknown",
            "profile_source": "channel" if channel and channel.profile else
            "legacy_device" if profile else None,
        }


class GatewayRegistry:
    """Read changes across processes and atomically persist validated registries."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._signature: tuple[int, int, int] | None = None
        self._gateways: dict[str, ExternalGateway] = {}

    def snapshot(self) -> dict[str, ExternalGateway]:
        with self._lock:
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                self._signature = None
                self._gateways = {}
                return {}
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if signature != self._signature:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("gateways"), list):
                    raise ValueError("gateways must be a list")
                gateways = [ExternalGateway.model_validate(item) for item in payload["gateways"]]
                if len({item.base_id for item in gateways}) != len(gateways):
                    raise ValueError("Duplicate gateway base IDs")
                self._validate_ranges(gateways)
                self._gateways = {item.base_id: item for item in gateways}
                self._signature = signature
            return {key: item.model_copy(deep=True) for key, item in self._gateways.items()}

    def resolve(self, sender_id: str) -> ExternalGateway | None:
        return next((item for item in self.snapshot().values() if item.contains(sender_id)), None)

    def sender_ids(self) -> set[str]:
        return {
            f"{int(item.base_id, 16) + offset:08X}"
            for item in self.snapshot().values()
            for offset in range(item.sender_count)
        }

    def upsert(self, gateway: ExternalGateway, expected_revision: str | None = None) -> None:
        with self._lock, self._write_lock():
            items = self.snapshot()
            if expected_revision is not None and expected_revision != gateway_revision(
                items.get(gateway.base_id)
            ):
                raise GatewayRevisionConflict("Gateway changed; reload it before saving")
            items[gateway.base_id] = gateway
            self._validate_ranges(list(items.values()))
            self._write(items)

    @staticmethod
    def _validate_ranges(gateways: list[ExternalGateway]) -> None:
        ordered = sorted(gateways, key=lambda item: int(item.base_id, 16))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if int(previous.base_id, 16) + previous.sender_count > int(current.base_id, 16):
                raise ValueError(
                    f"Sender ranges overlap: {previous.base_id} and {current.base_id}"
                )

    def remove(self, base_id: str) -> None:
        base_id = ExternalGateway.normalize_base_id(base_id.strip())
        with self._lock, self._write_lock():
            items = self.snapshot()
            items.pop(base_id, None)
            self._write(items)

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        """Serialize file read/modify/write across runtime and API processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + ".lock").open("a+b") as handle:
            if os.name == "nt":
                import importlib
                msvcrt = importlib.import_module("msvcrt")
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import importlib
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write(self, items: dict[str, ExternalGateway]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"gateways": [items[key].model_dump() for key in sorted(items)]},
                          handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._signature = None


@lru_cache(maxsize=16)
def _cached_gateway_registry(path: Path) -> GatewayRegistry:
    return GatewayRegistry(path)


def gateway_registry(path: str | Path) -> GatewayRegistry:
    return _cached_gateway_registry(Path(path).resolve())
