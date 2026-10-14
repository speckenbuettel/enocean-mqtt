"""Semantic datapoint API models."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Literal

DatapointDirection = Literal["read", "write", "read_write"]
DatapointSourceType = Literal["physical_device", "virtual_device"]
DatapointCollection = Literal["channels", "messages", "virtual_channels"]


@dataclass(frozen=True, slots=True)
class DatapointSource:
    """Internal source metadata for one API datapoint."""

    source_type: DatapointSourceType
    collection: DatapointCollection
    name: str
    profile: str
    eep: str | None = None
    device_id: str | None = None
    virtual_device_id: str | None = None
    sender_id: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """Return API-safe source metadata."""

        return _drop_none(
            {
                "source_type": self.source_type,
                "collection": self.collection,
                "name": self.name,
                "profile": self.profile,
                "eep": self.eep,
                "device_id": self.device_id,
                "virtual_device_id": self.virtual_device_id,
                "sender_id": self.sender_id,
            }
        )


@dataclass(frozen=True, slots=True)
class Datapoint:
    """API-facing semantic runtime datapoint."""

    id: str
    device_id: str
    name: str
    display_name: str | None
    semantic_role: str | None
    object_type: str | None
    data_type: str | None
    unit: str | None
    readable: bool
    writable: bool
    direction: DatapointDirection
    stateful: bool
    source: DatapointSource
    description: str | None = None
    enum: list[dict[str, Any]] = dataclass_field(default_factory=list)
    ranges: list[dict[str, Any]] = dataclass_field(default_factory=list)
    default_value: Any = None
    value_resolution: float | None = None
    value_precision: int | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        """Return the public API representation."""

        return _drop_none(
            {
                "id": self.id,
                "device_id": self.device_id,
                "name": self.name,
                "display_name": self.display_name,
                "semantic_role": self.semantic_role,
                "object_type": self.object_type,
                "data_type": self.data_type,
                "unit": self.unit,
                "readable": self.readable,
                "writable": self.writable,
                "direction": self.direction,
                "stateful": self.stateful,
                "description": self.description,
                "enum": self.enum or None,
                "ranges": self.ranges or None,
                "default_value": self.default_value,
                "value_resolution": self.value_resolution,
                "value_precision": self.value_precision,
                "metadata": self.metadata or None,
                "source": self.source.to_api_dict(),
                "representations": self.representations(),
            }
        )

    def representations(self) -> list[dict[str, Any]]:
        """Selectors are fields of one datapoint, not independent stateful IDs."""
        result = [{"field": "value", "data_type": self.data_type,
                   "readable": self.readable, "writable": self.writable}]
        if self.readable and self.data_type == "integer" and (
            self.enum or self.metadata.get("enum_variants")
        ):
            result.append({"field": "meaning", "data_type": "string",
                           "readable": True, "writable": False})
        return result


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }
