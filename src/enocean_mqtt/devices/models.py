"""Device registry models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DeviceCommunication = Literal[
    "unidirectional",
    "bidirectional_eep",
    "bidirectional_eep_pair",
]


class Device(BaseModel):
    """Validated EnOcean physical device registry model."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
    )

    device_id: str
    device_name: str
    alias: str | None = None
    description: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    communication: DeviceCommunication = "unidirectional"
    eep: str | None = None
    profile: str | None = None
    tx_eep: str | None = None
    tx_profile: str | None = None
    sender_id: str | None = None
    enocean_secure: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def registry_profile(self) -> str | None:
        """Return concrete registry profile used for receive-side decoding."""

        return self.profile or self.eep

    @property
    def tx_registry_profile(self) -> str | None:
        """Return concrete registry profile used for transmit-side encoding."""

        return self.tx_profile or self.profile or self.tx_eep or self.eep
