"""MQTT configuration loading helpers."""

from __future__ import annotations

from pathlib import Path

from enocean_mqtt.config import load_json_file
from enocean_mqtt.mqtt.models import MQTTConfig


def load_mqtt_config(path: str | Path) -> MQTTConfig:
    """Load validated MQTT configuration."""

    config = load_json_file(path)

    mqtt_config = config.get("mqtt")

    if not isinstance(mqtt_config, dict):
        raise RuntimeError("Missing mqtt configuration section")

    return MQTTConfig.model_validate(mqtt_config)
