"""Gateway runtime status and health publishing."""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from time import time
from typing import Any

import psutil

from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.time import build_timestamp_fields
from enocean_mqtt.version import load_project_version


class GatewayStatusPublisher:
    """Publish runtime status, health and metrics MQTT topics."""

    def __init__(
        self,
        mqtt_client: MQTTClient,
        base_topic: str,
        source: str,
        runtime_mode: str = "unknown",
        gateway_base_id: str | None = None,
        default_interface: str | None = None,
        enocean_tx_enabled: bool = False,
        sqlite_enabled: bool = False,
        sqlite_database_path: str | None = None,
        error_notifier: Callable[[str, str], None] | None = None,
    ) -> None:
        self._mqtt_client = mqtt_client
        self._error_notifier = error_notifier
        self._base_topic = base_topic.rstrip("/")
        self._source = source
        self._startup_time = time()
        self._mqtt_connected_since = time()
        self._mqtt_reconnects = 0
        self._runtime_mode = runtime_mode
        self._gateway_base_id = gateway_base_id
        self._default_interface = default_interface
        self._enocean_tx_enabled = enocean_tx_enabled
        self._sqlite_enabled = sqlite_enabled
        self._sqlite_database_path = sqlite_database_path
        self._sqlite_operational = sqlite_enabled
        self._web_api_payload: dict[str, Any] = {
            "enabled": False,
            "operational": False,
            "host": None,
            "port": None,
        }
        self._web_ui_payload: dict[str, Any] = {
            "enabled": False,
            "operational": False,
            "route": "/",
            "static_assets": False,
        }
        self._enocean_interface_payload: dict[str, Any] = {
            "connected": False,
            "port": None,
            "base_id": gateway_base_id,
        }
        self._enocean_interfaces_payload: dict[str, dict[str, Any]] = {}
        self._last_busmonitor_metrics_payload: dict[str, Any] | None = None
        self._last_gateway_metrics_payload: dict[str, Any] | None = None
        self._device_registry_last_reload = str(
            build_timestamp_fields()["timestamp_local"]
        )
        self._device_registry_devices_total = 0

        self.status_topic = f"{self._base_topic}/gateway/status"
        self.runtime_mode_topic = (
            f"{self._base_topic}/gateway/runtime_mode"
        )
        self.health_topic = f"{self._base_topic}/gateway/health"
        self.enocean_topic = f"{self._base_topic}/gateway/enocean"
        self.metrics_topic = f"{self._base_topic}/gateway/metrics"
        self.busmonitor_metrics_topic = (
            f"{self._base_topic}/busmonitor/metrics"
        )
        self.uptime_topic = f"{self._base_topic}/gateway/uptime"
        self.version_topic = f"{self._base_topic}/gateway/version"
        self.log_topic = f"{self._base_topic}/gateway/log"
        self.error_topic = f"{self._base_topic}/gateway/error"
        self.command_topic = f"{self._base_topic}/gateway/command"

    def set_device_registry_status(
        self,
        devices_total: int,
    ) -> None:
        """Update device registry status fields for health payloads."""

        self._device_registry_last_reload = str(
            build_timestamp_fields()["timestamp_local"]
        )
        self._device_registry_devices_total = devices_total

    def set_web_status(
        self,
        *,
        web_api: dict[str, Any],
        web_ui: dict[str, Any],
    ) -> None:
        """Update Web API/UI status fields for health payloads."""

        self._web_api_payload = {
            "enabled": bool(web_api.get("enabled")),
            "operational": bool(web_api.get("operational")),
            "host": web_api.get("host"),
            "port": web_api.get("port"),
        }
        self._web_ui_payload = {
            "enabled": bool(web_ui.get("enabled")),
            "operational": bool(web_ui.get("operational")),
            "route": web_ui.get("route", "/"),
            "static_assets": bool(web_ui.get("static_assets")),
        }

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
    ) -> None:
        """Update physical EnOcean interface status fields."""

        self._enocean_interface_payload = {
            "interface_id": interface_id,
            "connected": connected,
            "port": port,
            "base_id": base_id or self._gateway_base_id,
            "tx_enabled": tx_enabled,
            "transport_status": transport_status,
            "metrics": metrics or {},
        }

        if interface_id is not None:
            self._enocean_interfaces_payload[interface_id] = dict(
                self._enocean_interface_payload
            )

    def set_runtime_mode(self, runtime_mode: str) -> None:
        """Update active runtime mode."""

        self._runtime_mode = runtime_mode

        if self._mqtt_client.is_connected():
            self.publish_runtime_mode()
            self.publish_health(
                mqtt_connected=True,
            )

    @staticmethod
    def build_timestamp_fields() -> dict[str, float | str]:
        return build_timestamp_fields()

    @staticmethod
    def load_version() -> str:
        return load_project_version()

    @staticmethod
    def memory_rss_mb() -> float | None:
        process = psutil.Process(os.getpid())

        rss_mb = float(
            process.memory_info().rss
        ) / 1024 / 1024

        return round(rss_mb, 1)

    def uptime_seconds(self) -> int:
        return int(time() - self._startup_time)

    def mqtt_uptime_seconds(self) -> int:
        return int(time() - self._mqtt_connected_since)

    def mqtt_message_load(self, window_seconds: int = 15 * 60) -> dict[str, int]:
        """Return rolling MQTT message counts, including safe test fallbacks."""

        message_load = getattr(self._mqtt_client, "message_load", None)
        if callable(message_load):
            return dict(message_load(window_seconds))
        return {
            "window_seconds": window_seconds,
            "published": 0,
            "received": 0,
        }

    def sqlite_database_size_bytes(self) -> int | None:
        if not self._sqlite_enabled:
            return None

        if not self._sqlite_database_path:
            return None

        database_path = Path(self._sqlite_database_path)

        if not database_path.exists():
            return None

        return database_path.stat().st_size

    def configure_last_will(self) -> None:
        self._mqtt_client.configure_last_will(
            topic=self.status_topic,
            payload="offline",
            retain=True,
            qos=1,
        )

    def publish_online(self) -> None:
        self._mqtt_connected_since = time()

        self._mqtt_client.publish_value(
            self.status_topic,
            "online",
            retain=True,
            qos=1,
        )

    def publish_offline(self) -> None:
        self._mqtt_client.publish_value(
            self.status_topic,
            "offline",
            retain=True,
            qos=1,
        )

    def publish_runtime_mode(self) -> None:
        self._mqtt_client.publish_value(
            self.runtime_mode_topic,
            self._runtime_mode,
            retain=True,
            qos=1,
        )

    def publish_version(self) -> None:
        self._mqtt_client.publish_value(
            self.version_topic,
            self.load_version(),
            retain=True,
        )

    def publish_uptime(self) -> None:
        self._mqtt_client.publish_value(
            self.uptime_topic,
            self.uptime_seconds(),
            retain=True,
        )

    def enocean_state(self) -> str:
        """Return lightweight EnOcean interface state."""

        if self._enocean_interface_payload.get("connected"):
            return "connected"

        if any(
            payload.get("connected")
            for payload in self._enocean_interfaces_payload.values()
        ):
            return "connected"

        return "disconnected"

    def publish_enocean(self) -> None:
        """Publish physical EnOcean gateway/interface state."""

        self._mqtt_client.publish_value(
            self.enocean_topic,
            self.enocean_state(),
            retain=True,
        )

    def publish_health(self, mqtt_connected: bool) -> None:
        message_load = self.mqtt_message_load(15 * 60)
        payload: dict[str, Any] = {
            **self.build_timestamp_fields(),
            "online": mqtt_connected,
            "version": self.load_version(),
            "uptime_seconds": self.uptime_seconds(),
            "memory_rss_mb": self.memory_rss_mb(),
            "runtime_mode": self._runtime_mode,
            "mqtt": {
                "connected": mqtt_connected,
                "host": getattr(self._mqtt_client, "host", None),
                "port": getattr(self._mqtt_client, "port", None),
                "client_id": getattr(self._mqtt_client, "client_id", None),
                "reconnects": getattr(
                    self._mqtt_client,
                    "reconnects",
                    self._mqtt_reconnects,
                ),
                "uptime_seconds": self.mqtt_uptime_seconds(),
                "message_load_15mins": {
                    "published": message_load["published"],
                    "received": message_load["received"],
                },
            },
            "enocean": {
                "connected": self.enocean_state() == "connected",
                "tx_enabled": self._enocean_tx_enabled,
                "default_interface": self._default_interface,
                "interfaces": [
                    {
                        "interface_id": interface.get("interface_id"),
                        "connected": bool(interface.get("connected")),
                        "tx_enabled": bool(interface.get("tx_enabled")),
                        "port": interface.get("port"),
                        "base_id": interface.get("base_id"),
                        "metrics": interface.get("metrics", {}),
                    }
                    for interface in self._enocean_interfaces_payload.values()
                ],
            },
            "sqlite": {
                "enabled": self._sqlite_enabled,
                "operational": self._sqlite_operational,
                "database_size_bytes": (
                    self.sqlite_database_size_bytes()
                ),
            },
            "device_registry": {
                "last_reload": self._device_registry_last_reload,
                "devices_total": self._device_registry_devices_total,
            },
            "web_api": self._web_api_payload,
            "web_ui": self._web_ui_payload,
            "logging": {
                "level": logging.getLevelName(
                    logging.getLogger().getEffectiveLevel()
                )
            },
        }

        self._mqtt_client.publish_json(
            self.health_topic,
            payload,
            retain=True,
        )

        self.publish_enocean()

    def publish_metrics(
        self,
        statistics: dict[str, Any] | Counter[str],
        unknown_devices: int,
        telegrams_per_minute: float,
    ) -> None:
        """Publish runtime statistics and metrics."""

        rx_payload = {
            "telegrams_total": statistics.get(
                "rx_telegrams_total",
                statistics.get("telegrams_total", 0),
            ),
            "telegrams_per_minute": round(
                telegrams_per_minute,
                2,
            ),
            "peak_telegrams_per_minute": round(
                statistics.get(
                    "peak_telegrams_per_minute",
                    telegrams_per_minute,
                ),
                2,
            ),
            "repeated_telegrams_total": statistics.get(
                "repeated_telegrams_total",
                0,
            ),
            "telegram_mean_interval_seconds": statistics.get(
                "telegram_mean_interval_seconds",
                0,
            ),
        }

        rx_total = rx_payload["telegrams_total"]
        for category in ("original", "repeated", "unclassified"):
            count = statistics.get(f"{category}_telegrams_total", 0)
            rx_payload[f"{category}_telegrams"] = {
                "telegrams_total": count,
                "telegrams_per_minute": round(
                    telegrams_per_minute * count / rx_total if rx_total else 0.0, 2
                ),
            }

        tx_payload = {
            "telegrams_total": statistics.get(
                "tx_telegrams_total",
                0,
            ),
            "telegrams_per_minute": round(
                statistics.get(
                    "tx_telegrams_per_minute",
                    0.0,
                ),
                2,
            ),
            "telegram_mean_interval_seconds": statistics.get(
                "tx_telegram_mean_interval_seconds",
                0,
            ),
        }

        decoder_payload = {
            "decoded_telegrams_total": statistics.get(
                "decoded_telegrams",
                0,
            ),
            "decode_errors_total": statistics.get(
                "decode_errors",
                0,
            ),
        }

        busmonitor_payload: dict[str, Any] = {
            "rx": rx_payload,
            "tx": tx_payload,
            "decoder": decoder_payload,
            "rorg": statistics.get(
                "rorg_metrics",
                {},
            ),
            "unknown_devices": {
                "devices_total": unknown_devices,
                "telegrams_total": statistics.get(
                    "unknown_device_telegrams",
                    0,
                ),
                "rorg": statistics.get(
                    "unknown_rorg_metrics",
                    {},
                ),
            },
            "last_rorg": statistics.get("last_rorg"),
            "last_sender_id": statistics.get(
                "last_sender_id",
            ),
            "last_rx": statistics.get("last_rx"),
        }

        gateway_payload: dict[str, Any] = {
            "rx": {
                "telegrams_total": rx_payload["telegrams_total"],
                "telegrams_per_minute": rx_payload["telegrams_per_minute"],
                "telegram_mean_interval_seconds": rx_payload[
                    "telegram_mean_interval_seconds"
                ],
            },
            "tx": {
                "telegrams_total": tx_payload["telegrams_total"],
                "telegrams_per_minute": tx_payload["telegrams_per_minute"],
            },
            "decoder": decoder_payload,
            "devices": {
                "known_devices_total": self._device_registry_devices_total,
                "unknown_devices_total": unknown_devices,
                "active_devices_total": statistics.get(
                    "active_devices_total",
                    0,
                ),
            },
            "last_sender_id": statistics.get(
                "last_sender_id",
            ),
            "last_rx": statistics.get("last_rx"),
        }

        self._last_busmonitor_metrics_payload = busmonitor_payload
        self._last_gateway_metrics_payload = gateway_payload

        self._mqtt_client.publish_json(
            self.busmonitor_metrics_topic,
            busmonitor_payload,
            retain=True,
        )

        self._mqtt_client.publish_json(
            self.metrics_topic,
            gateway_payload,
            retain=True,
        )

    def republish_gateway_topics(self, mqtt_connected: bool) -> None:
        """Republish retained gateway/runtime topics."""

        self.publish_online()
        self.publish_runtime_mode()
        self.publish_version()
        self.publish_health(mqtt_connected=mqtt_connected)
        self.publish_enocean()
        self.publish_uptime()

        if self._last_busmonitor_metrics_payload is not None:
            self._mqtt_client.publish_json(
                self.busmonitor_metrics_topic,
                self._last_busmonitor_metrics_payload,
                retain=True,
            )

        if self._last_gateway_metrics_payload is not None:
            self._mqtt_client.publish_json(
                self.metrics_topic,
                self._last_gateway_metrics_payload,
                retain=True,
            )

    def publish_status(
        self,
        statistics: dict[str, Any] | Counter[str],
        mqtt_connected: bool,
        unknown_devices: int,
        telegrams_per_minute: float,
    ) -> None:
        """Compatibility wrapper for legacy callers."""

        self.publish_runtime_mode()
        self.publish_health(mqtt_connected=mqtt_connected)
        self.publish_metrics(
            statistics=statistics,
            unknown_devices=unknown_devices,
            telegrams_per_minute=telegrams_per_minute,
        )
        self.publish_uptime()

    def publish_log(
        self,
        level: str,
        component: str,
        message: str,
        **details: Any,
    ) -> None:
        payload: dict[str, Any] = {
            **self.build_timestamp_fields(),
            "level": level,
            "component": component,
            "message": message,
        }

        if details:
            payload["details"] = details

        self._mqtt_client.publish_json(
            self.log_topic,
            payload,
            retain=False,
        )

    def publish_error(
        self,
        component: str,
        message: str,
        **details: Any,
    ) -> None:
        if self._error_notifier is not None:
            self._error_notifier(component, message)
        payload: dict[str, Any] = {
            **self.build_timestamp_fields(),
            "level": "error",
            "component": component,
            "message": message,
        }

        if details:
            payload["details"] = details

        self._mqtt_client.publish_json(
            self.error_topic,
            payload,
            retain=False,
        )
