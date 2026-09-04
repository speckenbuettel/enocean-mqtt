"""EnOcean project export projection for integration clients."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from enocean_mqtt.datapoints.models import Datapoint
from enocean_mqtt.devices.projection import ApiDevice
from enocean_mqtt.runtime.service import RuntimeService

FORMAT = "enocean-project"
FORMAT_VERSION = 1
API_VERSION = "v1"


def build_enocean_project_export(
    service: RuntimeService,
    *,
    project_id: str,
    base_topic: str | None,
    generator_version: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an OBS/import-oriented project snapshot."""

    timestamp = generated_at or datetime.now(UTC)

    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "generated_at": timestamp.isoformat(),
        "generator": {
            "name": "enocean-mqtt",
            "version": generator_version,
        },
        "source": _drop_none(
            {
                "project_id": project_id,
                "base_topic": base_topic,
                "api_version": API_VERSION,
            }
        ),
        "devices": [
            _project_device(
                device,
                datapoints=service.datapoint_registry.by_device(device.id),
            )
            for device in service.api_device_registry.devices
        ],
        "issues": [
            *service.api_device_registry.issues,
            *service.datapoint_registry.issues,
        ],
    }


def _project_device(
    device: ApiDevice,
    *,
    datapoints: list[Datapoint],
) -> dict[str, Any]:
    channels = [
        _project_endpoint(
            datapoint,
            kind="channel",
            obs_binding_direction="SOURCE",
        )
        for datapoint in datapoints
        if datapoint.readable
    ]
    messages = [
        _project_endpoint(
            datapoint,
            kind="message",
            obs_binding_direction="TARGET",
        )
        for datapoint in datapoints
        if datapoint.writable
    ]

    return _drop_none(
        {
            "id": device.id,
            "source_type": device.source_type,
            "device_id": device.device_id,
            "virtual_device_id": device.virtual_device_id,
            "sender_id": device.sender_id,
            "alias": device.alias,
            "display_name": _display_name(device),
            "eep": device.eep,
            "profile": device.profile,
            "enabled": device.enabled,
            "metadata": device.metadata or None,
            "capabilities": {
                "readable": bool(channels),
                "writable": bool(messages),
                "channels_count": len(channels),
                "messages_count": len(messages),
            },
            "channels": channels,
            "messages": messages,
        }
    )


def _project_endpoint(
    datapoint: Datapoint,
    *,
    kind: str,
    obs_binding_direction: str,
) -> dict[str, Any]:
    return _drop_none(
        {
            "id": datapoint.id,
            "name": datapoint.name,
            "display_name": datapoint.display_name,
            "kind": kind,
            "direction": datapoint.direction,
            "semantic_role": datapoint.semantic_role,
            "object_type": datapoint.object_type,
            "data_type": datapoint.data_type,
            "unit": datapoint.unit,
            "description": datapoint.description,
            "enum": datapoint.enum or None,
            "ranges": datapoint.ranges or None,
            "default_value": datapoint.default_value,
            "value_resolution": datapoint.value_resolution,
            "value_precision": datapoint.value_precision,
            "metadata": datapoint.metadata or None,
            "source": datapoint.source.to_api_dict(),
            "obs": {
                "suggested_datapoint_name": (
                    datapoint.display_name or datapoint.name
                ),
                "suggested_binding_direction": obs_binding_direction,
            },
        }
    )


def _display_name(device: ApiDevice) -> str:
    return (
        device.device_name
        or device.alias
        or device.sender_id
        or device.device_id
        or device.virtual_device_id
        or device.id
    )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }
