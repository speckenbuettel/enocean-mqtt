"""Runtime manager for named ESP3 transport interfaces."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from enocean_mqtt.esp3.radio import RadioERP1Telegram
from enocean_mqtt.esp3.ser2net_bridge import Ser2NetBridge, Ser2NetBridgeConfig
from enocean_mqtt.esp3.serial_transport import (
    ESP3SerialTransport,
    SerialLike,
)
from enocean_mqtt.replay.models import ReplayTelegram
from enocean_mqtt.runtime.event import RadioSendResult
from enocean_mqtt.runtime_config import InterfaceTransportConfig

LOGGER = logging.getLogger(__name__)


class InterfaceStatusPublisher(Protocol):
    """Status publisher methods required by the interface manager."""

    def set_enocean_interface_status(
        self,
        *,
        interface_id: str | None = None,
        connected: bool,
        port: str | None,
        base_id: str | None = None,
        tx_enabled: bool = False,
        transport_status: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None: ...

    def publish_log(
        self,
        level: str,
        component: str,
        message: str,
        **details: Any,
    ) -> None: ...


class ESP3InterfaceManager:
    """Own named ESP3 transports and expose runtime control commands."""

    def __init__(
        self,
        *,
        interfaces: list[InterfaceTransportConfig],
        tx_enabled: bool = False,
        telegram_callback: Callable[[ReplayTelegram], None],
        status_publisher: InterfaceStatusPublisher,
        default_interface: str | None = None,
        serial_factory: Callable[..., SerialLike] | None = None,
    ) -> None:
        self._interfaces = {
            interface.interface_id: interface
            for interface in interfaces
        }
        self._tx_enabled = tx_enabled
        self._default_interface = default_interface
        self._telegram_callback = telegram_callback
        self._status_publisher = status_publisher
        self._serial_factory = serial_factory
        self._transports: dict[str, ESP3SerialTransport] = {}
        self._network_bridges: dict[str, Ser2NetBridge] = {}

    @property
    def interface_ids(self) -> list[str]:
        """Return configured interface IDs."""

        return sorted(self._interfaces)

    def start_enabled(self) -> None:
        """Connect all interfaces enabled by configuration."""

        for interface_id, config in self._interfaces.items():
            self._publish_status(interface_id)

            if not config.enabled:
                continue

            self.connect(interface_id)

    def stop_all(self) -> None:
        """Disconnect every running transport."""

        for interface_id in list(self._transports):
            self.disconnect(interface_id)

    def refresh_status(self) -> None:
        """Refresh publisher snapshots with current transport counters."""

        for interface_id in self.interface_ids:
            self._publish_status(interface_id)

    def connect(self, interface_id: str | None = None) -> dict[str, Any]:
        """Connect one interface, or the default if only one is configured."""

        interface_id = self._resolve_interface_id(interface_id)
        config = self._interfaces[interface_id]

        self.network_bridge_stop(interface_id)

        transport = self._transports.get(interface_id)

        if transport is not None and transport.is_running:
            return self.status(interface_id)

        transport = ESP3SerialTransport(
            interface_id=config.interface_id,
            port=config.device,
            baudrate=config.baudrate,
            base_id=config.base_id,
            timeout_seconds=config.timeout_seconds,
            reconnect_enabled=config.reconnect.enabled,
            reconnect_initial_delay_seconds=config.reconnect.initial_delay_seconds,
            reconnect_max_delay_seconds=config.reconnect.max_delay_seconds,
            serial_factory=self._serial_factory,
        )
        self._transports[interface_id] = transport
        transport.start(self._telegram_callback)

        time.sleep(0.05)
        self._publish_status(interface_id)
        self._status_publisher.publish_log(
            level="info",
            component="interface",
            message="EnOcean interface connect requested",
            interface_id=interface_id,
            port=config.device,
        )

        return self.status(interface_id)

    def disconnect(self, interface_id: str | None = None) -> dict[str, Any]:
        """Disconnect one interface, or the default if only one is configured."""

        interface_id = self._resolve_interface_id(interface_id)
        transport = self._transports.get(interface_id)

        if transport is not None:
            transport.stop()

        self._publish_status(interface_id)
        self._status_publisher.publish_log(
            level="info",
            component="interface",
            message="EnOcean interface disconnected",
            interface_id=interface_id,
        )

        return self.status(interface_id)

    def reconnect(self, interface_id: str | None = None) -> dict[str, Any]:
        """Disconnect and connect one interface."""

        interface_id = self._resolve_interface_id(interface_id)
        self.disconnect(interface_id)
        return self.connect(interface_id)

    def network_bridge_start(
        self,
        interface_id: str | None = None,
    ) -> dict[str, Any]:
        """Switch one interface from enocean-mqtt to ser2net."""

        interface_id = self._resolve_interface_id(interface_id)
        config = self._interfaces[interface_id]

        if not config.network_bridge.enabled:
            raise RuntimeError(
                f"Network bridge is disabled for interface: {interface_id}"
            )

        bridge = self._network_bridges.get(interface_id)

        if bridge is None:
            bridge = Ser2NetBridge(
                Ser2NetBridgeConfig(
                    interface_id=interface_id,
                    serial_device=config.device,
                    baudrate=config.baudrate,
                    host=config.network_bridge.host,
                    port=config.network_bridge.port,
                    ser2net_binary=config.network_bridge.ser2net_binary,
                )
            )
            self._network_bridges[interface_id] = bridge

        bridge.ensure_available()
        self.disconnect(interface_id)
        bridge.start()
        self._publish_status(interface_id)
        self._status_publisher.publish_log(
            level="info",
            component="interface",
            message="EnOcean interface network bridge started",
            interface_id=interface_id,
            host=config.network_bridge.host,
            port=config.network_bridge.port,
            serial_device=config.device,
        )

        return self.status(interface_id)

    def network_bridge_stop(
        self,
        interface_id: str | None = None,
    ) -> dict[str, Any]:
        """Stop a running ser2net bridge for one interface."""

        interface_id = self._resolve_interface_id(interface_id)
        bridge = self._network_bridges.get(interface_id)

        if bridge is not None:
            bridge.stop()

        self._publish_status(interface_id)
        self._status_publisher.publish_log(
            level="info",
            component="interface",
            message="EnOcean interface network bridge stopped",
            interface_id=interface_id,
        )

        return self.status(interface_id)

    def network_bridge_restart(
        self,
        interface_id: str | None = None,
    ) -> dict[str, Any]:
        """Restart the ser2net network bridge for one interface."""

        interface_id = self._resolve_interface_id(interface_id)
        self.network_bridge_stop(interface_id)
        return self.network_bridge_start(interface_id)

    def status(self, interface_id: str | None = None) -> dict[str, Any]:
        """Return status for one interface or all interfaces."""

        if interface_id is None:
            return {
                "interfaces": [
                    self.status(configured_interface_id)
                    for configured_interface_id in self.interface_ids
                ]
            }

        config = self._interfaces.get(interface_id)

        if config is None:
            raise KeyError(f"Unknown EnOcean interface: {interface_id}")

        transport = self._transports.get(interface_id)

        if transport is None:
            return {
                "interface_id": interface_id,
                "enabled": config.enabled,
                "transport": config.type,
                "port": config.device,
                "base_id": config.base_id,
                "connected": False,
                "status": "configured",
                "metrics": {},
                "network_bridge": self._network_bridge_status(interface_id),
            }

        transport_status = transport.get_status()

        return {
            "interface_id": interface_id,
            "enabled": config.enabled,
            "transport": transport_status.get("transport", config.type),
            "port": transport_status.get("port", config.device),
            "base_id": transport_status.get("base_id", config.base_id),
            "connected": bool(transport_status.get("connected")),
            "status": transport_status.get("status"),
            "last_error": transport_status.get("last_error"),
            "metrics": transport_status.get("metrics", {}),
            "network_bridge": self._network_bridge_status(interface_id),
        }

    def default_sender(
        self,
    ) -> Callable[[RadioERP1Telegram], RadioSendResult] | None:
        """Return a radio sender bound to the configured default interface."""

        if self._default_interface is None:
            return None

        def send(telegram: RadioERP1Telegram) -> RadioSendResult:
            interface_id = self._default_sender_interface_id()
            config = self._interfaces[interface_id]

            if not self._tx_enabled or not config.enabled or not config.tx_enabled:
                return RadioSendResult(interface_id, "disabled")

            transport = self._transports.get(interface_id)

            if transport is None:
                return RadioSendResult(
                    interface_id,
                    "failed",
                    f"EnOcean interface is not connected: {interface_id}",
                )

            try:
                transport.send(telegram)
            except Exception as exc:
                return RadioSendResult(interface_id, "failed", str(exc))

            return RadioSendResult(interface_id, "accepted")

        return send

    def _default_sender_interface_id(self) -> str:
        if (
            self._default_interface is not None
            and self._default_interface in self._interfaces
        ):
            return self._default_interface

        raise RuntimeError("No default EnOcean interface is configured")

    def _resolve_interface_id(self, interface_id: str | None) -> str:
        if interface_id:
            if interface_id not in self._interfaces:
                raise KeyError(f"Unknown EnOcean interface: {interface_id}")

            return interface_id

        if len(self._interfaces) == 1:
            return next(iter(self._interfaces))

        raise KeyError("interface_id is required when multiple interfaces exist")

    def _publish_status(self, interface_id: str) -> None:
        status = self.status(interface_id)
        self._status_publisher.set_enocean_interface_status(
            interface_id=interface_id,
            connected=bool(status.get("connected")),
            port=str(status.get("port")) if status.get("port") else None,
            base_id=str(status.get("base_id")) if status.get("base_id") else None,
            tx_enabled=self._interfaces[interface_id].tx_enabled,
            transport_status=(
                str(status.get("status")) if status.get("status") else None
            ),
            metrics=dict(status.get("metrics", {})),
        )


    def _network_bridge_status(self, interface_id: str) -> dict[str, Any]:
        config = self._interfaces[interface_id].network_bridge
        bridge = self._network_bridges.get(interface_id)

        if bridge is not None:
            return bridge.status()

        return {
            "enabled": config.enabled,
            "running": False,
            "host": config.host,
            "port": config.port,
            "serial_device": self._interfaces[interface_id].device,
            "baudrate": self._interfaces[interface_id].baudrate,
            "ser2net_binary": config.ser2net_binary,
            "last_error": None,
        }
