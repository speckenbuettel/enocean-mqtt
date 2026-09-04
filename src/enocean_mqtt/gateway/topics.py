"""MQTT topic builders for the semantic device gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from enocean_mqtt.devices.models import Device

DeviceTopicIdentifier = Literal["device_id", "alias", "both"]


def normalize_base_topic(base_topic: str) -> str:
    """Return base topic without leading or trailing separators."""

    return base_topic.strip("/")


def normalize_device_id(device_id: str) -> str:
    """Return canonical physical device ID according to mqtt-model.md."""

    normalized = device_id.strip()

    if normalized.lower().startswith("0x"):
        normalized = normalized[2:]

    return normalized.upper()


def normalize_alias(alias: str) -> str:
    """Return MQTT-safe alias."""

    return alias.strip().lower().strip("/")


@dataclass(frozen=True)
class DeviceTopicRef:
    """Resolved MQTT topic identity for a device."""

    identifier_type: Literal["device_id", "alias"]
    identifier: str


class DeviceTopicResolver:
    """Resolve read and write topic namespaces for a device."""

    def __init__(
        self,
        device_topic_identifier: DeviceTopicIdentifier = "device_id",
    ) -> None:
        if device_topic_identifier not in {"device_id", "alias", "both"}:
            raise ValueError(
                "Unsupported device_topic_identifier: "
                f"{device_topic_identifier}"
            )

        self._device_topic_identifier = device_topic_identifier

    def iter_read_topic_refs(self, device: Device) -> list[DeviceTopicRef]:
        """Return topic refs for read/state publications."""

        device_ref = DeviceTopicRef(
            identifier_type="device_id",
            identifier=normalize_device_id(device.device_id),
        )

        alias_ref = None

        if device.alias:
            alias_ref = DeviceTopicRef(
                identifier_type="alias",
                identifier=normalize_alias(device.alias),
            )

        if self._device_topic_identifier == "device_id":
            return [device_ref]

        if self._device_topic_identifier == "alias":
            return [alias_ref] if alias_ref is not None else [device_ref]

        if alias_ref is None:
            return [device_ref]

        return [device_ref, alias_ref]

    def write_topic_ref(self, device: Device) -> DeviceTopicRef:
        """Return device_id-only topic ref for command/set publications."""

        return DeviceTopicRef(
            identifier_type="device_id",
            identifier=normalize_device_id(device.device_id),
        )


def _device_base(base_topic: str, topic_ref: DeviceTopicRef) -> str:
    namespace = "alias" if topic_ref.identifier_type == "alias" else "device"

    return (
        f"{normalize_base_topic(base_topic)}/{namespace}/"
        f"{topic_ref.identifier}"
    )


def device_info_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/info."""

    return f"{_device_base(base_topic, topic_ref)}/info"


def device_capabilities_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/capabilities."""

    return f"{_device_base(base_topic, topic_ref)}/capabilities"


def device_metrics_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/metrics."""

    return f"{_device_base(base_topic, topic_ref)}/metrics"


def device_state_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/state."""

    return f"{_device_base(base_topic, topic_ref)}/state"


def device_message_set_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
    message: str,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/message/<message>/set."""

    return f"{_device_base(base_topic, topic_ref)}/message/{message}/set"


def device_command_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/command."""

    return f"{_device_base(base_topic, topic_ref)}/command"


def channel_value_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
    channel: str,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/channel/<channel>/value."""

    return f"{_device_base(base_topic, topic_ref)}/channel/{channel}/value"


def channel_state_topic(
    base_topic: str,
    topic_ref: DeviceTopicRef,
    channel: str,
) -> str:
    """Build <base_topic>/<namespace>/<identifier>/channel/<channel>/state."""

    return f"{_device_base(base_topic, topic_ref)}/channel/{channel}/state"
