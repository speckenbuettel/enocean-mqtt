"""Web UI routes and dashboard summary endpoint."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from enocean_mqtt.devices.foreign_registry import foreign_registry
from enocean_mqtt.eep.decoder import EEPDecodeError
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.runtime_decoder import decode_runtime_with_definition
from enocean_mqtt.runtime.service import RuntimeService

_UI_PAGES = {
    "/": ("dashboard.html", "dashboard"),
    "/busmonitor": ("busmonitor.html", "busmonitor"),
    "/devices-ui": ("devices.html", "devices"),
    "/runtime-ui": ("runtime.html", "runtime"),
    "/metrics-ui": ("metrics.html", "metrics"),
    "/logs-ui": ("logs.html", "logs"),
    "/configuration-ui": ("configuration.html", "configuration"),
    "/documentation-ui": ("documentation.html", "documentation"),
}


def _busmonitor_asset_versions() -> dict[str, str]:
    """Invalidate browser caches when a busmonitor asset's contents change."""
    static = Path(__file__).parent / "static"
    paths = (
        "css/busmonitor.css",
        "js/busmonitor.js",
        "js/busmonitor-controls.js",
        "js/busmonitor-tooltips.js",
    )
    return {
        path: hashlib.sha256((static / path).read_bytes()).hexdigest()[:16]
        for path in paths
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _dictionary(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


_JOURNAL_LEVELS = {
    "0": "EMERGENCY",
    "1": "ALERT",
    "2": "CRITICAL",
    "3": "ERROR",
    "4": "WARNING",
    "5": "NOTICE",
    "6": "INFO",
    "7": "DEBUG",
}
_TEXT_LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) "
    r"(?P<level>[A-Z]+) (?P<logger>[^:]+): (?P<message>.*)$"
)


def _journal_entries(
    *,
    limit: int = 200,
    level: str | None = None,
    search: str | None = None,
    since_start: bool = False,
) -> dict[str, Any]:
    """Read normalized entries from the service's persistent system journal."""

    requested_limit = max(1, min(limit, 1000))
    command = [
        "journalctl",
        "--unit",
        "enocean-mqtt.service",
        "--no-pager",
        "--output=json",
        "--reverse",
        f"--lines={requested_limit * 4}",
    ]
    if since_start:
        # Web API and gateway share this service process. No journal is deleted.
        started = datetime.fromtimestamp(psutil.Process().create_time(), tz=UTC)
        command.append(f"--since={started.strftime('%Y-%m-%d %H:%M:%S.%f UTC')}")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "entries": [], "error": str(exc)}

    if result.returncode != 0:
        return {
            "available": False,
            "entries": [],
            "error": result.stderr.strip() or "journalctl failed",
        }

    level_filter = (level or "").strip().upper()
    search_filter = (search or "").strip().casefold()
    entries: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue

        message = str(raw.get("MESSAGE") or "")
        parsed_message: dict[str, Any] = {}
        if message.startswith("{"):
            try:
                candidate = json.loads(message)
                if isinstance(candidate, dict):
                    parsed_message = candidate
            except json.JSONDecodeError:
                pass
        else:
            text_match = _TEXT_LOG_PATTERN.match(message)
            if text_match is not None:
                parsed_message = text_match.groupdict()

        resolved_level = str(
            parsed_message.get("level")
            or _JOURNAL_LEVELS.get(str(raw.get("PRIORITY")), "INFO")
        ).upper()
        logger_name = str(
            parsed_message.get("logger")
            or raw.get("SYSLOG_IDENTIFIER")
            or raw.get("_COMM")
            or "enocean-mqtt"
        )
        resolved_message = str(parsed_message.get("message") or message)
        exception = parsed_message.get("exception")
        if exception:
            resolved_message = f"{resolved_message}\n{exception}"
        timestamp = parsed_message.get("timestamp")
        if timestamp is None:
            try:
                timestamp = datetime.fromtimestamp(
                    int(str(raw.get("__REALTIME_TIMESTAMP"))) / 1_000_000,
                    tz=UTC,
                ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            except (TypeError, ValueError):
                timestamp = None

        searchable = f"{resolved_level} {logger_name} {resolved_message}".casefold()
        if level_filter and resolved_level != level_filter:
            continue
        if search_filter and search_filter not in searchable:
            continue

        entries.append(
            {
                "timestamp": timestamp,
                "level": resolved_level,
                "logger": logger_name,
                "message": resolved_message,
            }
        )
        if len(entries) >= requested_limit:
            break

    return {"available": True, "entries": entries, "error": None}


def _system_metrics(project_root: Path) -> dict[str, Any]:
    """Return lightweight host and current-process utilization metrics."""

    process = psutil.Process()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(project_root))
    load_average = None
    try:
        load_average = list(psutil.getloadavg())
    except (AttributeError, OSError):
        pass
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(),
        "load_average": load_average,
        "memory_total_bytes": memory.total,
        "memory_available_bytes": memory.available,
        "memory_percent": memory.percent,
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "disk_percent": disk.percent,
        "process_cpu_percent": process.cpu_percent(interval=None),
        "process_threads": process.num_threads(),
        "process_open_files": len(process.open_files()),
        "host_uptime_seconds": max(
            0,
            int(datetime.now(tz=UTC).timestamp() - psutil.boot_time()),
        ),
    }


def _configured_enocean_directions(
    config: dict[str, Any],
    interface_id: str | None = None,
) -> dict[str, bool]:
    """Return configured RX and effective TX state for an interface."""

    enocean = _dictionary(config.get("enocean"))
    interfaces = enocean.get("interfaces")
    configured = interfaces if isinstance(interfaces, list) else []
    selected = [
        item
        for item in configured
        if isinstance(item, dict)
        and (interface_id is None or item.get("interface_id") == interface_id)
    ]
    rx_enabled = any(item.get("enabled") is True for item in selected)
    tx_enabled = bool(enocean.get("tx_enabled")) and any(
        item.get("enabled") is True and item.get("tx_enabled") is True
        for item in selected
    )
    return {"rx_enabled": rx_enabled, "tx_enabled": tx_enabled}


def _dashboard_interfaces(
    interfaces: Any,
    aggregate: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project named interface snapshots for dashboard selection."""

    projected: list[dict[str, Any]] = []
    if isinstance(interfaces, dict):
        interface_items = sorted(interfaces.items())
    elif isinstance(interfaces, list):
        interface_items = [
            (str(value.get("interface_id") or ""), value)
            for value in interfaces
            if isinstance(value, dict)
        ]
    else:
        interface_items = []

    for interface_id, value in interface_items:
        payload = _dictionary(value)
        resolved_id = str(payload.get("interface_id") or interface_id)
        projected.append(
            {
                "interface_id": resolved_id,
                "connected": bool(payload.get("connected")),
                "base_id": payload.get("base_id"),
                "transport_status": payload.get("transport_status"),
                **_configured_enocean_directions(config, resolved_id),
            }
        )

    if not projected and aggregate.get("interface_id"):
        projected.append(
            {
                "interface_id": aggregate.get("interface_id"),
                "connected": bool(aggregate.get("connected")),
                "base_id": aggregate.get("base_id"),
                "transport_status": aggregate.get("transport_status"),
                **_configured_enocean_directions(
                    config,
                    str(aggregate.get("interface_id")),
                ),
            }
        )
    return projected


def _sqlite_summary(database_path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "available": database_path.exists(),
        "records": 0,
        "last_write_unix": None,
        "oldest_telegram_unix": None,
        "last_rx": None,
    }

    if not database_path.exists():
        return summary

    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS count,
                    MIN(timestamp_unix) AS oldest,
                    MAX(timestamp_unix) AS latest
                FROM telegrams
                """
            ).fetchone()
            if row is not None:
                summary["records"] = int(row["count"] or 0)
                summary["last_write_unix"] = row["latest"]
                summary["oldest_telegram_unix"] = row["oldest"]
            last_rx = connection.execute(
                """
                SELECT raw_telegram, rorg, sender_id, data, erp1_status
                FROM telegrams
                WHERE direction = 'rx'
                ORDER BY timestamp_unix DESC, telegram_id DESC
                LIMIT 1
                """
            ).fetchone()
            if last_rx is not None:
                summary["last_rx"] = {
                    key: _hex_text(last_rx[key])
                    for key in last_rx.keys()
                }
    except sqlite3.Error:
        summary["available"] = False

    return summary


def _hex_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex().upper()
    text = str(value).replace(" ", "").strip()
    return text.upper() or None


def _devices_by_sender(runtime_service: RuntimeService) -> dict[str, dict[str, Any]]:
    devices = runtime_service.get_devices().get("devices", [])
    if not isinstance(devices, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for device in devices:
        if not isinstance(device, dict):
            continue
        for key in ("sender_id", "device_id"):
            identifier = _hex_text(device.get(key))
            if identifier is not None:
                indexed[identifier] = device
    return indexed


def _last_rx_activity(
    sqlite_summary: dict[str, Any],
    devices_by_sender: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    telegram = _dictionary(sqlite_summary.get("last_rx"))
    sender_id = _hex_text(telegram.get("sender_id"))
    device = devices_by_sender.get(sender_id or "", {})
    sender_name = device.get("device_name") or device.get("alias") or "unknown"
    decoded_tooltip = "Decode unavailable"
    profile = device.get("profile") or device.get("eep")
    data = telegram.get("data")

    if profile and data:
        try:
            definition = load_eep_definition(str(profile))
            decoded = decode_runtime_with_definition(
                eep_definition=definition,
                payload_hex=str(data),
                status_hex=telegram.get("erp1_status"),
                telegram_id=None,
                rorg=telegram.get("rorg"),
                external_context={
                    "direction": "rx",
                    "sender_id": sender_id,
                    "rorg": telegram.get("rorg"),
                },
            )
            lines = []
            for channel_name, channel in decoded.values.items():
                suffix = f" {channel.unit}" if channel.unit else ""
                lines.append(f"{channel_name}: {channel.value}{suffix}")
            decoded_tooltip = "\n".join(lines) or "No decoded channels"
        except (EEPDecodeError, EEPRegistryError, ValueError) as exc:
            decoded_tooltip = f"Decode unavailable: {exc}"

    return {
        "raw_telegram": telegram.get("raw_telegram"),
        "decoded_tooltip": decoded_tooltip,
        "sender_id": sender_id,
        "sender_name": str(sender_name),
    }


def _device_counts(runtime_service: RuntimeService) -> tuple[int, int]:
    payload = runtime_service.get_devices()
    devices = payload.get("devices", [])
    if not isinstance(devices, list):
        return 0, 0

    physical = 0
    virtual = 0
    for device in devices:
        if not isinstance(device, dict):
            continue
        if device.get("enabled") is False:
            continue

        source_type = str(device.get("source_type") or "")
        if source_type == "virtual_device":
            virtual += 1
        elif source_type == "physical_device":
            physical += 1

    return physical, virtual


def _per_minute(metrics: dict[str, Any], direction: str) -> float:
    direction_metrics = metrics.get(direction)
    if not isinstance(direction_metrics, dict):
        return 0.0
    value = direction_metrics.get("telegrams_per_minute", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _overall_health(
    *,
    online: bool,
    runtime_mode: str,
    mqtt_connected: bool,
    enocean_connected: bool,
    api_enabled: bool,
    api_operational: bool,
    sqlite_enabled: bool,
    sqlite_operational: bool,
) -> dict[str, Any]:
    """Derive the documented dashboard health without hiding its inputs."""

    checks = [
        {
            "label": "Gateway",
            "state": "ok" if online else "problem",
            "value": "online" if online else "offline",
        },
#        {
#            "label": "Runtime mode",
#            "state": "ok" if runtime_mode == "live" else "warn",
#            "value": runtime_mode,
#        },
        {
            "label": "API",
            "state": (
                "ignored"
                if not api_enabled
                else ("ok" if api_operational else "warn")
            ),
            "value": (
                "disabled"
                if not api_enabled
                else ("operational" if api_operational else "unavailable")
            ),
        },
        {
            "label": "EnOcean",
            "state": "ok" if enocean_connected else "problem",
            "value": "connected" if enocean_connected else "disconnected",
        },
        {
            "label": "MQTT",
            "state": "ok" if mqtt_connected else "warn",
            "value": "connected" if mqtt_connected else "disconnected",
        },
        {
            "label": "SQLite",
            "state": (
                "ignored"
                if not sqlite_enabled
                else ("ok" if sqlite_operational else "warn")
            ),
            "value": (
                "disabled"
                if not sqlite_enabled
                else ("operational" if sqlite_operational else "unavailable")
            ),
        },
    ]
    if any(check["state"] == "problem" for check in checks):
        level, label = "problem", "System unavailable"
    elif any(check["state"] == "warn" for check in checks):
        level, label = "warn", "System unhealthy"
    else:
        level, label = "ok", "System healthy"
    return {"level": level, "label": label, "checks": checks}


def install_ui_routes(
    app: FastAPI,
    templates: Jinja2Templates,
    *,
    config_file: Path,
    sqlite_database: Path,
    project_root: Path,
    runtime_service_provider: Callable[[], RuntimeService],
    gateway_runtime_provider: Callable[[], dict[str, Any] | None],
) -> None:
    replaced_paths = {
        *_UI_PAGES,
        "/api/v1/ui/dashboard",
        "/api/v1/ui/system",
        "/api/v1/ui/system/logs",
    }
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) not in replaced_paths
    ]

    def make_handler(
        template_name: str,
        active_page: str,
    ) -> Callable[[Request], Any]:
        def handler(request: Request) -> Any:
            context: dict[str, Any] = {"active_page": active_page}
            shared_styles = Path(__file__).parent / "static/css/web-ui.css"
            context["shared_styles_version"] = (
                hashlib.sha256(shared_styles.read_bytes()).hexdigest()[:16]
            )
            if active_page == "busmonitor":
                context["asset_versions"] = _busmonitor_asset_versions()
            elif active_page == "dashboard":
                script = Path(__file__).parent / "static/js/dashboard.js"
                context["dashboard_script_version"] = (
                    hashlib.sha256(script.read_bytes()).hexdigest()[:16]
                )
            elif active_page == "runtime":
                script = Path(__file__).parent / "static/js/runtime.js"
                context["runtime_script_version"] = (
                    hashlib.sha256(script.read_bytes()).hexdigest()[:16]
                )
            return templates.TemplateResponse(
                request=request,
                name=template_name,
                context=context,
            )

        return handler

    for path, (template_name, active_page) in _UI_PAGES.items():
        app.add_api_route(
            path,
            make_handler(template_name, active_page),
            methods=["GET"],
            include_in_schema=False,
        )

    def dashboard_summary(request: Request) -> dict[str, Any]:
        config = _read_json(config_file)
        directions = _configured_enocean_directions(config)
        runtime_service = runtime_service_provider()
        fallback_physical, virtual_devices = _device_counts(runtime_service)
        sqlite = _sqlite_summary(sqlite_database)
        devices_by_sender = _devices_by_sender(runtime_service)
        runtime: dict[str, Any] = gateway_runtime_provider() or {}
        health = _dictionary(runtime.get("health"))
        metrics = _dictionary(runtime.get("metrics"))
        last_rx = _last_rx_activity(
            {"last_rx": metrics.get("last_rx") or sqlite.get("last_rx")},
            devices_by_sender,
        )

        mqtt = _dictionary(health.get("mqtt"))
        enocean_health = _dictionary(health.get("enocean"))
        enocean = _dictionary(health.get("enocean_interface"))
        if enocean_health:
            health_interfaces = enocean_health.get("interfaces")
            default_interface = enocean_health.get("default_interface")
            if isinstance(health_interfaces, list):
                enocean = next(
                    (
                        item
                        for item in health_interfaces
                        if isinstance(item, dict)
                        and item.get("interface_id") == default_interface
                    ),
                    next(
                        (item for item in health_interfaces if isinstance(item, dict)),
                        {},
                    ),
                )
        runtime_sqlite = _dictionary(health.get("sqlite"))
        registry = _dictionary(health.get("device_registry"))
        web_api = _dictionary(health.get("web_api"))
        web_ui = _dictionary(health.get("web_ui"))
        interfaces = enocean_health.get(
            "interfaces",
            health.get("enocean_interfaces", {}),
        )
        dashboard_interfaces = _dashboard_interfaces(
            interfaces,
            enocean,
            config,
        )
        metric_devices = _dictionary(metrics.get("devices"))
        decoder = _dictionary(metrics.get("decoder"))
        rx = _dictionary(metrics.get("rx"))
        tx = _dictionary(metrics.get("tx"))

        physical_devices = int(
            registry.get(
                "devices_total",
                metric_devices.get("known_devices_total", fallback_physical),
            )
            or 0
        )
        unknown_devices = int(metric_devices.get("unknown_devices_total", 0) or 0)
        runtime_mode = str(runtime.get("runtime_mode") or "unknown")
        online = runtime.get("status") == "online"
        mqtt_connected = bool(mqtt.get("connected"))
        enocean_connected = bool(
            enocean_health.get("connected", enocean.get("connected"))
        )
        api_enabled = bool(web_api.get("enabled"))
        api_operational = bool(web_api.get("operational"))
        sqlite_enabled = bool(runtime_sqlite.get("enabled"))
        sqlite_operational = bool(runtime_sqlite.get("operational"))
        sqlite_config = _dictionary(config.get("sqlite"))

        return {
            "runtime_commands": {
                "authorized": "admin" in request.state.web_roles,
            },
            "overall_health": _overall_health(
                online=online,
                runtime_mode=runtime_mode,
                mqtt_connected=mqtt_connected,
                enocean_connected=enocean_connected,
                api_enabled=api_enabled,
                api_operational=api_operational,
                sqlite_enabled=sqlite_enabled,
                sqlite_operational=sqlite_operational,
            ),
            "system": {
                "status": "running" if online else "offline",
                "version": runtime.get("version", "unknown"),
                "uptime_seconds": runtime.get("uptime_seconds", 0),
                "runtime_mode": runtime_mode,
                "memory_rss_mb": health.get("memory_rss_mb"),
                "api_enabled": api_enabled,
                "api_operational": api_operational,
                "web_ui_enabled": bool(web_ui.get("enabled")),
                "web_ui_operational": bool(web_ui.get("operational")),
            },
            "enocean": {
                "status": "connected" if enocean_connected else "disconnected",
                "interface_id": enocean.get("interface_id"),
                "transport_status": enocean.get("transport_status"),
                "base_id": enocean.get("base_id"),
                "interfaces_total": len(dashboard_interfaces),
                "interfaces": dashboard_interfaces,
                "metrics": enocean.get("metrics", {}),
                **directions,
            },
            "mqtt": {
                "status": "connected" if mqtt_connected else "disconnected",
                "host": mqtt.get("host"),
                "port": mqtt.get("port"),
                "reconnects": mqtt.get("reconnects", 0),
                "uptime_seconds": mqtt.get("uptime_seconds", 0),
                "message_load": _dictionary(
                    mqtt.get("message_load_15mins", mqtt.get("message_load"))
                ),
            },
            "sqlite": {
                **sqlite,
                "enabled": sqlite_enabled,
                "operational": sqlite_operational,
                "database_size_bytes": runtime_sqlite.get("database_size_bytes"),
                "max_telegrams": sqlite_config.get("max_telegrams", 0),
            },
            "metrics": {
                "rx_per_minute": _per_minute(metrics, "rx"),
                "tx_per_minute": _per_minute(metrics, "tx"),
                "rx_total": rx.get("telegrams_total", 0),
                "tx_total": tx.get("telegrams_total", 0),
                "decoded_total": decoder.get("decoded_telegrams_total", 0),
                "decode_errors_total": decoder.get("decode_errors_total", 0),
                "active_devices_total": metric_devices.get("active_devices_total", 0),
                "last_sender_id": metrics.get("last_sender_id"),
                "last_sender_name": devices_by_sender.get(
                    _hex_text(metrics.get("last_sender_id")) or "",
                    {},
                ).get("device_name")
                or devices_by_sender.get(
                    _hex_text(metrics.get("last_sender_id")) or "",
                    {},
                ).get("alias")
                or "unknown",
                "last_raw_rx": last_rx.get("raw_telegram"),
                "last_raw_rx_decoded": last_rx.get("decoded_tooltip"),
            },
            "device_registry": {
                "physical": physical_devices,
                "virtual": virtual_devices,
                "unknown": unknown_devices,
                "foreign": len(
                    foreign_registry(config_file.parent / "foreign-devices.json").snapshot()
                ),
                "total": physical_devices + virtual_devices,
                "last_reload": registry.get("last_reload"),
            },
        }

    app.add_api_route(
        "/api/v1/ui/dashboard",
        dashboard_summary,
        methods=["GET"],
        include_in_schema=False,
    )

    def system_summary() -> dict[str, Any]:
        config = _read_json(config_file)
        runtime: dict[str, Any] = gateway_runtime_provider() or {}
        health = _dictionary(runtime.get("health"))
        return {
            "status": runtime.get("status", "offline"),
            "version": runtime.get("version", "unknown"),
            "uptime_seconds": runtime.get("uptime_seconds", 0),
            "runtime_mode": runtime.get("runtime_mode", "unknown"),
            "health": health,
            "system_metrics": _system_metrics(project_root),
            "logging": {
                **_dictionary(health.get("logging")),
                "format": _dictionary(config.get("logging")).get("format", "text"),
                "destination": "systemd journal (stderr)",
                "service": "enocean-mqtt.service",
            },
        }

    def system_logs(
        limit: int = 200,
        level: str | None = None,
        search: str | None = None,
        since_start: bool = False,
    ) -> dict[str, Any]:
        return _journal_entries(limit=limit, level=level, search=search, since_start=since_start)

    app.add_api_route(
        "/api/v1/ui/system",
        system_summary,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/api/v1/ui/system/logs",
        system_logs,
        methods=["GET"],
        include_in_schema=False,
    )
