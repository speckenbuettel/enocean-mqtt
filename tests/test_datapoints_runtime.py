"""Tests for datapoint runtime value overlay."""

from __future__ import annotations

from enocean_mqtt.datapoints.models import Datapoint, DatapointSource
from enocean_mqtt.datapoints.registry import DatapointRegistry
from enocean_mqtt.datapoints.runtime import DatapointRuntimeRegistry, DatapointValue


def _required_value(
    runtime: DatapointRuntimeRegistry,
    datapoint_id: str,
) -> DatapointValue:
    value = runtime.get_value(datapoint_id)

    assert value is not None

    return value


def test_runtime_registry_overlays_good_readable_value():
    datapoint = Datapoint(
        id="living_room.temperature",
        device_id="living_room",
        name="temperature",
        display_name="Temperature",
        semantic_role="climate.temperature.measurement",
        object_type="measurement",
        data_type="float",
        unit="°C",
        readable=True,
        writable=False,
        direction="read",
        stateful=True,
        source=DatapointSource(
            source_type="physical_device",
            collection="channels",
            name="temperature",
            profile="A5-04-02",
            device_id="0185286B",
        ),
    )
    registry = DatapointRegistry(datapoints=[datapoint])

    runtime = DatapointRuntimeRegistry.from_device_state_payloads(
        datapoints=registry,
        device_states={
            "living_room": {
                "last_update": "2026-06-25T12:00:00+00:00",
                "channels": {
                    "temperature": {
                        "value": 21.4,
                        "unit": "°C",
                        "last_update": "2026-06-25T12:00:00+00:00",
                    }
                },
            }
        },
        source="test",
    )

    assert _required_value(runtime, "living_room.temperature").to_api_dict() == {
        "datapoint_id": "living_room.temperature",
        "value": 21.4,
        "unit": "°C",
        "quality": "good",
        "timestamp": "2026-06-25T12:00:00+00:00",
        "source": "test",
    }


def test_runtime_registry_reports_writable_datapoint_as_unsupported():
    datapoint = Datapoint(
        id="living_room.temperature_setpoint",
        device_id="living_room",
        name="temperature_setpoint",
        display_name="Temperature Setpoint",
        semantic_role="climate.temperature.setpoint",
        object_type="setpoint",
        data_type="float",
        unit="°C",
        readable=False,
        writable=True,
        direction="write",
        stateful=True,
        source=DatapointSource(
            source_type="physical_device",
            collection="messages",
            name="temperature_setpoint",
            profile="A5-20-06",
            device_id="0185286B",
        ),
    )
    registry = DatapointRegistry(datapoints=[datapoint])

    runtime = DatapointRuntimeRegistry.from_device_state_payloads(
        datapoints=registry,
        device_states={},
        source="test",
    )

    assert _required_value(
        runtime,
        "living_room.temperature_setpoint",
    ).to_api_dict() == {
        "datapoint_id": "living_room.temperature_setpoint",
        "unit": "°C",
        "quality": "unsupported",
        "source": "test",
        "message": "Datapoint is not readable",
    }


def test_runtime_registry_reports_missing_value_as_unavailable():
    datapoint = Datapoint(
        id="living_room.temperature",
        device_id="living_room",
        name="temperature",
        display_name="Temperature",
        semantic_role="climate.temperature.measurement",
        object_type="measurement",
        data_type="float",
        unit="°C",
        readable=True,
        writable=False,
        direction="read",
        stateful=True,
        source=DatapointSource(
            source_type="physical_device",
            collection="channels",
            name="temperature",
            profile="A5-04-02",
            device_id="0185286B",
        ),
    )
    registry = DatapointRegistry(datapoints=[datapoint])

    runtime = DatapointRuntimeRegistry.from_device_state_payloads(
        datapoints=registry,
        device_states={},
        source="test",
    )

    assert _required_value(runtime, "living_room.temperature").to_api_dict() == {
        "datapoint_id": "living_room.temperature",
        "unit": "°C",
        "quality": "unavailable",
        "source": "test",
        "message": "No runtime value available",
    }
