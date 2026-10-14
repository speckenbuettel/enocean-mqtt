"""MQTT runtime command handling."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from enocean_mqtt.eep.json_registry import EEPRegistryError, reload_eep_definitions
from enocean_mqtt.gateway.orchestrator import GatewayOrchestrator
from enocean_mqtt.gateway.runtime_schema import (
    RuntimeArgumentType,
    RuntimeCommandDefinition,
    RuntimeCommandValidationError,
    RuntimeCommandValidator,
)
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.replay.runtime_runner import ReplayRuntimeRunner
from enocean_mqtt.replay.session import ReplaySession

CommandHandler = Callable[[dict[str, Any]], None]
logger = logging.getLogger(__name__)


class RuntimeCommandExecutionError(Exception):
    """Structured runtime command execution error."""

    def __init__(
        self,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)

        self.message = message
        self.details = details


class RuntimeCommandHandler:
    """Handle MQTT runtime commands."""

    def __init__(
        self,
        mqtt_client: MQTTClient,
        status_publisher: GatewayStatusPublisher,
        replay_runtime_runner: ReplayRuntimeRunner,
        orchestrator: GatewayOrchestrator,
        base_topic: str,
    ) -> None:
        self._mqtt_client = mqtt_client
        self._status_publisher = status_publisher
        self._replay_runtime_runner = replay_runtime_runner
        self._orchestrator = orchestrator
        self._command_topic = (
            f"{base_topic.rstrip('/')}/gateway/command"
        )

        self._handlers: dict[str, CommandHandler] = {}

        self._validator = RuntimeCommandValidator()

        self.shutdown_requested = False
        self.restart_requested = False

        self.register("eeps.reload", self._handle_eeps_reload)

        self.register(
            "gateway.stop",
            self._handle_gateway_exit,
        )

        self.register(
            "gateway.exit",
            self._handle_gateway_exit,
        )

        self.register(
            "gateway.restart",
            self._handle_gateway_restart,
        )

        self.register(
            "gateway.republish",
            self._handle_gateway_republish,
        )

        self.register(
            "devices.republish",
            self._handle_devices_republish,
        )

        self.register(
            "replay.start",
            self._handle_replay_start,
            required_fields={
                "capture_file": str,
            },
            optional_fields={
                "interval_seconds": (int, float),
                "limit": int,
            },
        )

        self.register(
            "replay.stop",
            self._handle_replay_stop,
        )

        self._validator.register(
            RuntimeCommandDefinition(
                name="devices.import",
                optional_fields={
                    "import_file": str,
                },
            )
        )

        self._validator.register(
            RuntimeCommandDefinition(
                name="devices.reload",
            )
        )

        self._validator.register(
            RuntimeCommandDefinition(
                name="devices.export",
                optional_fields={
                    "export_file": str,
                },
            )
        )

        self._validator.register(
            RuntimeCommandDefinition(
                name="unknown_devices.export",
                optional_fields={
                    "export_file": str,
                },
            )
        )

        self._validator.register(
            RuntimeCommandDefinition(
                name="device.import",
                required_fields={
                    "device": dict,
                },
            )
        )

    def register(
        self,
        command: str,
        handler: CommandHandler,
        *,
        required_fields: dict[str, RuntimeArgumentType] | None = None,
        optional_fields: dict[str, RuntimeArgumentType] | None = None,
    ) -> None:
        """Register runtime command handler and validation schema."""

        self._handlers[command] = handler

        existing_definition = self._validator._definitions.get(command)

        effective_required_fields = (
            required_fields
            if required_fields is not None
            else (
                existing_definition.required_fields
                if existing_definition is not None
                else {}
            )
        )
        effective_optional_fields = (
            optional_fields
            if optional_fields is not None
            else (
                existing_definition.optional_fields
                if existing_definition is not None
                else {}
            )
        )

        self._validator.register(
            RuntimeCommandDefinition(
                name=command,
                required_fields=effective_required_fields,
                optional_fields=effective_optional_fields,
            )
        )

    def start(self) -> None:
        """Subscribe to runtime command topic."""

        self._mqtt_client.subscribe(
            self._command_topic,
            self._on_command,
            qos=1,
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Runtime command listener started",
            topic=self._command_topic,
        )

    def execute(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one validated runtime command."""

        command_payload = dict(payload or {})
        command_payload["command"] = command

        self._validator.validate(
            command,
            command_payload,
        )

        handler = self._handlers.get(command)

        if handler is None:
            raise RuntimeCommandValidationError(
                "unknown_command",
                "Unknown runtime command",
                command=command,
            )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Executing runtime command",
            command=command,
        )

        try:
            handler(command_payload)
        except Exception as exc:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Runtime command execution failed",
                error=str(exc),
                command=command,
            )
            raise RuntimeCommandExecutionError(
                "Runtime command execution failed",
                command=command,
                error=str(exc),
            ) from exc

        return {
            "status": "accepted",
            "command": command,
        }

    def _handle_eeps_reload(self, _payload: dict[str, Any]) -> None:
        try:
            profiles = reload_eep_definitions()
        except EEPRegistryError as exc:
            logger.error("EEP cache reload rejected; previous cache retained: %s", exc)
            raise
        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="EEP cache validated and reloaded",
            command="eeps.reload",
            profiles_total=len(profiles),
            profiles=profiles,
        )

    def _handle_gateway_exit(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Request graceful runtime shutdown."""

        command = payload.get(
            "command",
            "gateway.exit",
        )

        self.shutdown_requested = True

        self._replay_runtime_runner.stop(
            reason="gateway_shutdown_requested",
        )

        if command == "gateway.stop":
            self._status_publisher.publish_log(
                level="warning",
                component="runtime-command",
                message="Deprecated runtime command used",
                command="gateway.stop",
                replacement="gateway.exit",
            )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Gateway runtime exit requested",
            command=command,
        )

    def _handle_gateway_restart(
        self,
        _payload: dict[str, Any],
    ) -> None:
        """Request runtime restart via supervisor/systemd."""

        self.restart_requested = True
        self.shutdown_requested = True

        self._replay_runtime_runner.stop(
            reason="gateway_restart_requested",
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Gateway runtime restart requested",
        )

    def _handle_gateway_republish(
        self,
        _payload: dict[str, Any],
    ) -> None:
        """Republish retained gateway/runtime topics."""

        self._status_publisher.republish_gateway_topics(
            mqtt_connected=self._mqtt_client.is_connected(),
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Gateway retained topics republished",
        )

    def _handle_devices_republish(
        self,
        _payload: dict[str, Any],
    ) -> None:
        """Republish retained device topics."""

        device_count = (
            self._orchestrator
            ._publisher
            .republish_devices(
                self._orchestrator.registry
            )
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Device retained topics republished",
            devices_total=device_count,
        )

    def _handle_replay_start(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Start replay runtime session."""

        runtime_mode = (
            self._replay_runtime_runner
            ._runtime_state_manager
            .runtime_mode
        )

        if runtime_mode != "live":
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Invalid runtime state transition",
                command="replay.start",
                runtime_mode=runtime_mode,
            )
            return

        capture_file = str(
            payload["capture_file"]
        ).strip()

        interval_seconds = float(
            payload.get("interval_seconds", 1.0)
        )

        limit = payload.get("limit")

        session = ReplaySession(
            capture_file=capture_file,
            interval_seconds=interval_seconds,
            limit=limit,
        )

        self._replay_runtime_runner.start_async(session)

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Replay runtime session started",
            capture_file=capture_file,
            interval_seconds=interval_seconds,
            limit=limit,
        )

    def _handle_replay_stop(
        self,
        _payload: dict[str, Any],
    ) -> None:
        """Stop replay runtime session."""

        runtime_mode = (
            self._replay_runtime_runner
            ._runtime_state_manager
            .runtime_mode
        )

        if runtime_mode != "replay":
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Invalid runtime state transition",
                command="replay.stop",
                runtime_mode=runtime_mode,
            )
            return

        self._replay_runtime_runner.stop(
            reason="runtime_command_replay_stop",
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime-command",
            message="Replay runtime session stopped",
        )

    def _on_command(self, topic: str, payload: bytes) -> None:
        """Process incoming MQTT runtime command."""

        try:
            payload_text = payload.decode("utf-8").strip()

            if not payload_text:
                return

            if payload_text.startswith("{"):
                try:
                    command_payload = json.loads(payload_text)
                except json.JSONDecodeError as exc:
                    self._status_publisher.publish_error(
                        component="runtime-command",
                        message="Invalid JSON payload",
                        error=str(exc),
                    )
                    return
                command = str(command_payload.get("command", "")).strip()
            else:
                command_payload = {}
                command = payload_text
                command_payload["command"] = command

            if not command:
                self._status_publisher.publish_error(
                    component="runtime-command",
                    message="Missing runtime command",
                )
                return

            try:
                self._validator.validate(
                    command,
                    command_payload,
                )
            except RuntimeCommandValidationError as exc:
                self._status_publisher.publish_error(
                    component="runtime-command",
                    message=exc.message,
                    error_type=exc.error_type,
                    **exc.details,
                )
                return

            handler = self._handlers.get(command)

            if handler is None:
                self._status_publisher.publish_error(
                    component="runtime-command",
                    message="Unknown runtime command",
                    command=command,
                )
                return

            self._status_publisher.publish_log(
                level="info",
                component="runtime-command",
                message="Executing runtime command",
                command=command,
            )

            handler(command_payload)

        except Exception as exc:
            self._status_publisher.publish_error(
                component="runtime-command",
                message="Runtime command execution failed",
                error=str(exc),
                topic=topic,
            )
