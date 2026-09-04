"""API-facing semantic device projection.

This module builds the device discovery model consumed by the Web API from
configured physical devices, configured virtual devices and the canonical
DatapointRegistry.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Literal

from enocean_mqtt.datapoints import DatapointRegistry
from enocean_mqtt.datapoints.models import Datapoint
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry

DeviceSourceType = Literal["physical_device", "virtual_device"]

_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class ApiDevice:
    """API-facing semantic device."""

    id: str
    source_type: DeviceSourceType
    readable: bool
    writable: bool
    datapoints_count: int
    datapoints_url: str
    device_id: str | None = None
    virtual_device_id: str | None = None
    sender_id: str | None = None
    alias: str | None = None
    device_name: str | None = None
    description: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    eep: str | None = None
    profile: str | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        """Return public API representation."""

        return _drop_none(
            {
                "id": self.id,
                "source_type": self.source_type,
                "device_id": self.device_id,
                "virtual_device_id": self.virtual_device_id,
                "sender_id": self.sender_id,
                "alias": self.alias,
                "device_name": self.device_name,
                "description": self.description,
                "manufacturer": self.manufacturer,
                "model": self.model,
                "eep": self.eep,
                "profile": self.profile,
                "enabled": self.enabled,
                "readable": self.readable,
                "writable": self.writable,
                "datapoints_count": self.datapoints_count,
                "datapoints_url": self.datapoints_url,
                "metadata": self.metadata or None,
            }
        )


@dataclass(slots=True)
class ApiDeviceRegistry:
    """In-memory API device projection."""

    devices: list[ApiDevice]
    issues: list[dict[str, Any]] = dataclass_field(default_factory=list)

    @classmethod
    def from_config_files(
        cls,
        *,
        devices_file: str | Path,
        virtual_devices_file: str | Path | None,
        datapoint_registry: DatapointRegistry,
    ) -> ApiDeviceRegistry:
        """Build the API device registry from config files."""

        devices: list[ApiDevice] = []
        issues: list[dict[str, Any]] = []

        for device in _load_physical_devices(Path(devices_file)):
            device_id = _device_api_id(device)
            devices.append(
                _project_physical_device(
                    device,
                    datapoints=datapoint_registry.by_device(device_id),
                )
            )

        if virtual_devices_file is not None:
            projected, virtual_issues = _project_virtual_devices(
                Path(virtual_devices_file),
                datapoint_registry=datapoint_registry,
            )
            devices.extend(projected)
            issues.extend(virtual_issues)

        return cls(
            devices=sorted(devices, key=lambda item: item.id),
            issues=[*datapoint_registry.issues, *issues],
        )

    def get(self, device_id: str) -> ApiDevice | None:
        """Return one API device by API-facing ID."""

        for device in self.devices:
            if device.id == device_id:
                return device

        return None

    def to_api_dict(self) -> dict[str, Any]:
        """Return list payload."""

        return {
            "devices": [device.to_api_dict() for device in self.devices],
            "count": len(self.devices),
            "issues": self.issues,
        }


def _project_physical_device(
    device: Mapping[str, Any],
    *,
    datapoints: list[Datapoint],
) -> ApiDevice:
    api_device_id = _device_api_id(device)

    return ApiDevice(
        id=api_device_id,
        source_type="physical_device",
        device_id=_normalize_hex_id(device.get("device_id")),
        virtual_device_id=None,
        sender_id=_normalize_hex_id(device.get("sender_id")),
        alias=_text_or_none(device.get("alias")),
        device_name=_text_or_none(device.get("device_name")),
        description=_text_or_none(device.get("description")),
        manufacturer=_text_or_none(device.get("manufacturer")),
        model=_text_or_none(device.get("model")),
        eep=_text_or_none(device.get("eep")),
        profile=_first_text(device.get("profile"), device.get("eep")),
        enabled=_bool_or_none(device.get("enabled")),
        metadata=_metadata_or_empty(device.get("metadata")),
        readable=any(datapoint.readable for datapoint in datapoints),
        writable=any(datapoint.writable for datapoint in datapoints),
        datapoints_count=len(datapoints),
        datapoints_url=f"/api/v1/devices/{api_device_id}/datapoints",
    )


def _project_virtual_devices(
    virtual_devices_file: Path,
    *,
    datapoint_registry: DatapointRegistry,
) -> tuple[list[ApiDevice], list[dict[str, Any]]]:
    try:
        registry = VirtualDeviceRegistry.from_json(virtual_devices_file)
    except Exception as exc:
        return [], [
            {
                "source_type": "virtual_device_registry",
                "path": str(virtual_devices_file),
                "error": str(exc),
            }
        ]

    devices: list[ApiDevice] = []

    for device in registry.devices:
        datapoints = datapoint_registry.by_device(device.virtual_device_id)
        devices.append(
            ApiDevice(
                id=device.virtual_device_id,
                source_type="virtual_device",
                device_id=None,
                virtual_device_id=device.virtual_device_id,
                sender_id=device.sender_id,
                alias=device.virtual_device_id,
                device_name=_text_or_none(device.metadata.get("device_name")),
                description=device.description,
                manufacturer=_text_or_none(device.metadata.get("manufacturer")),
                model=_text_or_none(device.metadata.get("model")),
                eep=device.eep,
                profile=device.registry_profile,
                enabled=device.enabled,
                metadata=device.metadata,
                readable=any(datapoint.readable for datapoint in datapoints),
                writable=any(datapoint.writable for datapoint in datapoints),
                datapoints_count=len(datapoints),
                datapoints_url=(
                    f"/api/v1/devices/{device.virtual_device_id}/datapoints"
                ),
            )
        )

    return devices, []


def _load_physical_devices(devices_file: Path) -> list[dict[str, Any]]:
    if not devices_file.exists():
        return []

    try:
        payload = json.loads(devices_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(payload, list):
        devices = payload
    else:
        devices = payload.get("devices", [])

    return [dict(item) for item in devices if isinstance(item, dict)]


def _device_api_id(device: Mapping[str, Any]) -> str:
    return _safe_identifier(
        _first_text(
            device.get("alias"),
            _normalize_hex_id(device.get("device_id")),
            device.get("device_id"),
        ) or "unknown_device"
    )


def _safe_identifier(value: str) -> str:
    return _IDENTIFIER_RE.sub("_", value.strip()).strip("_") or "unnamed"


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text_or_none(value)

        if text is not None:
            return text

    return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def _normalize_hex_id(value: Any) -> str | None:
    if value is None:
        return None

    text = (
        str(value)
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace(":", "")
    )

    if text.lower().startswith("0x"):
        text = text[2:]

    return text.upper() if text else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _metadata_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }
