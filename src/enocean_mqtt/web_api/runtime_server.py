"""Embedded Web API runtime server."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import uvicorn

from enocean_mqtt.devices.projection import ApiDeviceRegistry
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.runtime.service import RuntimeService
from enocean_mqtt.runtime_config import WebAPIConfig
from enocean_mqtt.web_api.app import (
    CONFIG_FILE,
    DEVICES_FILE,
    PROJECT_ROOT,
    SQLITE_DATABASE,
    STATIC_DIRECTORY,
    TEMPLATE_DIRECTORY,
    VIRTUAL_DEVICES_FILE,
    app,
    configure_api_authentication,
    configure_runtime_command_dispatcher,
    get_datapoint_registry,
    get_latest_device_states,
    templates,
)
from enocean_mqtt.web_api.gateway_status_routes import (
    create_gateway_status_router,
    gateway_runtime_snapshot,
)
from enocean_mqtt.web_api.live_events import (
    configure_live_event_queue,
    request_live_event_shutdown,
)
from enocean_mqtt.web_api.runtime_controls import configure_interface_controls
from enocean_mqtt.web_api.semantic_routes import create_semantic_router
from enocean_mqtt.web_api.telegram_activity_routes import create_telegram_activity_router
from enocean_mqtt.web_api.ui_routes import install_ui_routes
from enocean_mqtt.web_api.web_auth import install_web_authentication

logger = logging.getLogger(__name__)

InterfaceControl = Callable[[str | None], dict[str, Any]]
RuntimeCommandDispatcher = Callable[
    [str, dict[str, Any] | None],
    dict[str, Any],
]

_SEMANTIC_ROUTE_PREFIXES = (
    "/api/v1/devices",
    "/api/v1/datapoints",
)
_GATEWAY_STATUS_ROUTE_PATHS = {
    "/api/v1/gateway/status",
    "/api/v1/gateway/version",
    "/api/v1/gateway/uptime",
    "/api/v1/gateway/runtime-mode",
    "/api/v1/gateway/enocean",
    "/api/v1/gateway/health",
    "/api/v1/gateway/adapter-status",
    "/api/v1/gateway/adapter-status/stream",
    "/api/v1/gateway/metrics",
    "/api/v1/gateway/runtime",
    "/api/v1/gateway/busmonitor-metrics",
}
_TELEGRAM_ACTIVITY_ROUTE_PATHS = {
    "/api/v1/busmonitor/metrics/telegram-activity",
}


def _process_log_level() -> int:
    """Return the configured process log level for Uvicorn's own loggers."""

    return logging.getLogger().getEffectiveLevel()


class EmbeddedWebAPIServer:
    """Embedded FastAPI/uvicorn runtime service."""

    def __init__(
        self,
        config: WebAPIConfig,
        *,
        device_publisher: Any | None = None,
        device_tx_runtime: Any | None = None,
        virtual_device_runtime: Any | None = None,
        interface_status_provider: InterfaceControl | None = None,
        interface_connect: InterfaceControl | None = None,
        interface_disconnect: InterfaceControl | None = None,
        interface_reconnect: InterfaceControl | None = None,
        interface_network_bridge_start: InterfaceControl | None = None,
        interface_network_bridge_stop: InterfaceControl | None = None,
        interface_network_bridge_restart: InterfaceControl | None = None,
        runtime_command_dispatcher: RuntimeCommandDispatcher | None = None,
    ) -> None:
        self.config = config
        self.device_publisher = device_publisher
        self.device_tx_runtime = device_tx_runtime
        self.virtual_device_runtime = virtual_device_runtime
        self._interface_status_provider = interface_status_provider
        self._interface_connect = interface_connect
        self._interface_disconnect = interface_disconnect
        self._interface_reconnect = interface_reconnect
        self._interface_network_bridge_start = interface_network_bridge_start
        self._interface_network_bridge_stop = interface_network_bridge_stop
        self._interface_network_bridge_restart = interface_network_bridge_restart
        self._runtime_command_dispatcher = runtime_command_dispatcher
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

    def start(self) -> None:
        """Start the embedded Web API in a background thread."""

        if not self.config.enabled:
            logger.debug("Embedded Web API disabled")
            return

        configure_live_event_queue(
            max_queue_size=self.config.sse.max_queue_size,
        )
        configure_api_authentication(
            enabled=self.config.authentication.enabled,
            token_file=self.config.authentication.token_file,
        )
        configure_interface_controls(
            status_provider=self._interface_status_provider,
            connect=self._interface_connect,
            disconnect=self._interface_disconnect,
            reconnect=self._interface_reconnect,
            network_bridge_start=self._interface_network_bridge_start,
            network_bridge_stop=self._interface_network_bridge_stop,
            network_bridge_restart=self._interface_network_bridge_restart,
        )
        configure_runtime_command_dispatcher(
            self._runtime_command_dispatcher,
        )
        self._configure_runtime_state_provider()
        self._configure_gateway_status_routes()
        self._configure_telegram_activity_routes()
        install_ui_routes(
            app,
            templates,
            config_file=CONFIG_FILE,
            sqlite_database=SQLITE_DATABASE,
            project_root=PROJECT_ROOT,
            runtime_service_provider=self._runtime_service,
            gateway_runtime_provider=self._gateway_runtime_snapshot,
        )
        install_web_authentication(
            app,
            templates,
            enabled=self.config.authentication.enabled,
            token_file=self.config.authentication.token_file,
        )

        uvicorn_config = uvicorn.Config(
            app=app,
            host=self.config.host,
            port=self.config.port,
            reload=self.config.reload,
            log_level=_process_log_level(),
        )

        self._server = uvicorn.Server(uvicorn_config)

        self._thread = threading.Thread(
            target=self._server.run,
            name="enocean-web-api",
            daemon=True,
        )

        self._thread.start()

        logger.info(
            "Embedded Web API started on %s:%s",
            self.config.host,
            self.config.port,
        )

    def _runtime_service(self) -> RuntimeService:
        datapoints = get_datapoint_registry()
        return RuntimeService(
            datapoint_registry=datapoints,
            api_device_registry=ApiDeviceRegistry.from_config_files(
                devices_file=DEVICES_FILE,
                virtual_devices_file=VIRTUAL_DEVICES_FILE,
                datapoint_registry=datapoints,
            ),
            device_publisher=self.device_publisher,
            virtual_device_runtime=self.virtual_device_runtime,
            device_tx_runtime=self.device_tx_runtime,
            virtual_device_writer=self.virtual_device_runtime,
            fallback_device_states_provider=get_latest_device_states,
            fallback_source="sqlite_latest_telegram",
        )

    def _configure_runtime_state_provider(self) -> None:
        """Wire semantic API routes to the live runtime state providers."""

        app.router.routes = [
            route
            for route in app.router.routes
            if not any(
                getattr(route, "path", "").startswith(prefix)
                for prefix in _SEMANTIC_ROUTE_PREFIXES
            )
        ]
        app.include_router(create_semantic_router(self._runtime_service))

    def _gateway_status_publisher(self) -> GatewayStatusPublisher | None:
        """Resolve the shared status publisher from the runtime dispatcher."""

        dispatcher_owner = getattr(self._runtime_command_dispatcher, "__self__", None)
        publisher = getattr(dispatcher_owner, "_status_publisher", None)
        return publisher if isinstance(publisher, GatewayStatusPublisher) else None

    def _configure_gateway_status_routes(self) -> None:
        """Expose the same live gateway state that is published through MQTT."""

        if self._gateway_status_publisher() is None:
            logger.warning("Gateway status publisher unavailable for Web API")
            return

        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) not in _GATEWAY_STATUS_ROUTE_PATHS
        ]
        app.include_router(
            create_gateway_status_router(
                lambda: self._gateway_status_publisher_required()
            )
        )

    def _configure_telegram_activity_routes(self) -> None:
        """Expose server-side aggregated telegram activity for Metrics."""

        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) not in _TELEGRAM_ACTIVITY_ROUTE_PATHS
        ]
        app.include_router(
            create_telegram_activity_router(
                database_path=SQLITE_DATABASE,
                devices_file=DEVICES_FILE,
            )
        )

    def _gateway_status_publisher_required(self) -> GatewayStatusPublisher:
        publisher = self._gateway_status_publisher()
        if publisher is None:
            raise RuntimeError("Gateway status publisher is not available")
        return publisher

    def _gateway_runtime_snapshot(self) -> dict[str, Any] | None:
        publisher = self._gateway_status_publisher()
        if publisher is None:
            return None
        return gateway_runtime_snapshot(publisher)

    def health_payload(self) -> dict[str, dict[str, object]]:
        """Return Web API and Web UI health payload fragments."""

        static_assets = self._static_assets_available()
        web_api_operational = (
            self.config.enabled
            and self._thread is not None
            and self._thread.is_alive()
        )

        return {
            "web_api": {
                "enabled": self.config.enabled,
                "operational": web_api_operational,
                "host": self.config.host,
                "port": self.config.port,
            },
            "web_ui": {
                "enabled": self.config.enabled,
                "operational": self.config.enabled and static_assets,
                "route": "/",
                "static_assets": static_assets,
            },
        }

    @staticmethod
    def _static_assets_available() -> bool:
        """Return whether required Web UI assets are present."""

        required_paths = (
            TEMPLATE_DIRECTORY / "dashboard.html",
            TEMPLATE_DIRECTORY / "busmonitor.html",
            TEMPLATE_DIRECTORY / "login.html",
            STATIC_DIRECTORY / "js" / "dashboard.js",
            STATIC_DIRECTORY / "js" / "busmonitor.js",
            STATIC_DIRECTORY / "css" / "dashboard.css",
            STATIC_DIRECTORY / "css" / "busmonitor.css",
            STATIC_DIRECTORY / "css" / "web-ui.css",
            STATIC_DIRECTORY / "css" / "login.css",
        )

        return all(path.exists() for path in required_paths)

    def stop(self) -> None:
        """Stop the embedded Web API server."""

        request_live_event_shutdown()
        configure_interface_controls(
            status_provider=None,
            connect=None,
            disconnect=None,
            reconnect=None,
        )
        configure_runtime_command_dispatcher(None)

        if self._server is not None:
            self._server.should_exit = True

        if self._thread is not None:
            self._thread.join(timeout=5.0)
