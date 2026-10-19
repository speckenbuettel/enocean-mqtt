"""Semantic MQTT device publisher."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime
from time import monotonic
from typing import Any

from enocean_mqtt.devices.gateways import ExternalGateway
from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.devices.tx_profiles import (
    DeviceTxProfileError,
    build_device_tx_capabilities,
)
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.runtime_decoder import RuntimeDecodedTelegram
from enocean_mqtt.eep.semantic_mapping import derived_value
from enocean_mqtt.gateway.topics import (
    DeviceTopicIdentifier,
    DeviceTopicRef,
    DeviceTopicResolver,
    channel_state_topic,
    channel_value_topic,
    device_capabilities_topic,
    device_info_topic,
    device_metrics_topic,
    device_state_topic,
    normalize_alias,
    normalize_device_id,
)
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.replay.busmonitor_export import _decode_teach_in
from enocean_mqtt.time import build_timestamp_fields

DEFAULT_ACTIVITY_WINDOW_SECONDS = 3600
DEFAULT_PEAK_WINDOW_SECONDS = 900

logger = logging.getLogger(__name__)


class DevicePublisher:
    """Publish semantic device MQTT topics."""

    def publish_gateway_command(
        self, *, gateway: ExternalGateway, sender_id: str,
        decoded: RuntimeDecodedTelegram, timestamp: str | None,
    ) -> None:
        """Retain the latest observed external command, never actuator state."""
        self._mqtt_client.publish_json(
            f"{self._base_topic}/devices/gateways/{gateway.base_id}/{sender_id}/command",
            {
                "base_id": gateway.base_id, "sender_id": sender_id,
                "profile": decoded.eep, "profile_direction": "tx",
                "telegram_type_id": decoded.telegram_type_id, "timestamp": timestamp,
                "fields": decoded.fields,
                "values": {
                    name: {"value": item.published_value, "unit": item.unit,
                           "raw_value": item.raw_value, "meaning": item.meaning}
                    for name, item in decoded.values.items()
                },
            },
            retain=True,
        )

    def __init__(
        self,
        mqtt_client: MQTTClient,
        base_topic: str,
        device_topic_identifier: DeviceTopicIdentifier = "device_id",
        telegram_mean_interval_window_seconds: int = (
            DEFAULT_ACTIVITY_WINDOW_SECONDS
        ),
        peak_telegrams_window_seconds: int = (
            DEFAULT_PEAK_WINDOW_SECONDS
        ),
        controller_mapping_path: str = "config/device-controller-mappings.json",
    ) -> None:
        self._mqtt_client = mqtt_client
        self._base_topic = base_topic
        self._published_info: set[str] = set()
        self._device_states: dict[str, dict[str, Any]] = {}
        self._controller_mapping_path = controller_mapping_path

        self._topic_resolver = DeviceTopicResolver(
            device_topic_identifier=device_topic_identifier,
        )

        self._telegram_mean_interval_window_seconds = (
            telegram_mean_interval_window_seconds
        )

        self._peak_telegrams_window_seconds = (
            peak_telegrams_window_seconds
        )

        self._device_metrics: dict[str, dict[str, Any]] = defaultdict(
            dict
        )

    @staticmethod
    def _build_timestamp_fields(timestamp: str | None) -> dict[str, float | str]:
        """Build canonical MQTT timestamp fields."""

        if not timestamp:
            return build_timestamp_fields()

        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        return build_timestamp_fields(parsed)

    @staticmethod
    def _mqtt_output_enabled(channel: Any) -> bool:
        """Return whether a decoded channel shall be published to MQTT."""

        definition = getattr(channel, "definition", None)
        output = getattr(definition, "output", None)

        if output is None:
            return True

        return bool(getattr(output, "mqtt", True))

    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        """Return a copy of the current aggregate state for one physical device."""

        normalized_device_id = normalize_device_id(device_id)
        state = self._device_states.get(normalized_device_id)

        if state is None:
            return None

        return deepcopy(state)

    def get_device_states(self) -> dict[str, dict[str, Any]]:
        """Return copies of all current aggregate physical device states."""

        return {
            device_id: deepcopy(state)
            for device_id, state in self._device_states.items()
        }

    def publish_device_info(self, device: Device) -> None:
        """Publish retained device metadata and TX capabilities."""

        device_id = normalize_device_id(device.device_id)

        payload: dict[str, Any] = {
            "device_id": device_id,
            "device_name": device.device_name,
            "alias": device.alias,
            "description": device.description,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "communication": device.communication,
            "eep": device.eep,
            "profile": device.profile,
            "tx_eep": device.tx_eep,
            "tx_profile": device.tx_profile,
            "sender_id": device.sender_id,
            "enocean_secure": device.enocean_secure,
            "enabled": device.enabled,
            "metadata": device.metadata,
        }

        sanitized_payload = {
            key: value
            for key, value in payload.items()
            if value is not None
        }

        for topic_ref in self._topic_resolver.iter_read_topic_refs(device):
            self._mqtt_client.publish_json(
                device_info_topic(self._base_topic, topic_ref),
                sanitized_payload,
                retain=True,
            )

            self._publish_or_clear_device_capabilities(
                device=device,
                topic_ref=topic_ref,
            )

        self._published_info.add(device_id)

    def republish_devices(
        self,
        registry: DeviceRegistry,
    ) -> int:
        """Republish retained info/state topics and TX capabilities."""

        devices = list(registry.devices)

        logger.info(
            "Republishing retained info/state topics for %s devices",
            len(devices),
        )

        republished_devices = 0

        for device in devices:
            try:
                self.publish_device_info(device)

                device_id = normalize_device_id(device.device_id)
                state_payload = self._device_states.get(device_id)

                if state_payload is not None:
                    self._publish_device_state_payload(
                        device=device,
                        payload=state_payload,
                    )

                republished_devices += 1

            except Exception:
                logger.exception(
                    "Failed to republish retained topics for device %s",
                    device.device_id,
                )

        logger.info(
            "Republished retained info/state topics for %s devices",
            republished_devices,
        )

        return republished_devices

    def clear_retained_device_topics(self, device: Device) -> list[str]:
        """Clear retained MQTT topics for one device."""

        device_id = normalize_device_id(device.device_id)
        channel_names = self._retained_channel_names(device)
        topics: set[str] = set()

        for topic_ref in self._cleanup_topic_refs(device):
            topics.update(
                {
                    device_info_topic(self._base_topic, topic_ref),
                    device_capabilities_topic(self._base_topic, topic_ref),
                    device_metrics_topic(self._base_topic, topic_ref),
                    device_state_topic(self._base_topic, topic_ref),
                }
            )

            for channel_name in channel_names:
                topics.update(
                    {
                        channel_state_topic(
                            self._base_topic,
                            topic_ref,
                            channel_name,
                        ),
                        channel_value_topic(
                            self._base_topic,
                            topic_ref,
                            channel_name,
                        ),
                    }
                )

        cleared_topics: list[str] = []

        for topic in sorted(topics):
            self._mqtt_client.clear_retained_topic(topic)
            cleared_topics.append(topic)

        self._published_info.discard(device_id)
        self._device_metrics.pop(device_id, None)
        self._device_states.pop(device_id, None)

        return cleared_topics

    def _cleanup_topic_refs(self, device: Device) -> list[DeviceTopicRef]:
        """Return all retained read topic refs that may exist for a device."""

        topic_refs = [
            DeviceTopicRef(
                identifier_type="device_id",
                identifier=normalize_device_id(device.device_id),
            )
        ]

        if device.alias:
            topic_refs.append(
                DeviceTopicRef(
                    identifier_type="alias",
                    identifier=normalize_alias(device.alias),
                )
            )

        return topic_refs

    def _publish_or_clear_device_capabilities(
        self,
        *,
        device: Device,
        topic_ref: DeviceTopicRef,
    ) -> None:
        """Publish retained TX capabilities or clear stale capability topics."""

        topic = device_capabilities_topic(self._base_topic, topic_ref)

        try:
            payload = build_device_tx_capabilities(
                device=device,
                base_topic=self._base_topic,
                topic_ref=topic_ref,
                controller_mapping_path=self._controller_mapping_path,
            )
        except DeviceTxProfileError as exc:
            logger.warning(
                "Cannot build TX capabilities for device %s: %s",
                device.device_id,
                exc,
            )
            self._mqtt_client.clear_retained_topic(topic)
            return

        if payload is None:
            self._mqtt_client.clear_retained_topic(topic)
            return

        self._mqtt_client.publish_json(
            topic,
            payload,
            retain=True,
        )

    def _retained_channel_names(self, device: Device) -> set[str]:
        """Return channel topic names to clear for one device."""

        device_id = normalize_device_id(device.device_id)
        state_payload = self._device_states.get(device_id, {})
        channel_names = {
            str(channel_name)
            for channel_name in state_payload.get("channels", {})
        }

        registry_profile = device.registry_profile

        if registry_profile:
            try:
                eep_definition = load_eep_definition(registry_profile)
                channel_names.update(
                    channel.name
                    for channel in eep_definition.channels
                    if channel.output.mqtt
                )
            except EEPRegistryError:
                logger.warning(
                    "Cannot resolve EEP profile %s while clearing retained "
                    "topics for device %s",
                    registry_profile,
                    device.device_id,
                )

        channel_names.add("telegram_type")

        return channel_names

    def _calculate_telegrams_per_minute(
        self,
        timestamps: deque[float],
        window_seconds: int,
    ) -> float:
        """Calculate telegram rate within sliding window."""

        if not timestamps:
            return 0.0

        now_monotonic = monotonic()

        while timestamps and (
            now_monotonic - timestamps[0]
            > window_seconds
        ):
            timestamps.popleft()

        return round(
            len(timestamps)
            / (window_seconds / 60.0),
            2,
        )

    def publish_device_metrics(
        self,
        device: Device,
        timestamp: str | None,
        rssi_dbm: int | None = None,
    ) -> None:
        """Publish runtime device telemetry metrics."""

        device_id = normalize_device_id(device.device_id)

        metrics = self._device_metrics[device_id]

        now_monotonic = monotonic()

        if "rx_activity" not in metrics:
            metrics["rx_activity"] = deque()

        rx_activity: deque[float] = metrics["rx_activity"]

        rx_activity.append(now_monotonic)

        previous_seen = metrics.get("_last_seen_monotonic")
        telegram_mean_interval_seconds = None
        last_seen_seconds_ago = None

        if previous_seen is not None:
            telegram_mean_interval_seconds = round(
                now_monotonic - previous_seen,
                1,
            )

            last_seen_seconds_ago = round(
                now_monotonic - previous_seen,
                1,
            )

        metrics["_last_seen_monotonic"] = now_monotonic

        metrics["telegrams_total"] = (
            metrics.get("telegrams_total", 0) + 1
        )

        timestamp_fields = self._build_timestamp_fields(timestamp)

        payload = {
            **timestamp_fields,
            "telegrams_total": metrics["telegrams_total"],
            "telegrams_per_minute": (
                self._calculate_telegrams_per_minute(
                    rx_activity,
                    self._telegram_mean_interval_window_seconds,
                )
            ),
            "telegram_mean_interval_seconds": (
                telegram_mean_interval_seconds
            ),
            "last_seen": timestamp_fields["timestamp_local"],
            "last_seen_seconds_ago": last_seen_seconds_ago,
            "last_rssi_dbm": rssi_dbm,
        }

        sanitized_payload = {
            key: value
            for key, value in payload.items()
            if value is not None
        }

        metrics["_last_payload"] = sanitized_payload

        for topic_ref in self._topic_resolver.iter_read_topic_refs(device):
            self._mqtt_client.publish_json(
                device_metrics_topic(
                    self._base_topic,
                    topic_ref,
                ),
                sanitized_payload,
                retain=True,
            )

    def publish_decoded_telegram(
        self,
        device: Device,
        decoded: Any,
        timestamp: str | None,
        rorg: str | None = None,
        data: str | None = None,
    ) -> None:
        """Publish semantic decoded channel topics."""

        self.publish_device_info(device)
        self.publish_device_metrics(device, timestamp)

        timestamp_fields = self._build_timestamp_fields(timestamp)
        device_id = normalize_device_id(device.device_id)
        teach_in = _decode_teach_in(rorg, data)
        previous_state = self._device_states.get(device_id, {})
        previous_channels = previous_state.get("channels", {})
        aggregate_channels: dict[str, dict[str, Any]] = (
            deepcopy(previous_channels)
            if isinstance(previous_channels, dict)
            else {}
        )

        if teach_in is not None:
            channel_name = "telegram_type"
            channel_value = "teach_in_telegram"
            teach_in_channel_payload = {
                "value": channel_value,
                "semantic_role": "enocean.telegram",
                "object_type": "state",
                "last_update": timestamp_fields["timestamp_local"],
            }
            teach_in_channel_state_payload: dict[str, Any] = {
                **timestamp_fields,
                "channel": channel_name,
                "value": channel_value,
                "semantic_role": "enocean.telegram",
                "object_type": "state",
            }
            aggregate_channels[channel_name] = teach_in_channel_payload

            for topic_ref in self._topic_resolver.iter_read_topic_refs(device):
                self._mqtt_client.publish_json(
                    channel_state_topic(
                        self._base_topic,
                        topic_ref,
                        channel_name,
                    ),
                    teach_in_channel_state_payload,
                    retain=True,
                )

                self._mqtt_client.publish_value(
                    channel_value_topic(
                        self._base_topic,
                        topic_ref,
                        channel_name,
                    ),
                    channel_value,
                    retain=True,
                )
        else:
            for channel_name, channel in decoded.values.items():
                if not self._mqtt_output_enabled(channel):
                    continue

                channel_payload: dict[str, Any] = {
                    "value": channel.published_value,
                    "last_update": timestamp_fields["timestamp_local"],
                }

                channel_state_payload: dict[str, Any] = {
                    **timestamp_fields,
                    "channel": channel_name,
                    "value": channel.published_value,
                }

                if channel.meaning is not None:
                    channel_payload["meaning"] = channel.meaning
                    channel_state_payload["meaning"] = channel.meaning

                if channel.unit is not None:
                    channel_state_payload["unit"] = channel.unit
                    channel_payload["unit"] = channel.unit

                if channel.semantic_role is not None:
                    channel_state_payload["semantic_role"] = channel.semantic_role
                    channel_payload["semantic_role"] = channel.semantic_role

                if channel.object_type is not None:
                    channel_state_payload["object_type"] = channel.object_type
                    channel_payload["object_type"] = channel.object_type

                _add_derived_values(
                    channel_state_payload,
                    semantic_role=channel.semantic_role,
                    value=channel.value,
                )
                _add_derived_values(
                    channel_payload,
                    semantic_role=channel.semantic_role,
                    value=channel.value,
                )

                aggregate_channels[channel_name] = channel_payload

                for topic_ref in self._topic_resolver.iter_read_topic_refs(device):
                    self._mqtt_client.publish_json(
                        channel_state_topic(
                            self._base_topic,
                            topic_ref,
                            channel_name,
                        ),
                        channel_state_payload,
                        retain=True,
                    )

                    self._mqtt_client.publish_value(
                        channel_value_topic(
                            self._base_topic,
                            topic_ref,
                            channel_name,
                        ),
                        channel.published_value,
                        retain=True,
                    )

        state_payload = self._build_base_state_payload(device)
        state_payload.update(
            {
                "last_update": timestamp_fields["timestamp_local"],
                "channels": aggregate_channels,
            }
        )

        if rorg is not None:
            state_payload["rorg"] = rorg

        if data is not None:
            state_payload["data"] = data

        self._device_states[device_id] = {
            key: value
            for key, value in state_payload.items()
            if value is not None
        }

        self._publish_device_state_payload(
            device=device,
            payload=self._device_states[device_id],
        )

    def _build_base_state_payload(self, device: Device) -> dict[str, Any]:
        """Build the retained base state payload for one device."""

        payload: dict[str, Any] = {
            "device_id": normalize_device_id(device.device_id),
            "device_name": device.device_name,
            "eep": device.eep,
            "profile": device.profile,
            "channels": {},
        }

        if device.sender_id is not None:
            payload["sender_id"] = device.sender_id

        return {
            key: value
            for key, value in payload.items()
            if value is not None
        }

    def _publish_device_state_payload(
        self,
        device: Device,
        payload: dict[str, Any],
    ) -> None:
        for topic_ref in self._topic_resolver.iter_read_topic_refs(device):
            self._mqtt_client.publish_json(
                device_state_topic(
                    self._base_topic,
                    topic_ref,
                ),
                payload,
                retain=True,
            )


def _add_derived_values(
    payload: dict[str, Any],
    *,
    semantic_role: str | None,
    value: Any,
) -> None:
    value_bool = derived_value(
        semantic_role=semantic_role,
        value_name="value_bool",
        value=value,
    )

    if value_bool is not None:
        payload["value_bool"] = value_bool
