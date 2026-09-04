"""Strict runtime configuration models and loading helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enocean_mqtt.config import load_json_file
from enocean_mqtt.mqtt.models import MQTTConfig

DeviceTopicIdentifier = Literal["device_id", "alias", "both"]
LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LoggingFormat = Literal["text", "json"]
BASE_ID_PATTERN = re.compile(r"^[0-9A-F]{8}$")


class ApplicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="enocean-mqtt", min_length=1)
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value


class RuntimePathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices_json: str = "config/devices.json"
    virtual_devices_json: str = "config/virtual-devices.json"
    sender_id_registry: str = "config/sender-id-registry.json"
    devices_csv_import: str = "testdata/devices.csv"
    devices_csv_export: str = "export/devices.csv"
    unknown_devices_csv_export: str = "export/unknown_devices.csv"
    eep_registry_directory: str = "eep/registry"


class TopicsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_topic_identifier: DeviceTopicIdentifier = "device_id"


class SerialReconnectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    initial_delay_seconds: int = Field(default=5, gt=0)
    max_delay_seconds: int = Field(default=60, gt=0)

    @model_validator(mode="after")
    def validate_delay_order(self) -> SerialReconnectConfig:
        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError("initial_delay_seconds must not exceed max_delay_seconds")
        return self


class InterfaceNetworkBridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=7000, ge=1, le=65535)
    ser2net_binary: str = Field(default="ser2net", min_length=1)


class InterfaceTransportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface_id: str = Field(min_length=1)
    enabled: bool = False
    tx_enabled: bool = False
    type: Literal["serial_esp3"] = "serial_esp3"
    device: str = Field(min_length=1)
    baudrate: int = Field(default=57600, gt=0)
    timeout_seconds: float = Field(default=1.0, gt=0)
    base_id: str | None = None
    reconnect: SerialReconnectConfig = Field(default_factory=SerialReconnectConfig)
    network_bridge: InterfaceNetworkBridgeConfig = Field(
        default_factory=InterfaceNetworkBridgeConfig
    )

    @field_validator("interface_id")
    @classmethod
    def strip_interface_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("interface_id must not be empty")
        return normalized

    @field_validator("base_id")
    @classmethod
    def validate_base_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not BASE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("base_id must contain exactly eight hexadecimal digits")
        if int(normalized, 16) & 0x7F:
            raise ValueError("base_id must have its lowest seven bits cleared")
        return normalized


class EnOceanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_interface: str | None = None
    tx_enabled: bool = False
    interfaces: list[InterfaceTransportConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interfaces(self) -> EnOceanConfig:
        interface_ids = [interface.interface_id for interface in self.interfaces]
        if len(interface_ids) != len(set(interface_ids)):
            raise ValueError("enocean interface_id values must be unique")
        if self.default_interface is not None:
            self.default_interface = self.default_interface.strip()
            if self.default_interface not in interface_ids:
                raise ValueError("default_interface must reference enocean.interfaces")
        return self

    def get_default_interface(self) -> InterfaceTransportConfig | None:
        if self.default_interface is None:
            return None
        return next(
            interface
            for interface in self.interfaces
            if interface.interface_id == self.default_interface
        )

    def default_base_id(self) -> str | None:
        interface = self.get_default_interface()
        return interface.base_id if interface is not None else None


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    health_publish_interval_seconds: int = Field(default=300, gt=0)


class MetricsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    peak_telegrams_window_seconds: int = Field(default=900, gt=0)
    telegram_mean_interval_window_seconds: int = Field(default=3600, gt=0)
    active_device_window_seconds: int = Field(default=86400, gt=0)


class SQLiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    database_path: str = Field(default="data/sqlite/enocean-mqtt.sqlite", min_length=1)
    persist_live: bool = True
    persist_replay: bool = False
    max_telegrams: int = Field(default=0, ge=0)


class PublishDefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool = True
    state: bool = True
    meta: bool = True
    retain: bool = True
    on_change_only: bool = False
    change_threshold: float | None = None
    min_interval_seconds: float | None = Field(default=None, ge=0)
    max_interval_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_interval_order(self) -> PublishDefaultsConfig:
        if (
            self.min_interval_seconds is not None
            and self.max_interval_seconds is not None
            and self.min_interval_seconds > self.max_interval_seconds
        ):
            raise ValueError("min_interval_seconds must not exceed max_interval_seconds")
        return self


class WebAPISSEConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    max_queue_size: int = Field(default=1000, gt=0)


class WebAPIAuthenticationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    token_file: str = Field(default="config/secrets/api-tokens.json", min_length=1)


class WebAPIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8001, ge=1, le=65535)
    reload: bool = False
    authentication: WebAPIAuthenticationConfig = Field(default_factory=WebAPIAuthenticationConfig)
    sse: WebAPISSEConfig = Field(default_factory=WebAPISSEConfig)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: LoggingLevel = "INFO"
    format: LoggingFormat = "text"

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    enocean: EnOceanConfig = Field(default_factory=EnOceanConfig)
    mqtt: MQTTConfig
    topics: TopicsConfig = Field(default_factory=TopicsConfig)
    paths: RuntimePathsConfig = Field(default_factory=RuntimePathsConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    sqlite: SQLiteConfig = Field(default_factory=SQLiteConfig)
    publish_defaults: PublishDefaultsConfig = Field(default_factory=PublishDefaultsConfig)
    web_api: WebAPIConfig = Field(default_factory=WebAPIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def configured_interfaces(self) -> list[InterfaceTransportConfig]:
        return list(self.enocean.interfaces)

    def default_tx_base_id(self) -> str | None:
        return self.enocean.default_base_id()


def _load_sender_registry_base_ids(path: str | Path) -> dict[str, str]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    interfaces = payload.get("interfaces", [])
    if not isinstance(interfaces, list):
        return {}
    return {
        str(item["interface_id"]): str(item["base_id"]).strip().upper()
        for item in interfaces
        if isinstance(item, dict)
        and item.get("interface_id") is not None
        and item.get("base_id") is not None
    }


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    runtime_config = RuntimeConfig.model_validate(load_json_file(path))
    sender_registry_base_ids = _load_sender_registry_base_ids(
        runtime_config.paths.sender_id_registry
    )
    if sender_registry_base_ids:
        runtime_config.enocean.interfaces = [
            interface.model_copy(
                update={
                    "base_id": interface.base_id
                    or sender_registry_base_ids.get(interface.interface_id)
                }
            )
            for interface in runtime_config.enocean.interfaces
        ]
    os.environ["ENOCEAN_MQTT_EEP_REGISTRY"] = runtime_config.paths.eep_registry_directory
    return runtime_config
