"""TX profile resolution and capability helpers for physical devices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enocean_mqtt.devices.models import Device
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.models import EEPDefinition, MessageDefinition
from enocean_mqtt.gateway.topics import (
    DeviceTopicRef,
    device_message_set_topic,
    normalize_device_id,
)

TX_CAPABLE_COMMUNICATION = {
    "bidirectional_eep",
    "bidirectional_eep_pair",
}


class DeviceTxProfileError(ValueError):
    """Raised when a physical-device TX profile cannot be resolved."""


def resolve_device_tx_profile(
    device: Device,
    *,
    controller_mapping_path: str | Path = "config/device-controller-mappings.json",
) -> str:
    """Resolve the effective Registry-v3 TX profile for one physical device."""

    if device.communication == "bidirectional_eep":
        profile = device.profile or device.eep

        if not profile:
            raise DeviceTxProfileError(
                f"Bidirectional EEP device has no profile/eep: {device.device_id}"
            )

        return normalize_profile_ref(profile)

    if device.communication == "bidirectional_eep_pair":
        if device.tx_profile:
            return normalize_profile_ref(device.tx_profile)

        mapping_key = device.registry_profile

        if not mapping_key:
            raise DeviceTxProfileError(
                "Bidirectional EEP pair device has no receive-side profile: "
                f"{device.device_id}"
            )

        mapped_profile = load_controller_mappings(
            controller_mapping_path,
        ).get(normalize_profile_ref(mapping_key))

        if not mapped_profile:
            raise DeviceTxProfileError(
                "No TX profile mapping for bidirectional EEP pair device: "
                f"device_id={device.device_id} profile={mapping_key}"
            )

        return mapped_profile

    raise DeviceTxProfileError(
        f"Unsupported physical device TX communication model: {device.communication}"
    )


def load_controller_mappings(
    controller_mapping_path: str | Path,
) -> dict[str, str]:
    """Load device profile to controller/TX profile mappings."""

    path = Path(controller_mapping_path)

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    mappings: dict[str, str] = {}

    for item in payload.get("mappings", []):
        device_eep = item.get("device_eep")
        sender_eep = item.get("sender_eep")

        if not device_eep or not sender_eep:
            continue

        mappings[normalize_profile_ref(str(device_eep))] = normalize_profile_ref(
            str(sender_eep)
        )

    return mappings


def load_tx_definition(tx_profile: str) -> EEPDefinition:
    """Load and validate an encodable TX Registry-v3 definition."""

    try:
        definition = load_eep_definition(tx_profile)
    except EEPRegistryError as exc:
        raise DeviceTxProfileError(
            f"Unable to load TX profile {tx_profile}: {exc}"
        ) from exc

    tx_telegrams = [
        telegram
        for telegram in definition.telegrams
        if telegram.direction in {None, "tx"}
        and telegram.message_bindings
    ]

    if not tx_telegrams:
        raise DeviceTxProfileError(
            f"TX profile has no encodable TX telegrams: {tx_profile}"
        )

    return definition


def build_device_tx_capabilities(
    *,
    device: Device,
    base_topic: str,
    topic_ref: DeviceTopicRef,
    controller_mapping_path: str | Path = "config/device-controller-mappings.json",
) -> dict[str, Any] | None:
    """Build retained MQTT TX capabilities for one physical device topic ref."""

    if device.communication not in TX_CAPABLE_COMMUNICATION:
        return None

    tx_profile = resolve_device_tx_profile(
        device,
        controller_mapping_path=controller_mapping_path,
    )
    tx_definition = load_tx_definition(tx_profile)
    messages = {
        message.name: _message_capability(
            message=message,
            base_topic=base_topic,
            topic_ref=topic_ref,
        )
        for message in tx_definition.messages
        if not (message.tx is not None and message.tx.managed)
    }

    if not messages:
        return None

    return {
        "device_id": normalize_device_id(device.device_id),
        "communication": device.communication,
        "rx_profile": device.registry_profile,
        "tx_profile": tx_profile,
        "sender_id": device.sender_id,
        "messages": messages,
    }


def normalize_profile_ref(value: str) -> str:
    """Normalize standard EEP and proprietary profile references."""

    normalized = str(value).strip()

    if "-" in normalized and len(normalized) == 8:
        return normalized.upper()

    return normalized.lower()


def _message_capability(
    *,
    message: MessageDefinition,
    base_topic: str,
    topic_ref: DeviceTopicRef,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "topic": device_message_set_topic(
            base_topic,
            topic_ref,
            message.name,
        ),
        "description": message.description,
        "data_type": message.data_type,
        "object_type": message.object_type,
        "semantic_role": message.semantic_role,
        "unit": message.unit,
    }

    if message.enum:
        payload["values"] = [item.label for item in message.enum]

    if message.ranges:
        first_range = message.ranges[0]

        if first_range.min is not None:
            payload["min"] = first_range.min

        if first_range.max is not None:
            payload["max"] = first_range.max

        if first_range.step is not None:
            payload["step"] = first_range.step

    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }
