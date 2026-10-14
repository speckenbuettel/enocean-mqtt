"""Device registry handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enocean_mqtt.devices.models import Device


class DeviceRegistry:
    """In-memory EnOcean physical device registry."""

    def __init__(self, devices: list[Device]) -> None:
        self.devices = devices

    @classmethod
    def from_json(cls, path: str | Path) -> DeviceRegistry:
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
            device_items = payload.get("devices", [])

        devices = [Device(**item) for item in device_items]

        return cls(devices)

    def to_json(self, path: str | Path) -> None:
        """Write registry to devices.json."""

        json_path = Path(path)

        if not json_path.parent.exists():
            json_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "devices": [
                device.model_dump(mode="json")
                for device in self.devices
            ]
        }

        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get_by_device_id(self, device_id: str) -> Device | None:
        """Return physical device by device ID."""

        normalized_device_id = device_id.strip().upper()

        for device in self.devices:
            if device.device_id.upper() == normalized_device_id:
                return device

        return None

    def upsert(self, new_device: Device) -> tuple[str, Device]:
        """Insert or replace device by device_id."""

        normalized_device_id = new_device.device_id.strip().upper()

        for index, existing_device in enumerate(self.devices):
            if existing_device.device_id.upper() != normalized_device_id:
                continue

            self.devices[index] = new_device

            return "updated", new_device

        self.devices.append(new_device)

        return "created", new_device

    def remove(self, device_id: str) -> Device | None:
        """Remove and return one physical device by device ID."""

        normalized_device_id = device_id.strip().upper()

        for index, existing_device in enumerate(self.devices):
            if existing_device.device_id.upper() != normalized_device_id:
                continue

            return self.devices.pop(index)

        return None
