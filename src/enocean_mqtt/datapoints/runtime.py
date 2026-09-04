"""Runtime value access for datapoints.

The discovery registry describes which datapoints exist. This module overlays
runtime state onto those datapoints without changing the discovery model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Literal

from enocean_mqtt.datapoints.models import Datapoint
from enocean_mqtt.datapoints.registry import DatapointRegistry

DatapointValueQuality = Literal[
    "good",
    "unavailable",
    "unsupported",
]


@dataclass(frozen=True, slots=True)
class DatapointValue:
    """Current or last-known runtime value for one datapoint."""

    datapoint_id: str
    value: Any = None
    unit: str | None = None
    quality: DatapointValueQuality = "unavailable"
    timestamp: str | None = None
    source: str | None = None
    message: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """Return the API value representation."""

        return _drop_none(
            {
                "datapoint_id": self.datapoint_id,
                "value": self.value,
                "unit": self.unit,
                "quality": self.quality,
                "timestamp": self.timestamp,
                "source": self.source,
                "message": self.message,
            }
        )


@dataclass(slots=True)
class DatapointRuntimeRegistry:
    """Runtime overlay for API datapoints."""

    datapoints: DatapointRegistry
    values: dict[str, DatapointValue] = dataclass_field(default_factory=dict)
    issues: list[dict[str, Any]] = dataclass_field(default_factory=list)

    @classmethod
    def from_device_state_payloads(
        cls,
        *,
        datapoints: DatapointRegistry,
        device_states: Mapping[str, Mapping[str, Any]],
        source: str,
    ) -> DatapointRuntimeRegistry:
        """Build runtime values from device-state payloads.

        ``device_states`` is keyed by API-facing device ID. Each payload may
        contain a ``channels`` object with channel names as keys and current or
        last-known channel state as values.
        """

        values: dict[str, DatapointValue] = {}

        for datapoint in datapoints.datapoints:
            if not datapoint.readable:
                values[datapoint.id] = DatapointValue(
                    datapoint_id=datapoint.id,
                    unit=datapoint.unit,
                    quality="unsupported",
                    source=source,
                    message="Datapoint is not readable",
                )
                continue

            device_state = device_states.get(datapoint.device_id)
            channel_state = _channel_state_for_datapoint(
                datapoint,
                device_state,
            )

            if channel_state is None:
                values[datapoint.id] = DatapointValue(
                    datapoint_id=datapoint.id,
                    unit=datapoint.unit,
                    quality="unavailable",
                    source=source,
                    message="No runtime value available",
                )
                continue

            values[datapoint.id] = DatapointValue(
                datapoint_id=datapoint.id,
                value=channel_state.get("value"),
                unit=channel_state.get("unit") or datapoint.unit,
                quality="good",
                timestamp=(
                    channel_state.get("last_update")
                    or channel_state.get("timestamp_local")
                    or device_state.get("last_update")
                    if device_state is not None
                    else None
                ),
                source=source,
            )

        return cls(
            datapoints=datapoints,
            values=values,
        )

    def get_value(self, datapoint_id: str) -> DatapointValue | None:
        """Return runtime value for one datapoint."""

        datapoint = self.datapoints.get(datapoint_id)

        if datapoint is None:
            return None

        return self.values.get(
            datapoint_id,
            DatapointValue(
                datapoint_id=datapoint_id,
                unit=datapoint.unit,
                quality="unavailable",
                message="No runtime value available",
            ),
        )

    def value_payload_for_datapoint(self, datapoint: Datapoint) -> dict[str, Any]:
        """Return datapoint discovery payload with runtime value overlay."""

        payload = datapoint.to_api_dict()
        value = self.get_value(datapoint.id)
        payload["runtime_value"] = (
            value.to_api_dict()
            if value is not None
            else DatapointValue(datapoint_id=datapoint.id).to_api_dict()
        )
        return payload


def _channel_state_for_datapoint(
    datapoint: Datapoint,
    device_state: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if device_state is None:
        return None

    channels = device_state.get("channels")

    if not isinstance(channels, Mapping):
        return None

    channel_state = channels.get(datapoint.source.name)

    if isinstance(channel_state, Mapping):
        return channel_state

    if channel_state is not None:
        return {"value": channel_state}

    return None


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }
