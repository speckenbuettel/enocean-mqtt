"""Virtual device registry models."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

VIRTUAL_DEVICE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
SENDER_ID_PATTERN = re.compile(r"^[A-F0-9]{8}$")


class VirtualDevice(BaseModel):
    """Validated virtual EnOcean device registry model."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
    )

    virtual_device_id: str
    sender_id: str
    eep: str
    profile: str | None = None
    channels: list[str] = Field(default_factory=list)
    description: str | None = None
    enabled: bool = True
    teach_in_method: str | None = None
    teach_in_telegram: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("virtual_device_id")
    @classmethod
    def validate_virtual_device_id(cls, value: str) -> str:
        """Validate MQTT-safe virtual device identity."""

        normalized = value.strip().lower()

        if not VIRTUAL_DEVICE_ID_PATTERN.match(normalized):
            raise ValueError(
                "virtual_device_id must be lowercase snake_case"
            )

        return normalized

    @field_validator("sender_id")
    @classmethod
    def validate_sender_id(cls, value: str) -> str:
        """Validate canonical EnOcean sender ID."""

        normalized = value.strip().upper()

        if normalized.lower().startswith("0x"):
            normalized = normalized[2:]

        if not SENDER_ID_PATTERN.match(normalized):
            raise ValueError(
                "sender_id must be exactly 8 uppercase hexadecimal characters"
            )

        return normalized

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: list[str]) -> list[str]:
        """Normalize and validate configured TX channels."""

        channels = [item.strip() for item in value if item.strip()]

        if not channels:
            raise ValueError("at least one channel must be configured")

        duplicates = {
            channel for channel in channels if channels.count(channel) > 1
        }

        if duplicates:
            raise ValueError(
                "duplicate virtual device channels: "
                f"{', '.join(sorted(duplicates))}"
            )

        return channels

    @property
    def registry_profile(self) -> str:
        """Return concrete EEP registry profile used for TX encoding."""

        return self.profile or self.eep
