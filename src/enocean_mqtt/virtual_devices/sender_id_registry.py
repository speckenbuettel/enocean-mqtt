"""Persistent sender ID allocation registry for gateway-managed senders."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SENDER_ID_PATTERN = re.compile(r"^[A-F0-9]{8}$")
MANUFACTURER_ID_PATTERN = re.compile(r"^[A-F0-9]{3}$")
DEVICE_TYPE_VIRTUAL_DEVICE = "virtual_device"
DEVICE_TYPE_EMULATED_SENDER = "emulated_sender"
DEFAULT_INTERFACE_ID = "usb300_01"
DEFAULT_MANUFACTURER_ID = "760"


class SenderIdRegistryError(ValueError):
    """Raised when sender ID registry handling fails."""


class SenderIdAllocation(BaseModel):
    """One allocated synthetic sender ID."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sender_id: str
    device_type: str
    device_reference: str | None = None
    destination_id: str | None = None

    @field_validator("sender_id")
    @classmethod
    def validate_sender_id(cls, value: str) -> str:
        normalized = _normalize_hex(value, width=8)

        if not SENDER_ID_PATTERN.match(normalized):
            raise ValueError("sender_id must be 8 uppercase hexadecimal characters")

        return normalized

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, value: str) -> str:
        normalized = value.strip()

        if normalized not in {DEVICE_TYPE_VIRTUAL_DEVICE, DEVICE_TYPE_EMULATED_SENDER}:
            raise ValueError(
                "device_type must be virtual_device or emulated_sender"
            )

        return normalized

    @field_validator("destination_id")
    @classmethod
    def validate_destination_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = _normalize_hex(value, width=8)

        if not SENDER_ID_PATTERN.match(normalized):
            raise ValueError(
                "destination_id must be 8 uppercase hexadecimal characters"
            )

        return normalized

    @model_validator(mode="after")
    def validate_reference(self) -> SenderIdAllocation:
        if self.device_type == DEVICE_TYPE_VIRTUAL_DEVICE and not self.device_reference:
            raise ValueError("virtual_device allocations require device_reference")

        if self.device_type == DEVICE_TYPE_EMULATED_SENDER and not self.destination_id:
            raise ValueError("emulated_sender allocations require destination_id")

        return self


class SenderIdInterface(BaseModel):
    """Sender ID allocation pool owned by one EnOcean TX interface."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    interface_id: str
    base_id: str
    allocated_sender_ids: list[SenderIdAllocation] = Field(default_factory=list)

    @field_validator("base_id")
    @classmethod
    def validate_base_id(cls, value: str) -> str:
        normalized = _normalize_hex(value, width=8)

        if not SENDER_ID_PATTERN.match(normalized):
            raise ValueError("base_id must be 8 uppercase hexadecimal characters")

        if int(normalized, 16) & 0x7F:
            raise ValueError("base_id must be aligned to a 128-ID pool")

        return normalized


class SenderIdRegistryFile(BaseModel):
    """Root sender ID registry file."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    manufacturer_id: str = DEFAULT_MANUFACTURER_ID
    interfaces: list[SenderIdInterface] = Field(default_factory=list)

    @field_validator("manufacturer_id")
    @classmethod
    def validate_manufacturer_id(cls, value: str) -> str:
        normalized = _normalize_hex(value, width=3)

        if not MANUFACTURER_ID_PATTERN.match(normalized):
            raise ValueError(
                "manufacturer_id must be 3 uppercase hexadecimal characters"
            )

        if int(normalized, 16) > 0x7FF:
            raise ValueError("manufacturer_id must be inside the 11-bit range")

        return normalized

    @model_validator(mode="after")
    def validate_unique_values(self) -> SenderIdRegistryFile:
        interface_ids: set[str] = set()
        sender_ids: set[str] = set()

        for interface in self.interfaces:
            if interface.interface_id in interface_ids:
                raise ValueError(
                    f"Duplicate sender registry interface_id: {interface.interface_id}"
                )

            interface_ids.add(interface.interface_id)
            base = int(interface.base_id, 16)
            max_sender = base + 127

            for allocation in interface.allocated_sender_ids:
                sender_int = int(allocation.sender_id, 16)

                if sender_int <= base or sender_int > max_sender:
                    raise ValueError(
                        f"sender_id {allocation.sender_id} is outside the "
                        f"pool for interface {interface.interface_id}"
                    )

                if allocation.sender_id in sender_ids:
                    raise ValueError(
                        f"Duplicate allocated sender_id: {allocation.sender_id}"
                    )

                sender_ids.add(allocation.sender_id)

        return self


class SenderIdRegistry:
    """Persistent sender ID allocation registry."""

    def __init__(self, path: str | Path, *, default_base_id: str | None = None) -> None:
        self.path = Path(path)
        self.default_base_id = (
            _normalize_hex(default_base_id, width=8) if default_base_id else None
        )
        self.file = self._load()

    @property
    def manufacturer_id(self) -> str:
        """Return configured global manufacturer ID."""

        return self.file.manufacturer_id

    def allocate_virtual_device(
        self,
        *,
        virtual_device_id: str,
        interface_id: str = DEFAULT_INTERFACE_ID,
        base_id: str | None = None,
    ) -> str:
        """Allocate or return a stable sender ID for one virtual device."""

        interface = self._get_or_create_interface(
            interface_id=interface_id,
            base_id=base_id,
        )
        normalized_reference = virtual_device_id.strip().lower()

        for allocation in interface.allocated_sender_ids:
            if (
                allocation.device_type == DEVICE_TYPE_VIRTUAL_DEVICE
                and allocation.device_reference == normalized_reference
            ):
                return allocation.sender_id

        sender_id = self._next_sender_id(interface)
        interface.allocated_sender_ids.append(
            SenderIdAllocation(
                sender_id=sender_id,
                device_type=DEVICE_TYPE_VIRTUAL_DEVICE,
                device_reference=normalized_reference,
            )
        )
        self._save()

        return sender_id

    def allocate_emulated_sender(
        self,
        *,
        destination_id: str,
        interface_id: str = DEFAULT_INTERFACE_ID,
        base_id: str | None = None,
    ) -> str:
        """Allocate or return a stable sender ID for one TX destination."""

        interface = self._get_or_create_interface(
            interface_id=interface_id,
            base_id=base_id,
        )
        normalized_destination_id = _normalize_hex(destination_id, width=8)

        for allocation in interface.allocated_sender_ids:
            if (
                allocation.device_type == DEVICE_TYPE_EMULATED_SENDER
                and allocation.destination_id == normalized_destination_id
            ):
                return allocation.sender_id

        sender_id = self._next_sender_id(interface)
        interface.allocated_sender_ids.append(
            SenderIdAllocation(
                sender_id=sender_id,
                device_type=DEVICE_TYPE_EMULATED_SENDER,
                destination_id=normalized_destination_id,
            )
        )
        self._save()

        return sender_id

    def release_virtual_device(
        self,
        *,
        virtual_device_id: str,
    ) -> str | None:
        """Release allocated sender ID for one virtual device."""

        normalized = virtual_device_id.strip().lower()

        for interface in self.file.interfaces:
            for index, allocation in enumerate(interface.allocated_sender_ids):
                if allocation.device_type != DEVICE_TYPE_VIRTUAL_DEVICE:
                    continue

                if allocation.device_reference != normalized:
                    continue

                removed = interface.allocated_sender_ids.pop(index)
                self._save()
                return removed.sender_id

        return None

    def release_emulated_sender(
        self,
        *,
        sender_id: str | None = None,
        destination_id: str | None = None,
    ) -> str | None:
        """Release an allocated emulated sender by sender or destination ID."""

        normalized_sender_id = (
            _normalize_hex(sender_id, width=8) if sender_id else None
        )
        normalized_destination_id = (
            _normalize_hex(destination_id, width=8) if destination_id else None
        )

        if normalized_sender_id is None and normalized_destination_id is None:
            raise SenderIdRegistryError(
                "release_emulated_sender requires sender_id or destination_id"
            )

        for interface in self.file.interfaces:
            for index, allocation in enumerate(interface.allocated_sender_ids):
                if allocation.device_type != DEVICE_TYPE_EMULATED_SENDER:
                    continue

                if (
                    normalized_sender_id is not None
                    and allocation.sender_id != normalized_sender_id
                ):
                    continue

                if (
                    normalized_destination_id is not None
                    and allocation.destination_id != normalized_destination_id
                ):
                    continue

                removed = interface.allocated_sender_ids.pop(index)
                self._save()
                return removed.sender_id

        return None

    def _load(self) -> SenderIdRegistryFile:
        if not self.path.exists():
            return SenderIdRegistryFile(
                manufacturer_id=DEFAULT_MANUFACTURER_ID,
                interfaces=[],
            )

        raw_content = self.path.read_text(encoding="utf-8").strip()

        if not raw_content:
            return SenderIdRegistryFile(
                manufacturer_id=DEFAULT_MANUFACTURER_ID,
                interfaces=[],
            )

        return SenderIdRegistryFile.model_validate(json.loads(raw_content))

    def _save(self) -> None:
        self.file = SenderIdRegistryFile.model_validate(
            self.file.model_dump(mode="json")
        )

        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

        self.path.write_text(
            json.dumps(
                self.file.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def _get_or_create_interface(
        self,
        *,
        interface_id: str,
        base_id: str | None,
    ) -> SenderIdInterface:
        for interface in self.file.interfaces:
            if interface.interface_id == interface_id:
                return interface

        effective_base_id = base_id or self.default_base_id

        if effective_base_id is None:
            raise SenderIdRegistryError(
                "Cannot initialise sender registry interface without base_id"
            )

        interface = SenderIdInterface(
            interface_id=interface_id,
            base_id=effective_base_id,
            allocated_sender_ids=[],
        )
        self.file.interfaces.append(interface)
        self._save()

        return interface

    @staticmethod
    def _next_sender_id(interface: SenderIdInterface) -> str:
        base = int(interface.base_id, 16)
        used = {
            int(allocation.sender_id, 16)
            for allocation in interface.allocated_sender_ids
        }

        for offset in range(1, 128):
            candidate = base + offset

            if candidate not in used:
                return f"{candidate:08X}"

        raise SenderIdRegistryError(
            f"No free sender IDs left for interface {interface.interface_id}"
        )


def _normalize_hex(value: str | None, *, width: int) -> str:
    if value is None:
        raise ValueError("hex value must not be None")

    normalized = str(value).strip().upper()

    if normalized.startswith("0X"):
        normalized = normalized[2:]

    return normalized.zfill(width)
