"""Replay EnOcean capture files to MQTT."""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path
from typing import Any

from enocean_mqtt.devices.gateways import gateway_registry
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.devices.tx_runtime import DeviceTxRuntime
from enocean_mqtt.esp3.interface_manager import ESP3InterfaceManager
from enocean_mqtt.gateway.mqtt_inject import (
    MQTTInjectError,
    parse_injected_telegram,
)
from enocean_mqtt.gateway.orchestrator import GatewayOrchestrator
from enocean_mqtt.gateway.process_control import restart_current_process, shutdown_signals
from enocean_mqtt.gateway.publisher import DevicePublisher
from enocean_mqtt.gateway.runtime_commands import RuntimeCommandHandler
from enocean_mqtt.gateway.runtime_inventory_commands import RuntimeInventoryCommands
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.gateway.unknown_devices import UnknownDeviceRegistry
from enocean_mqtt.logging_config import configure_logging
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.notifications import NotificationService
from enocean_mqtt.replay.controller import ReplayController
from enocean_mqtt.replay.models import ReplayTelegram
from enocean_mqtt.replay.runtime_runner import ReplayRuntimeRunner
from enocean_mqtt.replay.session import ReplaySession
from enocean_mqtt.runtime.state_manager import RuntimeStateManager
from enocean_mqtt.runtime_config import RuntimeConfig, load_runtime_config
from enocean_mqtt.storage.sqlite_store import SQLiteRuntimeStore
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry
from enocean_mqtt.virtual_devices.runtime import VirtualDeviceRuntime
from enocean_mqtt.virtual_devices.runtime_commands import (
    VirtualDeviceRuntimeCommands,
)
from enocean_mqtt.virtual_devices.sender_id_registry import SenderIdRegistry
from enocean_mqtt.web_api.runtime_server import (
    EmbeddedWebAPIServer,
)

DEFAULT_CONFIG_PATH = "config/config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start enocean-mqtt runtime."
    )

    parser.add_argument("capture_file", nargs="?")

    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
    )

    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--limit", type=int)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    replay_session = None

    if args.capture_file:
        replay_session = ReplaySession.from_cli(
            capture_file=args.capture_file,
            interval_seconds=args.interval,
            limit=args.limit,
        )

    runtime_config = load_runtime_config(args.config)
    configure_logging(runtime_config.logging)
    notifications = NotificationService(
        runtime_config.notifications.pushover, runtime_config.application.name,
    )
    notifications.start()
    try:
        with shutdown_signals() as stop_requested:
            restart_requested = _run_gateway(
                runtime_config, replay_session, notifications, stop_requested=stop_requested,
            )
    except Exception:
        notifications.gateway_error("gateway", "Runtime failed. See the gateway log for details.")
        raise
    finally:
        notifications.gateway_stopped()
        notifications.close()
    if restart_requested:
        restart_current_process()


def _run_gateway(
    runtime_config: RuntimeConfig,
    replay_session: ReplaySession | None,
    notifications: NotificationService,
    *,
    stop_requested: threading.Event | None = None,
) -> bool:
    stop_requested = stop_requested if stop_requested is not None else threading.Event()
    replay_controller = ReplayController()
    mqtt_config = runtime_config.mqtt
    runtime_paths = runtime_config.paths
    gateway_config = runtime_config.gateway
    metrics_config = runtime_config.metrics
    sqlite_config = runtime_config.sqlite
    topics_config = runtime_config.topics
    web_api_config = runtime_config.web_api
    interface_configs = runtime_config.configured_interfaces()
    default_tx_base_id = runtime_config.default_tx_base_id()

    base_topic = mqtt_config.base_topic.rstrip("/")

    mqtt_client = MQTTClient(
        host=mqtt_config.host,
        port=mqtt_config.port,
        client_id=mqtt_config.client_id,
        username=mqtt_config.username,
        password_file=mqtt_config.password_file,
        keepalive_seconds=mqtt_config.keepalive_seconds,
        clean_session=mqtt_config.clean_session,
        reconnect_initial_delay_seconds=(
            mqtt_config.reconnect.initial_delay_seconds
        ),
        reconnect_max_delay_seconds=(
            mqtt_config.reconnect.max_delay_seconds
        ),
    )

    status_publisher = GatewayStatusPublisher(
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        source="runtime",
        runtime_mode="live",
        gateway_base_id=default_tx_base_id,
        default_interface=runtime_config.enocean.default_interface,
        enocean_tx_enabled=runtime_config.enocean.tx_enabled,
        sqlite_enabled=sqlite_config.enabled,
        sqlite_database_path=(
            sqlite_config.database_path
        ),
        error_notifier=notifications.gateway_error,
    )

    runtime_state_manager = RuntimeStateManager(
        status_publisher=status_publisher,
        initial_runtime_mode="live",
    )

    sqlite_store = None

    if sqlite_config.enabled:
        sqlite_store = SQLiteRuntimeStore(
            database_path=sqlite_config.database_path,
            max_telegrams=sqlite_config.max_telegrams,
            persist_live=sqlite_config.persist_live,
            persist_replay=sqlite_config.persist_replay,
            foreign_devices_file=Path(runtime_paths.devices_json).parent / "foreign-devices.json",
        )

    initial_registry = DeviceRegistry.from_json(
        runtime_paths.devices_json,
    )

    status_publisher.set_device_registry_status(
        devices_total=len(initial_registry.devices),
    )

    device_publisher = DevicePublisher(
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        device_topic_identifier=topics_config.device_topic_identifier,
        telegram_mean_interval_window_seconds=(
            metrics_config.telegram_mean_interval_window_seconds
        ),
        peak_telegrams_window_seconds=(
            metrics_config.peak_telegrams_window_seconds
        ),
    )

    orchestrator = GatewayOrchestrator(
        registry=initial_registry,
        publisher=device_publisher,
        status_publisher=status_publisher,
        gateways=gateway_registry(Path(runtime_paths.devices_json).parent / "gateways.json"),
    )

    unknown_devices_registry = UnknownDeviceRegistry()

    runtime_inventory = RuntimeInventoryCommands(
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        status_publisher=status_publisher,
        devices_json_path=runtime_paths.devices_json,
        devices_csv_import_path=runtime_paths.devices_csv_import,
        devices_csv_export_path=runtime_paths.devices_csv_export,
        unknown_devices_csv_path=(
            runtime_paths.unknown_devices_csv_export
        ),
        unknown_devices_registry=unknown_devices_registry,
        registry_reload_callback=orchestrator.update_registry,
        device_publisher=device_publisher,
        sender_registry_base_id=default_tx_base_id,
    )

    replay_runtime_runner = ReplayRuntimeRunner(
        replay_controller=replay_controller,
        runtime_state_manager=runtime_state_manager,
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        orchestrator=orchestrator,
        status_publisher=status_publisher,
        unknown_devices_registry=unknown_devices_registry,
        gateway_health_publish_interval_seconds=(
            gateway_config.health_publish_interval_seconds
        ),
        active_device_window_seconds=(
            metrics_config.active_device_window_seconds
        ),
        sqlite_store=sqlite_store,
    )

    def handle_esp3_telegram(telegram: ReplayTelegram) -> None:
        replay_runtime_runner.process_external_telegram(
            telegram
        )

    interface_manager = ESP3InterfaceManager(
        interfaces=interface_configs,
        tx_enabled=runtime_config.enocean.tx_enabled,
        telegram_callback=handle_esp3_telegram,
        status_publisher=status_publisher,
        default_interface=runtime_config.enocean.default_interface,
    )

    radio_sender = interface_manager.default_sender()

    sender_registry = SenderIdRegistry(
        runtime_paths.sender_id_registry,
        default_base_id=default_tx_base_id,
    )

    device_tx_runtime = DeviceTxRuntime(
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        registry_provider=lambda: orchestrator.registry,
        device_topic_identifier=topics_config.device_topic_identifier,
        status_publisher=status_publisher,
        radio_sender=radio_sender,
        manufacturer_id=sender_registry.manufacturer_id,
        tx_event_callback=replay_runtime_runner.record_external_tx_event,
    )

    runtime_commands = RuntimeCommandHandler(
        mqtt_client=mqtt_client,
        status_publisher=status_publisher,
        replay_runtime_runner=replay_runtime_runner,
        orchestrator=orchestrator,
        base_topic=base_topic,
    )

    runtime_commands.register(
        "device.import",
        runtime_inventory.device_import,
        required_fields={
            "device": dict,
        },
    )

    runtime_commands.register(
        "device.delete",
        runtime_inventory.device_delete,
        required_fields={
            "device_id": str,
        },
    )

    runtime_commands.register(
        "device.teach_in",
        lambda payload: device_tx_runtime.teach_in(
            str(payload["device_id"]),
            payload.get("teach_in"),
        ),
        required_fields={
            "device_id": str,
        },
        optional_fields={
            "teach_in": dict,
        },
    )

    runtime_commands.register(
        "devices.import",
        runtime_inventory.devices_import,
    )

    runtime_commands.register(
        "devices.reload",
        runtime_inventory.devices_reload,
    )

    runtime_commands.register(
        "devices.export",
        runtime_inventory.devices_export,
    )

    runtime_commands.register(
        "unknown_devices.export",
        runtime_inventory.unknown_devices_export,
    )

    def handle_interface_status(payload: dict[str, Any]) -> None:
        status_publisher.publish_log(
            level="info",
            component="interface",
            message="EnOcean interface status requested",
            status=interface_manager.status(
                payload.get("interface_id")
            ),
        )

    def handle_interface_connect(payload: dict[str, Any]) -> None:
        interface_manager.connect(
            payload.get("interface_id")
        )

    def handle_interface_disconnect(payload: dict[str, Any]) -> None:
        interface_manager.disconnect(
            payload.get("interface_id")
        )

    def handle_interface_reconnect(payload: dict[str, Any]) -> None:
        interface_manager.reconnect(
            payload.get("interface_id")
        )

    def handle_interface_network_bridge_start(payload: dict[str, Any]) -> None:
        interface_manager.network_bridge_start(
            payload.get("interface_id")
        )

    def handle_interface_network_bridge_stop(payload: dict[str, Any]) -> None:
        interface_manager.network_bridge_stop(
            payload.get("interface_id")
        )

    def handle_interface_network_bridge_restart(payload: dict[str, Any]) -> None:
        interface_manager.network_bridge_restart(
            payload.get("interface_id")
        )

    runtime_commands.register(
        "interface.status",
        handle_interface_status,
        optional_fields={
            "interface_id": str,
        },
    )

    runtime_commands.register(
        "interface.connect",
        handle_interface_connect,
        optional_fields={
            "interface_id": str,
        },
    )

    runtime_commands.register(
        "interface.disconnect",
        handle_interface_disconnect,
        optional_fields={
            "interface_id": str,
        },
    )

    runtime_commands.register(
        "interface.reconnect",
        handle_interface_reconnect,
        optional_fields={
            "interface_id": str,
        },
    )

    runtime_commands.register(
        "interface.network_bridge.start",
        handle_interface_network_bridge_start,
        optional_fields={
            "interface_id": str,
        },
    )

    runtime_commands.register(
        "interface.network_bridge.stop",
        handle_interface_network_bridge_stop,
        optional_fields={
            "interface_id": str,
        },
    )

    runtime_commands.register(
        "interface.network_bridge.restart",
        handle_interface_network_bridge_restart,
        optional_fields={
            "interface_id": str,
        },
    )

    virtual_device_registry = VirtualDeviceRegistry.from_json(
        runtime_paths.virtual_devices_json
    )

    virtual_device_runtime = VirtualDeviceRuntime(
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        registry=virtual_device_registry,
        sqlite_store=sqlite_store,
        radio_sender=radio_sender,
        tx_event_callback=replay_runtime_runner.record_external_tx_event,
    )

    def reload_virtual_device_registry(
        registry: VirtualDeviceRegistry,
    ) -> None:
        virtual_device_runtime.update_registry(registry)

    virtual_device_commands = VirtualDeviceRuntimeCommands(
        status_publisher=status_publisher,
        virtual_devices_json_path=runtime_paths.virtual_devices_json,
        registry_reload_callback=reload_virtual_device_registry,
        mqtt_client=mqtt_client,
        base_topic=base_topic,
        base_id=default_tx_base_id,
    )

    runtime_commands.register(
        "virtual_device.create",
        virtual_device_commands.virtual_device_create,
        required_fields={
            "virtual_device": dict,
        },
    )

    runtime_commands.register(
        "virtual_device.delete",
        virtual_device_commands.virtual_device_delete,
        required_fields={
            "virtual_device_id": str,
        },
    )

    runtime_commands.register(
        "virtual_device.teach_in",
        lambda payload: virtual_device_runtime.teach_in(
            str(payload["virtual_device_id"]),
        ),
        required_fields={
            "virtual_device_id": str,
        },
    )

    mqtt_client.connect()

    if not mqtt_client.wait_for_connection(timeout_seconds=10):
        raise RuntimeError("MQTT connection timeout")

    embedded_web_api = EmbeddedWebAPIServer(
        config=web_api_config,
        device_publisher=device_publisher,
        device_tx_runtime=device_tx_runtime,
        virtual_device_runtime=virtual_device_runtime,
        interface_status_provider=interface_manager.status,
        interface_connect=interface_manager.connect,
        interface_disconnect=interface_manager.disconnect,
        interface_reconnect=interface_manager.reconnect,
        interface_network_bridge_start=interface_manager.network_bridge_start,
        interface_network_bridge_stop=interface_manager.network_bridge_stop,
        interface_network_bridge_restart=interface_manager.network_bridge_restart,
        runtime_command_dispatcher=runtime_commands.execute,
    )

    embedded_web_api.start()
    web_health = embedded_web_api.health_payload()

    status_publisher.set_web_status(
        web_api=web_health["web_api"],
        web_ui=web_health["web_ui"],
    )

    inject_topic = f"{base_topic}/busmonitor/rx/inject"

    def handle_injected_telegram(topic: str, payload: bytes) -> None:
        payload_text = payload.decode("utf-8", errors="replace").strip()

        if not payload_text:
            return

        try:
            injected = parse_injected_telegram(payload_text)
        except MQTTInjectError as exc:
            status_publisher.publish_error(
                component="mqtt-inject",
                message="Invalid injected telegram",
                topic=topic,
                reason=str(exc),
            )
            return

        replay_runtime_runner.process_external_telegram(
            injected.to_replay_telegram()
        )

    mqtt_client.subscribe(
        inject_topic,
        handle_injected_telegram,
        qos=1,
    )

    if mqtt_config.runtime_commands_enabled:
        runtime_commands.start()
    device_tx_runtime.register()
    virtual_device_runtime.register()

    interface_manager.start_enabled()
    interface_manager.refresh_status()

    status_publisher.configure_last_will()
    status_publisher.publish_online()
    status_publisher.publish_runtime_mode()
    status_publisher.publish_version()
    status_publisher.publish_health(
        mqtt_connected=mqtt_client.is_connected(),
    )
    status_publisher.publish_uptime()
    status_publisher.publish_log(
        level="info",
        component="gateway",
        message="Gateway started in live mode",
        runtime_mode="live",
    )

    notifications.gateway_started()
    try:
        if replay_session is not None:
            replay_runtime_runner.run_sync(replay_session, stop_requested=stop_requested)
        else:
            last_health_publish_monotonic = time.monotonic()

            while not runtime_commands.shutdown_requested and not stop_requested.wait(1.0):

                now_monotonic = time.monotonic()

                if (
                    now_monotonic - last_health_publish_monotonic
                    >= gateway_config.health_publish_interval_seconds
                ):
                    interface_manager.refresh_status()
                    status_publisher.publish_health(
                        mqtt_connected=mqtt_client.is_connected(),
                    )

                    status_publisher.publish_uptime()

                    last_health_publish_monotonic = (
                        now_monotonic
                    )
    finally:
        replay_runtime_runner.stop(
            reason="runtime_shutdown",
        )

        embedded_web_api.stop()

        interface_manager.stop_all()
        if sqlite_store is not None:
            sqlite_store.close()

        if mqtt_client.is_connected():
            status_publisher.publish_offline()

        mqtt_client.disconnect()

    return runtime_commands.restart_requested and not stop_requested.is_set()


if __name__ == "__main__":
    main()
