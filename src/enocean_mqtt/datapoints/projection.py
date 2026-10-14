"""Projection from runtime configuration and Registry v3 into datapoints."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from enocean_mqtt.datapoints.models import (
    Datapoint,
    DatapointDirection,
    DatapointSource,
    DatapointSourceType,
)
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.models import (
    ChannelDefinition,
    EEPDefinition,
    MessageDefinition,
    ValueMapping,
    ValueRangeMapping,
)
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry

_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def project_from_config_files(
    *,
    devices_file: str | Path,
    virtual_devices_file: str | Path | None = None,
) -> tuple[list[Datapoint], list[dict[str, Any]]]:
    """Project configured physical and virtual devices to datapoints."""

    datapoints: list[Datapoint] = []
    issues: list[dict[str, Any]] = []

    for device in _load_physical_devices(Path(devices_file)):
        projected, device_issues = _project_physical_device(device)
        datapoints.extend(projected)
        issues.extend(device_issues)

    if virtual_devices_file is not None:
        projected, virtual_issues = _project_virtual_devices(
            Path(virtual_devices_file)
        )
        datapoints.extend(projected)
        issues.extend(virtual_issues)

    return _deduplicate_datapoints(datapoints), issues


def _project_physical_device(
    device: Mapping[str, Any],
) -> tuple[list[Datapoint], list[dict[str, Any]]]:
    device_id = _device_api_id(device)
    gateway_device_id = _normalize_hex_id(device.get("device_id"))
    sender_id = _normalize_hex_id(device.get("sender_id"))
    profile = _first_text(device.get("profile"), device.get("eep"))
    tx_profile = _first_text(
        device.get("tx_profile"),
        device.get("tx_eep"),
        device.get("profile"),
        device.get("eep"),
    )
    datapoints: list[Datapoint] = []
    issues: list[dict[str, Any]] = []

    if profile is not None:
        eep_definition, issue = _safe_load_eep(
            profile,
            source_type="physical_device",
            device_id=device_id,
        )

        if eep_definition is not None:
            datapoints.extend(
                _datapoints_from_channels(
                    api_device_id=device_id,
                    source_type="physical_device",
                    source_device_id=gateway_device_id,
                    source_virtual_device_id=None,
                    sender_id=sender_id,
                    profile=profile,
                    eep=eep_definition.eep,
                    channels=_discovery_channels(eep_definition),
                    writable=False,
                )
            )
        elif issue is not None:
            issues.append(issue)

    if tx_profile is not None:
        eep_definition, issue = _safe_load_eep(
            tx_profile,
            source_type="physical_device",
            device_id=device_id,
        )

        if eep_definition is not None:
            datapoints.extend(
                _datapoints_from_messages(
                    api_device_id=device_id,
                    source_type="physical_device",
                    source_device_id=gateway_device_id,
                    source_virtual_device_id=None,
                    sender_id=sender_id,
                    profile=tx_profile,
                    eep=eep_definition.eep,
                    messages=eep_definition.messages,
                )
            )
        elif issue is not None:
            issues.append(issue)

    return _deduplicate_datapoints(datapoints), issues


def _project_virtual_devices(
    virtual_devices_file: Path,
) -> tuple[list[Datapoint], list[dict[str, Any]]]:
    datapoints: list[Datapoint] = []
    issues: list[dict[str, Any]] = []

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

    for device in registry.devices:
        eep_definition, issue = _safe_load_eep(
            device.registry_profile,
            source_type="virtual_device",
            device_id=device.virtual_device_id,
        )

        if eep_definition is None:
            if issue is not None:
                issues.append(issue)
            continue

        enabled_channels = set(device.channels)
        datapoints.extend(
            _datapoints_from_channels(
                api_device_id=device.virtual_device_id,
                source_type="virtual_device",
                source_device_id=None,
                source_virtual_device_id=device.virtual_device_id,
                sender_id=device.sender_id,
                profile=device.registry_profile,
                eep=eep_definition.eep,
                channels=[
                    channel
                    for channel in eep_definition.channels
                    if channel.name in enabled_channels
                ],
                writable=True,
            )
        )

    return _deduplicate_datapoints(datapoints), issues


def _datapoints_from_channels(
    *,
    api_device_id: str,
    source_type: DatapointSourceType,
    source_device_id: str | None,
    source_virtual_device_id: str | None,
    sender_id: str | None,
    profile: str,
    eep: str | None,
    channels: list[ChannelDefinition],
    writable: bool,
) -> list[Datapoint]:
    datapoints: list[Datapoint] = []

    for channel in channels:
        if not channel.output.api:
            continue

        direction: DatapointDirection = "write" if writable else "read"
        datapoints.append(
            _build_datapoint(
                api_device_id=api_device_id,
                name=channel.name,
                display_name=channel.display_name or channel.friendly_name,
                semantic_role=channel.semantic_role,
                object_type=channel.api_object_type,
                data_type=channel.data_type,
                unit=channel.unit,
                readable=not writable,
                writable=writable,
                direction=direction,
                stateful=True,
                description=channel.description,
                enum=channel.enum,
                ranges=channel.ranges,
                default_value=channel.default_value,
                value_resolution=channel.value_resolution,
                value_precision=channel.value_precision,
                metadata=channel.metadata,
                source=DatapointSource(
                    source_type=source_type,
                    collection=(
                        "virtual_channels"
                        if source_type == "virtual_device"
                        else "channels"
                    ),
                    name=channel.name,
                    profile=profile,
                    eep=eep,
                    device_id=source_device_id,
                    virtual_device_id=source_virtual_device_id,
                    sender_id=sender_id,
                ),
            )
        )

    return datapoints


def _datapoints_from_messages(
    *,
    api_device_id: str,
    source_type: DatapointSourceType,
    source_device_id: str | None,
    source_virtual_device_id: str | None,
    sender_id: str | None,
    profile: str,
    eep: str | None,
    messages: list[MessageDefinition],
) -> list[Datapoint]:
    datapoints: list[Datapoint] = []

    for message in messages:
        if not message.output.api:
            continue

        datapoints.append(
            _build_datapoint(
                api_device_id=api_device_id,
                name=message.name,
                display_name=message.display_name,
                semantic_role=message.semantic_role,
                object_type=message.object_type,
                data_type=message.data_type,
                unit=message.unit,
                readable=False,
                writable=True,
                direction="write",
                stateful=True,
                description=message.description,
                enum=message.enum,
                ranges=message.ranges,
                default_value=message.default_value,
                value_resolution=message.value_resolution,
                value_precision=message.value_precision,
                metadata=message.metadata,
                source=DatapointSource(
                    source_type=source_type,
                    collection="messages",
                    name=message.name,
                    profile=profile,
                    eep=eep,
                    device_id=source_device_id,
                    virtual_device_id=source_virtual_device_id,
                    sender_id=sender_id,
                ),
            )
        )

    return datapoints


def _build_datapoint(
    *,
    api_device_id: str,
    name: str,
    display_name: str | None,
    semantic_role: str | None,
    object_type: str | None,
    data_type: str | None,
    unit: str | None,
    readable: bool,
    writable: bool,
    direction: DatapointDirection,
    stateful: bool,
    description: str | None,
    enum: list[ValueMapping],
    ranges: list[ValueRangeMapping],
    default_value: Any,
    value_resolution: float | None,
    value_precision: int | None,
    metadata: dict[str, Any],
    source: DatapointSource,
) -> Datapoint:
    return Datapoint(
        id=f"{_safe_identifier(api_device_id)}.{_safe_identifier(name)}",
        device_id=api_device_id,
        name=name,
        display_name=display_name,
        semantic_role=semantic_role,
        object_type=object_type,
        data_type="integer" if readable and (data_type == "enum" or enum) else data_type,
        unit=unit,
        readable=readable,
        writable=writable,
        direction=direction,
        stateful=stateful,
        description=description,
        enum=[_enum_to_dict(item) for item in enum],
        ranges=[_range_to_dict(item) for item in ranges],
        default_value=default_value,
        value_resolution=value_resolution,
        value_precision=value_precision,
        metadata=metadata,
        source=source,
    )


def _discovery_channels(definition: EEPDefinition) -> list[ChannelDefinition]:
    """Include binding-only enum metadata; runtime meaning remains variant-specific."""
    result = []
    for channel in definition.channels:
        variants = [
            {"telegram_type_id": telegram.telegram_type_id,
             "enum": [_enum_to_dict(item) for item in binding.enum]}
            for telegram in definition.telegrams for binding in telegram.channel_bindings
            if binding.channel_ref == channel.name and binding.enum
        ]
        bindings = [binding for telegram in definition.telegrams
                    for binding in telegram.channel_bindings
                    if binding.channel_ref == channel.name and binding.enum]
        enum = channel.enum
        if bindings:
            enum = bindings[0].enum if all(b.enum == bindings[0].enum for b in bindings) else []
        result.append(replace(
            channel, enum=enum,
            data_type="enum" if variants else channel.data_type,
            metadata={**channel.metadata, "enum_variants": variants}
            if variants else channel.metadata,
        ))
    return result


def _safe_load_eep(
    profile: str,
    *,
    source_type: str,
    device_id: str,
) -> tuple[EEPDefinition | None, dict[str, Any] | None]:
    try:
        return load_eep_definition(profile), None
    except (EEPRegistryError, OSError, json.JSONDecodeError, ValueError) as exc:
        return None, {
            "source_type": source_type,
            "device_id": device_id,
            "profile": profile,
            "error": str(exc),
        }


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
    return _first_text(
        device.get("alias"),
        _normalize_hex_id(device.get("device_id")),
        device.get("device_id"),
    ) or "unknown_device"


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue

        text = str(value).strip()

        if text:
            return text

    return None


def _normalize_hex_id(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip().replace(" ", "").replace("-", "").replace(":", "")

    if text.lower().startswith("0x"):
        text = text[2:]

    return text.upper() if text else None


def _safe_identifier(value: str) -> str:
    return _IDENTIFIER_RE.sub("_", value.strip()).strip("_") or "unnamed"


def _enum_to_dict(item: ValueMapping) -> dict[str, Any]:
    return _drop_none(
        {
            "value": item.value,
            "label": item.label,
            "semantic_value": item.semantic_value,
            "description": item.description,
        }
    )


def _range_to_dict(item: ValueRangeMapping) -> dict[str, Any]:
    return _drop_none(
        {
            "min": item.min,
            "max": item.max,
            "step": item.step,
            "unit": item.unit,
            "description": item.description,
            "raw_min": item.raw_min,
            "raw_max": item.raw_max,
            "label": item.label,
        }
    )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }


def _deduplicate_datapoints(datapoints: list[Datapoint]) -> list[Datapoint]:
    result: dict[str, Datapoint] = {}

    for datapoint in datapoints:
        result.setdefault(datapoint.id, datapoint)

    return list(result.values())
