"""Virtual device registry handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enocean_mqtt.virtual_devices.models import VirtualDevice


class VirtualDeviceRegistry:
    """In-memory virtual device registry."""

    def __init__(self, devices: list[VirtualDevice]) -> None:
        self.devices = devices

    @classmethod
    def from_json(cls, path: str | Path) -> VirtualDeviceRegistry:
        """Load registry from JSON file."""

        json_path = Path(path)

        if not json_path.exists():
            return cls([])

        raw_content = json_path.read_text(encoding="utf-8").strip()

        if not raw_content:
            return cls([])

        payload = json.loads(raw_content)

        device_items: list[dict[str, Any]]

        if isinstance(payload, list):
            device_items = payload
        else:
            device_items = payload.get("virtual_devices", [])

        devices = [VirtualDevice(**item) for item in device_items]

        return cls(devices)

    def to_json(self, path: str | Path) -> None:
        """Write registry to virtual-devices.json."""

        json_path = Path(path)

        if not json_path.parent.exists():
            json_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "virtual_devices": [
                device.model_dump(mode="json")
                for device in self.devices
            ]
        }

        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get_by_id(
        self,
        virtual_device_id: str,
    ) -> VirtualDevice | None:
        """Return virtual device by runtime identity."""

        normalized = virtual_device_id.strip().lower()

        for device in self.devices:
            if device.virtual_device_id == normalized:
                return device

        return None

    def upsert(
        self,
        new_device: VirtualDevice,
    ) -> tuple[str, VirtualDevice]:
        """Insert or replace virtual device by runtime identity."""

        for index, existing_device in enumerate(self.devices):
            if (
                existing_device.virtual_device_id
                != new_device.virtual_device_id
            ):
                continue

            self.devices[index] = new_device
            return "updated", new_device

        self.devices.append(new_device)

        return "created", new_device

    def delete(
        self,
        virtual_device_id: str,
    ) -> VirtualDevice | None:
        """Delete one virtual device from registry."""

        normalized = virtual_device_id.strip().lower()

        for index, existing_device in enumerate(self.devices):
            if existing_device.virtual_device_id != normalized:
                continue

            removed_device = self.devices.pop(index)
            return removed_device

        return None
