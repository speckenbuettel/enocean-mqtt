"""MQTT runtime configuration models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MQTTReconnectConfig(BaseModel):
    """Mandatory MQTT reconnect timing configuration."""

    model_config = ConfigDict(extra="forbid")
    initial_delay_seconds: int = Field(default=5, gt=0)
    max_delay_seconds: int = Field(default=60, gt=0)

    @model_validator(mode="after")
    def validate_delay_order(self) -> MQTTReconnectConfig:
        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError("initial_delay_seconds must not exceed max_delay_seconds")
        return self


class MQTTTLSConfig(BaseModel):
    """Reserved MQTT TLS configuration."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    ca_cert_file: str | None = None
    client_cert_file: str | None = None
    client_key_file: str | None = None
    insecure_skip_verify: bool = False

    @model_validator(mode="after")
    def reject_unimplemented_tls(self) -> MQTTTLSConfig:
        if self.enabled:
            raise ValueError("MQTT TLS is not implemented; enabled must be false")
        return self


class MQTTConfig(BaseModel):
    """Validated MQTT runtime configuration."""

    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1)
    port: int = Field(default=1883, ge=1, le=65535)
    client_id: str = Field(default="enocean-mqtt", min_length=1)
    base_topic: str = Field(min_length=1)
    clean_session: bool = True
    runtime_commands_enabled: bool = True
    username: str | None = None
    password_file: str | None = None
    keepalive_seconds: int = Field(default=30, gt=0)
    reconnect: MQTTReconnectConfig = Field(default_factory=MQTTReconnectConfig)
    tls: MQTTTLSConfig = Field(default_factory=MQTTTLSConfig)
