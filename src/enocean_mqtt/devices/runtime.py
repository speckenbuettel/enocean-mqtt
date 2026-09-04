"""Runtime enrichment of device inventory using EEP registry."""

from __future__ import annotations

from typing import Any

from enocean_mqtt.devices.models import Device
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition


def build_runtime_device(device: Device) -> dict[str, Any]:
    """Build runtime-enriched device object."""

    payload: dict[str, Any] = {
        "device_id": device.device_id,
        "device_name": device.device_name,
        "alias": device.alias,
        "communication": device.communication,
        "eep": device.eep,
        "profile": device.profile,
        "tx_eep": device.tx_eep,
        "tx_profile": device.tx_profile,
        "sender_id": device.sender_id,
        "enabled": device.enabled,
        "enocean_secure": device.enocean_secure,
        "metadata": device.metadata,
    }

    eep_definition = None
    registry_profile = device.registry_profile

    if registry_profile is not None:
        try:
            eep_definition = load_eep_definition(registry_profile)
        except EEPRegistryError:
            eep_definition = None

    if eep_definition:
        payload["eep_definition"] = {
            "description": eep_definition.description,
            "channels": [
                {
                    "name": channel.name,
                    "data_type": channel.data_type,
                    "channel_type": channel.channel_type,
                    "unit": channel.unit,
                    "writable": channel.writable,
                }
                for channel in eep_definition.channels
            ],
        }

    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }
