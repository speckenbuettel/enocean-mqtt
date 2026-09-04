"""REST projection of gateway runtime status already published through MQTT."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from enocean_mqtt.gateway.status import GatewayStatusPublisher

GatewayStatusProvider = Callable[[], GatewayStatusPublisher]


def _mqtt_connected(status: GatewayStatusPublisher) -> bool:
    client = status._mqtt_client  # In-process projection of the runtime publisher.
    try:
        return bool(client.is_connected())
    except Exception:
        return False


def _health_payload(status: GatewayStatusPublisher) -> dict[str, Any]:
    mqtt_connected = _mqtt_connected(status)
    enocean_connected = status.enocean_state() == "connected"

    return {
        **status.build_timestamp_fields(),
        "online": mqtt_connected,
        "version": status.load_version(),
        "uptime_seconds": status.uptime_seconds(),
        "memory_rss_mb": status.memory_rss_mb(),
        "runtime_mode": status._runtime_mode,
        "mqtt": {
            "connected": mqtt_connected,
            "host": getattr(status._mqtt_client, "host", None),
            "port": getattr(status._mqtt_client, "port", None),
            "client_id": getattr(status._mqtt_client, "client_id", None),
            "reconnects": getattr(
                status._mqtt_client,
                "reconnects",
                status._mqtt_reconnects,
            ),
            "uptime_seconds": status.mqtt_uptime_seconds(),
            "message_load_15mins": {
                key: value
                for key, value in status.mqtt_message_load().items()
                if key in {"published", "received"}
            },
        },
        "enocean": {
            "connected": enocean_connected,
            "tx_enabled": status._enocean_tx_enabled,
            "default_interface": status._default_interface,
            "interfaces": [
                {
                    "interface_id": interface.get("interface_id"),
                    "connected": bool(interface.get("connected")),
                    "tx_enabled": bool(interface.get("tx_enabled")),
                    "port": interface.get("port"),
                    "base_id": interface.get("base_id"),
                    "metrics": interface.get("metrics", {}),
                }
                for interface in status._enocean_interfaces_payload.values()
            ],
        },
        "sqlite": {
            "enabled": status._sqlite_enabled,
            "operational": status._sqlite_operational,
            "database_size_bytes": status.sqlite_database_size_bytes(),
        },
        "device_registry": {
            "last_reload": status._device_registry_last_reload,
            "devices_total": status._device_registry_devices_total,
        },
        "web_api": dict(status._web_api_payload),
        "web_ui": dict(status._web_ui_payload),
        "logging": {
            "level": logging.getLevelName(logging.getLogger().getEffectiveLevel())
        },
    }


def gateway_runtime_snapshot(status: GatewayStatusPublisher) -> dict[str, Any]:
    """Return all retained-style gateway runtime state in one API payload."""

    health = _health_payload(status)
    gateway_metrics = dict(status._last_gateway_metrics_payload or {})
    busmonitor_metrics = dict(status._last_busmonitor_metrics_payload or {})

    return {
        "status": "online" if health["online"] else "offline",
        "version": status.load_version(),
        "uptime_seconds": status.uptime_seconds(),
        "runtime_mode": status._runtime_mode,
        "enocean": status.enocean_state(),
        "health": health,
        "metrics": gateway_metrics,
        "busmonitor_metrics": busmonitor_metrics,
    }


def create_gateway_status_router(
    status_provider: GatewayStatusProvider,
) -> APIRouter:
    """Create API routes mirroring current gateway MQTT status topics."""

    router = APIRouter(prefix="/api/v1/gateway", tags=["gateway"])

    def status() -> GatewayStatusPublisher:
        return status_provider()

    @router.get("/status")
    def get_status() -> dict[str, str]:
        snapshot = gateway_runtime_snapshot(status())
        return {"status": str(snapshot["status"])}

    @router.get("/version")
    def get_version() -> dict[str, str]:
        return {"version": status().load_version()}

    @router.get("/uptime")
    def get_uptime() -> dict[str, int]:
        return {"uptime_seconds": status().uptime_seconds()}

    @router.get("/runtime-mode")
    def get_runtime_mode() -> dict[str, str]:
        return {"runtime_mode": str(status()._runtime_mode)}

    @router.get("/enocean")
    def get_enocean() -> dict[str, Any]:
        current = status()
        return {
            "state": current.enocean_state(),
            "interface": dict(current._enocean_interface_payload),
            "interfaces": dict(current._enocean_interfaces_payload),
        }

    @router.get("/health")
    def get_health() -> dict[str, Any]:
        return _health_payload(status())

    @router.get("/metrics")
    def get_metrics() -> dict[str, Any]:
        return dict(status()._last_gateway_metrics_payload or {})

    @router.get("/runtime")
    def get_runtime() -> dict[str, Any]:
        return gateway_runtime_snapshot(status())

    @router.get("/busmonitor-metrics")
    def get_busmonitor_metrics() -> dict[str, Any]:
        return dict(status()._last_busmonitor_metrics_payload or {})

    return router
