"""Runtime command handling for virtual devices."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from enocean_mqtt.eep.json_registry import load_eep_definition
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.virtual_devices.models import VirtualDevice
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry
from enocean_mqtt.virtual_devices.sender_id_registry import SenderIdRegistry
from enocean_mqtt.virtual_devices.teach_in import (
    determine_teach_in_method,
    generate_teach_in_telegram,
)

RegistryReloadCallback = Callable[[VirtualDeviceRegistry], None]


class VirtualDeviceRuntimeCommands:
    """Virtual-device-related runtime command handlers."""

    def __init__(
        self,
        *,
        status_publisher: GatewayStatusPublisher,
        virtual_devices_json_path: str | Path,
        registry_reload_callback: RegistryReloadCallback,
        mqtt_client: MQTTClient | None = None,
        base_topic: str | None = None,
        sender_registry_path: str | Path = "config/sender-id-registry.json",
        base_id: str | None = None,
    ) -> None:
        self._status_publisher = status_publisher
        self._virtual_devices_json_path = Path(virtual_devices_json_path)
        self._registry_reload_callback = registry_reload_callback
        self._mqtt_client = mqtt_client
        self._base_topic = base_topic.rstrip("/") if base_topic else None
        self.registry = VirtualDeviceRegistry.from_json(
            self._virtual_devices_json_path
        )
        self.sender_registry = SenderIdRegistry(
            sender_registry_path,
            default_base_id=base_id,
        )

    def virtual_device_create(self, payload: dict) -> None:
        """Create or update one virtual device via runtime JSON."""

        raw_device = payload.get("virtual_device")

        if not isinstance(raw_device, dict):
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Missing or invalid virtual_device payload",
                command="virtual_device.create",
            )
            return

        try:
            virtual_device_id = str(
                raw_device["virtual_device_id"]
            ).strip().lower()
            eep, profile = _resolve_virtual_device_profile(raw_device)

            eep_definition = load_eep_definition(profile or eep)
            sender_id = self.sender_registry.allocate_virtual_device(
                virtual_device_id=virtual_device_id,
            )
            teach_in_method = determine_teach_in_method(eep_definition)
            teach_in_telegram = generate_teach_in_telegram(
                sender_id=sender_id,
                eep_definition=eep_definition,
                manufacturer_id=self.sender_registry.manufacturer_id,
            )

            virtual_device_payload = {
                **raw_device,
                "virtual_device_id": virtual_device_id,
                "eep": eep,
                "profile": profile,
                "sender_id": sender_id,
                "teach_in_method": teach_in_method,
                "teach_in_telegram": teach_in_telegram,
            }

            virtual_device = VirtualDevice(**virtual_device_payload)
            self._validate_channels(virtual_device)
        except Exception as exc:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Virtual device validation failed",
                command="virtual_device.create",
                error=str(exc),
            )
            return

        operation, created_device = self.registry.upsert(virtual_device)
        self.registry.to_json(self._virtual_devices_json_path)
        self._registry_reload_callback(self.registry)

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Runtime virtual device create completed",
            command="virtual_device.create",
            operation=operation,
            virtual_device_id=created_device.virtual_device_id,
            sender_id=created_device.sender_id,
            eep=created_device.eep,
            profile=created_device.registry_profile,
            teach_in_method=created_device.teach_in_method,
            channels=created_device.channels,
            virtual_devices_json=str(self._virtual_devices_json_path),
        )

    def virtual_device_delete(self, payload: dict) -> None:
        """Delete one virtual device and release its sender ID."""

        virtual_device_id = str(
            payload.get("virtual_device_id", "")
        ).strip().lower()

        if not virtual_device_id:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Missing virtual_device_id",
                command="virtual_device.delete",
            )
            return

        removed_device = self.registry.delete(virtual_device_id)

        if removed_device is None:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Virtual device not found",
                command="virtual_device.delete",
                virtual_device_id=virtual_device_id,
            )
            return

        released_sender_id = self.sender_registry.release_virtual_device(
            virtual_device_id=virtual_device_id,
        )

        self.registry.to_json(self._virtual_devices_json_path)
        self._registry_reload_callback(self.registry)
        cleared_topics = self._clear_retained_virtual_topics(removed_device)

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Runtime virtual device deleted",
            command="virtual_device.delete",
            virtual_device_id=virtual_device_id,
            sender_id=released_sender_id,
            cleared_topics=cleared_topics,
        )

    def _clear_retained_virtual_topics(
        self,
        removed_device: VirtualDevice,
    ) -> list[str]:
        """Clear retained MQTT topics owned by one virtual device."""

        if self._mqtt_client is None or self._base_topic is None:
            return []

        virtual_device_id = removed_device.virtual_device_id
        topics = [
            f"{self._base_topic}/virtual/{virtual_device_id}/info",
            f"{self._base_topic}/virtual/{virtual_device_id}/state",
        ]

        for channel in removed_device.channels:
            topics.append(
                f"{self._base_topic}/virtual/{virtual_device_id}"
                f"/channel/{channel}/state"
            )

        cleared_topics: list[str] = []

        for topic in topics:
            self._mqtt_client.clear_retained_topic(topic)
            cleared_topics.append(topic)

        return cleared_topics

    def _validate_channels(self, virtual_device: VirtualDevice) -> None:
        """Validate configured channels against canonical EEP registry."""

        eep_definition = load_eep_definition(
            virtual_device.registry_profile
        )
        available_channels = {
            channel.name
            for channel in eep_definition.channels
            if channel.output.mqtt
        }

        missing_channels = sorted(
            set(virtual_device.channels) - available_channels
        )

        if missing_channels:
            raise ValueError(
                "unknown virtual device channels for profile "
                f"{virtual_device.registry_profile}: "
                f"{', '.join(missing_channels)}"
            )


def _resolve_virtual_device_profile(raw_device: dict) -> tuple[str, str | None]:
    """Resolve canonical EEP/profile fields from runtime command payload."""

    raw_eep = raw_device.get("eep")
    raw_profile = raw_device.get("profile")

    eep = str(raw_eep).strip().upper() if raw_eep is not None else ""
    profile = str(raw_profile).strip() if raw_profile is not None else ""

    if not eep and not profile:
        raise ValueError("virtual device requires either eep or profile")

    if not eep:
        eep = profile

    return eep, profile or None
