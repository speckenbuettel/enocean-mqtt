"""Configuration loading helpers for enocean-mqtt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""


SUPPORTED_INPUT_MODES = {
    "simulation",
}


REQUIRED_TOP_LEVEL_SECTIONS = {
    "application",
    "mqtt",
    "simulation",
    "status",
    "files",
}


REQUIRED_MQTT_FIELDS = {
    "host",
    "port",
    "client_id",
    "base_topic",
}


REQUIRED_SIMULATION_FIELDS = {
    "interval_seconds",
}


REQUIRED_STATUS_FIELDS = {
    "availability_topic",
    "health_topic",
    "last_will",
}


REQUIRED_LAST_WILL_FIELDS = {
    "online_payload",
    "offline_payload",
    "retain",
    "qos",
}


REQUIRED_FILES_FIELDS = {
    "devices_file",
}


REQUIRED_APPLICATION_FIELDS = {
    "input_mode",
}



def load_json_file(path: str | Path) -> dict[str, Any]:
    """Load and parse a JSON configuration file."""

    config_path = Path(path)

    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    try:
        data = cast(
            dict[str, Any],
            json.loads(config_path.read_text(encoding="utf-8")),
        )

        return data
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in configuration file: {config_path}"
        ) from exc



def validate_runtime_config(config: dict[str, Any]) -> None:
    """Validate runtime configuration structure and values."""

    _validate_required_sections(config)
    _validate_application_config(config["application"])
    _validate_mqtt_config(config["mqtt"])
    _validate_simulation_config(config["simulation"])
    _validate_status_config(config["status"])
    _validate_files_config(config["files"])



def _validate_required_sections(config: dict[str, Any]) -> None:
    missing = REQUIRED_TOP_LEVEL_SECTIONS - set(config.keys())

    if missing:
        raise ConfigurationError(
            "Missing required configuration sections: "
            f"{', '.join(sorted(missing))}"
        )



def _validate_application_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_APPLICATION_FIELDS - set(config.keys())

    if missing:
        raise ConfigurationError(
            "Missing required application configuration fields: "
            f"{', '.join(sorted(missing))}"
        )

    input_mode = cast(str, config["input_mode"])

    if input_mode not in SUPPORTED_INPUT_MODES:
        raise ConfigurationError(
            f"Unsupported input_mode '{input_mode}'. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_INPUT_MODES))}"
        )



def _validate_mqtt_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_MQTT_FIELDS - set(config.keys())

    if missing:
        raise ConfigurationError(
            "Missing required MQTT configuration fields: "
            f"{', '.join(sorted(missing))}"
        )

    if not config["host"]:
        raise ConfigurationError("MQTT host must not be empty")

    if not config["client_id"]:
        raise ConfigurationError("MQTT client_id must not be empty")

    if not config["base_topic"]:
        raise ConfigurationError("MQTT base_topic must not be empty")

    port = config["port"]

    if not isinstance(port, int):
        raise ConfigurationError("MQTT port must be an integer")

    if not 1 <= port <= 65535:
        raise ConfigurationError("MQTT port must be between 1 and 65535")



def _validate_simulation_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_SIMULATION_FIELDS - set(config.keys())

    if missing:
        raise ConfigurationError(
            "Missing required simulation configuration fields: "
            f"{', '.join(sorted(missing))}"
        )

    interval = config["interval_seconds"]

    if not isinstance(interval, int | float):
        raise ConfigurationError("simulation.interval_seconds must be numeric")

    if interval <= 0:
        raise ConfigurationError(
            "simulation.interval_seconds must be greater than zero"
        )



def _validate_status_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_STATUS_FIELDS - set(config.keys())

    if missing:
        raise ConfigurationError(
            "Missing required status configuration fields: "
            f"{', '.join(sorted(missing))}"
        )

    last_will = config["last_will"]

    missing_last_will = REQUIRED_LAST_WILL_FIELDS - set(last_will.keys())

    if missing_last_will:
        raise ConfigurationError(
            "Missing required last_will configuration fields: "
            f"{', '.join(sorted(missing_last_will))}"
        )



def _validate_files_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_FILES_FIELDS - set(config.keys())

    if missing:
        raise ConfigurationError(
            "Missing required files configuration fields: "
            f"{', '.join(sorted(missing))}"
        )

    devices_file = config["devices_file"]

    if not devices_file:
        raise ConfigurationError("files.devices_file must not be empty")
