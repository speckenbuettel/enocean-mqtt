"""Runtime inventory command handlers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from enocean_mqtt.devices.csv_format import export_csv, import_csv
from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.gateway.publisher import DevicePublisher
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.gateway.unknown_devices import UnknownDeviceRegistry
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.virtual_devices.sender_id_registry import SenderIdRegistry

_TX_CAPABLE_COMMUNICATION = {
    "bidirectional_eep",
    "bidirectional_eep_pair",
}


class RuntimeInventoryCommands:
    """Inventory-related runtime command handlers."""

    def __init__(
        self,
        mqtt_client: MQTTClient,
        base_topic: str,
        status_publisher: GatewayStatusPublisher,
        devices_json_path: str | Path,
        devices_csv_import_path: str | Path,
        devices_csv_export_path: str | Path,
        unknown_devices_csv_path: str | Path,
        unknown_devices_registry: UnknownDeviceRegistry,
        registry_reload_callback: Callable[[DeviceRegistry], None],
        device_publisher: DevicePublisher,
        sender_registry_path: str | Path = "config/sender-id-registry.json",
        sender_registry_base_id: str | None = None,
    ) -> None:
        self._mqtt_client = mqtt_client
        self._base_topic = base_topic.rstrip("/")
        self._status_publisher = status_publisher
        self._devices_json_path = Path(devices_json_path)
        self._devices_csv_import_path = Path(devices_csv_import_path)
        self._devices_csv_export_path = Path(devices_csv_export_path)
        self._unknown_devices_csv_path = Path(unknown_devices_csv_path)
        self._unknown_devices_registry = unknown_devices_registry
        self._registry_reload_callback = registry_reload_callback
        self._device_publisher = device_publisher
        self._sender_registry_path = Path(sender_registry_path)
        self.sender_registry = SenderIdRegistry(
            self._sender_registry_path,
            default_base_id=sender_registry_base_id,
        )

        self.registry = DeviceRegistry.from_json(
            self._devices_json_path
        )

    def device_import(self, payload: dict) -> None:
        """Import or update a single physical device via runtime JSON."""

        raw_device = payload.get("device")

        if not isinstance(raw_device, dict):
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Missing or invalid device payload",
                command="device.import",
            )
            return

        try:
            device = Device(**raw_device)
            device, allocated_sender_id = self._ensure_device_sender_id(device)
        except Exception as exc:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Device validation failed",
                command="device.import",
                error=str(exc),
            )
            return

        operation, imported_device = self.registry.upsert(device)
        self.registry.to_json(self._devices_json_path)
        self._apply_runtime_registry_update(self.registry)
        removed_unknown_devices = self._cleanup_promoted_unknown_devices()
        republished_devices = self._device_publisher.republish_devices(
            self.registry
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Runtime device import completed",
            command="device.import",
            operation=operation,
            device_id=imported_device.device_id,
            device_name=imported_device.device_name,
            alias=imported_device.alias,
            sender_id=imported_device.sender_id,
            allocated_sender_id=allocated_sender_id,
            removed_unknown_devices=removed_unknown_devices,
            republished_devices=republished_devices,
            devices_json=str(self._devices_json_path),
            sender_registry=str(self._sender_registry_path),
        )

    def device_delete(self, payload: dict) -> None:
        """Delete one physical device by device ID."""

        device_id = str(payload.get("device_id", "")).strip().upper()

        if not device_id:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Missing device_id",
                command="device.delete",
            )
            return

        removed_device = self.registry.remove(device_id)

        if removed_device is None:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Device not found",
                command="device.delete",
                device_id=device_id,
            )
            return

        released_sender_id = self._release_emulated_sender_for_device(
            removed_device,
        )
        cleared_topics = self._device_publisher.clear_retained_device_topics(
            removed_device,
        )

        self.registry.to_json(self._devices_json_path)
        self._apply_runtime_registry_update(self.registry)

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Runtime device deleted",
            command="device.delete",
            device_id=removed_device.device_id,
            device_name=removed_device.device_name,
            alias=removed_device.alias,
            sender_id=removed_device.sender_id,
            released_sender_id=released_sender_id,
            cleared_topics=cleared_topics,
            devices_json=str(self._devices_json_path),
            sender_registry=str(self._sender_registry_path),
        )

    def devices_import(self, payload: dict) -> None:
        """Import devices CSV into runtime registry."""

        import_path = self._resolve_import_path(payload)

        if not import_path.exists():
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Devices CSV import file does not exist",
                command="devices.import",
                file=str(import_path),
            )
            return

        if import_path.stat().st_size == 0:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Devices CSV import file is empty",
                command="devices.import",
                file=str(import_path),
            )
            return

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Starting device registry import",
            command="devices.import",
            file=str(import_path),
        )

        registry = import_csv(
            import_path,
            existing_registry=self.registry,
            log_callback=self._log_callback,
        )
        allocated_sender_ids = self._ensure_registry_sender_ids(registry)

        registry.to_json(self._devices_json_path)
        self.registry = registry
        self._apply_runtime_registry_update(registry)
        removed_unknown_devices = self._cleanup_promoted_unknown_devices()
        republished_devices = self._device_publisher.republish_devices(
            self.registry
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Device registry imported and runtime reloaded",
            command="devices.import",
            devices=len(self.registry.devices),
            allocated_sender_ids=allocated_sender_ids,
            removed_unknown_devices=removed_unknown_devices,
            republished_devices=republished_devices,
            import_file=str(import_path),
            devices_json=str(self._devices_json_path),
            sender_registry=str(self._sender_registry_path),
        )

    def devices_reload(self, _payload: dict) -> None:
        """Reload runtime registry from devices.json."""

        old_devices = {
            device.device_id.upper(): device
            for device in self.registry.devices
        }

        registry = DeviceRegistry.from_json(self._devices_json_path)
        allocated_sender_ids = self._ensure_registry_sender_ids(registry)
        new_device_ids = {
            device.device_id.upper()
            for device in registry.devices
        }

        removed_devices = 0

        for device_id, device in old_devices.items():
            if device_id in new_device_ids:
                continue

            self._device_publisher.clear_retained_device_topics(
                device,
            )
            removed_devices += 1

        if allocated_sender_ids:
            registry.to_json(self._devices_json_path)

        self.registry = registry
        self._apply_runtime_registry_update(registry)
        removed_unknown_devices = self._cleanup_promoted_unknown_devices()
        republished_devices = self._device_publisher.republish_devices(
            self.registry
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Runtime registry reloaded from devices.json",
            command="devices.reload",
            devices=len(self.registry.devices),
            allocated_sender_ids=allocated_sender_ids,
            removed_devices=removed_devices,
            removed_unknown_devices=removed_unknown_devices,
            republished_devices=republished_devices,
            file=str(self._devices_json_path),
            sender_registry=str(self._sender_registry_path),
        )

    def devices_export(self, payload: dict) -> None:
        """Export runtime registry to CSV."""

        export_path = self._resolve_export_path(payload)

        if not export_path.parent.exists():
            export_path.parent.mkdir(parents=True, exist_ok=True)

        export_csv(self.registry, export_path)

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Device registry exported",
            command="devices.export",
            devices=len(self.registry.devices),
            file=str(export_path),
        )

    def unknown_devices_export(self, payload: dict) -> None:
        """Export runtime unknown device registry."""

        export_path = self._resolve_unknown_export_path(payload)
        self._unknown_devices_registry.export_csv(export_path)

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Unknown devices CSV exported",
            command="unknown_devices.export",
            file=str(export_path),
            devices=self._unknown_devices_registry.count_devices(),
            telegrams=self._unknown_devices_registry.count_telegrams(),
        )

    def _apply_runtime_registry_update(
        self,
        registry: DeviceRegistry,
    ) -> None:
        self._registry_reload_callback(registry)
        self._status_publisher.set_device_registry_status(
            devices_total=len(registry.devices),
        )

    def _ensure_registry_sender_ids(
        self,
        registry: DeviceRegistry,
    ) -> list[str]:
        allocated_sender_ids: list[str] = []

        for index, device in enumerate(list(registry.devices)):
            updated_device, allocated_sender_id = self._ensure_device_sender_id(
                device,
            )
            registry.devices[index] = updated_device

            if allocated_sender_id is not None:
                allocated_sender_ids.append(allocated_sender_id)

        return allocated_sender_ids

    def _ensure_device_sender_id(
        self,
        device: Device,
    ) -> tuple[Device, str | None]:
        """Ensure TX-capable physical devices have an emulated sender ID."""

        if device.communication not in _TX_CAPABLE_COMMUNICATION:
            return device, None

        sender_id = self.sender_registry.allocate_emulated_sender(
            destination_id=device.device_id,
        )

        if device.sender_id == sender_id:
            return device, None

        return device.model_copy(update={"sender_id": sender_id}), sender_id

    def _release_emulated_sender_for_device(
        self,
        device: Device,
    ) -> str | None:
        """Release the emulated sender allocated for one physical device."""

        destination_id = device.device_id
        released_sender_id = None

        if device.sender_id:
            released_sender_id = self.sender_registry.release_emulated_sender(
                sender_id=device.sender_id,
                destination_id=destination_id,
            )

        if released_sender_id is None:
            released_sender_id = self.sender_registry.release_emulated_sender(
                destination_id=destination_id,
            )

        return released_sender_id

    def _resolve_import_path(self, payload: dict) -> Path:
        import_file = str(payload.get("import_file", "")).strip()

        if not import_file:
            return self._devices_csv_import_path

        return Path(import_file)

    def _resolve_export_path(self, payload: dict) -> Path:
        export_file = str(payload.get("export_file", "")).strip()

        if not export_file:
            return self._devices_csv_export_path

        return Path(export_file)

    def _resolve_unknown_export_path(self, payload: dict) -> Path:
        export_file = str(payload.get("export_file", "")).strip()

        if not export_file:
            return self._unknown_devices_csv_path

        return Path(export_file)

    def _cleanup_promoted_unknown_devices(self) -> int:
        """Remove now-known devices from unknown device registry and MQTT."""

        removed_devices = 0
        unknown_records_by_sender = {
            record.sender_id.strip().upper()
            for record in self._unknown_devices_registry.records()
        }

        for device in self.registry.devices:
            normalized_device_id = device.device_id.strip().upper()

            removed_from_registry = self._unknown_devices_registry.remove(
                normalized_device_id,
            )
            was_retained_unknown = normalized_device_id in unknown_records_by_sender

            if not removed_from_registry and not was_retained_unknown:
                continue

            self._clear_unknown_device_topics(normalized_device_id)
            removed_devices += 1

        return removed_devices

    def _clear_unknown_device_topics(self, sender_id: str) -> None:
        """Clear known historical variants of retained unknown-device topics."""

        normalized_sender_id = sender_id.strip().upper()
        topic_variants = {
            normalized_sender_id,
            normalized_sender_id.lower(),
        }

        for topic_sender_id in topic_variants:
            self._mqtt_client.clear_retained_topic(
                f"{self._base_topic}/busmonitor/unknown_devices/{topic_sender_id}",
            )

    def _log_callback(
        self,
        level: str,
        component: str,
        message: str,
    ) -> None:
        """Forward importer events into runtime logs/errors."""

        if level == "error":
            self._status_publisher.publish_error(
                component=component,
                message=message,
            )
            return

        self._status_publisher.publish_log(
            level=level,
            component=component,
            message=message,
        )
