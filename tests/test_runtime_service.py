from __future__ import annotations

from collections.abc import Callable
from typing import Any

from enocean_mqtt.datapoints import DatapointRegistry
from enocean_mqtt.datapoints.models import Datapoint, DatapointSource
from enocean_mqtt.devices.projection import ApiDevice, ApiDeviceRegistry
from enocean_mqtt.runtime.service import RuntimeService


class FakePhysicalRuntimeState:
    def __init__(self, states: dict[str, dict[str, Any]]) -> None:
        self.states = states

    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        state = self.states.get(device_id)

        if state is None:
            return None

        return dict(state)


class FakeVirtualRuntimeState:
    def __init__(self, states: dict[str, dict[str, Any]]) -> None:
        self.states = states

    def get_device_state(self, virtual_device_id: str) -> dict[str, Any] | None:
        state = self.states.get(virtual_device_id)

        if state is None:
            return None

        return dict(state)


def _service(
    *,
    physical_states: dict[str, dict[str, Any]] | None = None,
    virtual_states: dict[str, dict[str, Any]] | None = None,
    fallback_states: dict[str, dict[str, Any]] | None = None,
) -> RuntimeService:
    datapoint_registry = DatapointRegistry(
        datapoints=[
            Datapoint(
                id="th_sensor.temperature",
                device_id="th_sensor",
                name="temperature",
                display_name=None,
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
                    device_id="052523B1",
                ),
            )
        ],
    )
    api_device_registry = ApiDeviceRegistry(
        devices=[
            ApiDevice(
                id="th_sensor",
                source_type="physical_device",
                device_id="052523B1",
                readable=True,
                writable=False,
                datapoints_count=1,
                datapoints_url="/api/v1/devices/th_sensor/datapoints",
            ),
            ApiDevice(
                id="virtual_sensor",
                source_type="virtual_device",
                virtual_device_id="virtual_sensor",
                readable=False,
                writable=True,
                datapoints_count=1,
                datapoints_url="/api/v1/devices/virtual_sensor/datapoints",
            ),
        ],
    )

    fallback_provider: Callable[[], dict[str, dict[str, Any]]] | None = None

    if fallback_states is not None:
        def fallback_provider() -> dict[str, dict[str, Any]]:
            return fallback_states

    return RuntimeService(
        datapoint_registry=datapoint_registry,
        api_device_registry=api_device_registry,
        device_publisher=(
            FakePhysicalRuntimeState(physical_states)
            if physical_states is not None
            else None
        ),
        virtual_device_runtime=(
            FakeVirtualRuntimeState(virtual_states)
            if virtual_states is not None
            else None
        ),
        fallback_device_states_provider=fallback_provider,
        fallback_source="sqlite_latest_telegram",
    )


def test_runtime_service_returns_api_devices() -> None:
    service = _service()

    payload = service.get_devices()

    assert payload["count"] == 2
    assert {device["id"] for device in payload["devices"]} == {
        "th_sensor",
        "virtual_sensor",
    }


def test_runtime_service_maps_api_device_id_to_physical_runtime_state() -> None:
    service = _service(
        physical_states={
            "052523B1": {
                "device_id": "052523B1",
                "channels": {
                    "temperature": {
                        "value": 21.5,
                        "unit": "°C",
                    }
                },
            }
        }
    )

    state = service.get_device_state("th_sensor")

    assert state is not None
    assert state["device_id"] == "052523B1"
    assert state["channels"]["temperature"]["value"] == 21.5


def test_runtime_service_maps_api_device_id_to_virtual_runtime_state() -> None:
    service = _service(
        virtual_states={
            "virtual_sensor": {
                "virtual_device_id": "virtual_sensor",
                "channels": {
                    "temperature": {
                        "value": 22.0,
                    }
                },
            }
        }
    )

    state = service.get_device_state("virtual_sensor")

    assert state is not None
    assert state["virtual_device_id"] == "virtual_sensor"
    assert state["channels"]["temperature"]["value"] == 22.0


def test_runtime_service_builds_datapoint_runtime_from_physical_state() -> None:
    service = _service(
        physical_states={
            "052523B1": {
                "device_id": "052523B1",
                "last_update": "2026-06-26T12:00:00+00:00",
                "channels": {
                    "temperature": {
                        "value": 21.5,
                        "unit": "°C",
                        "last_update": "2026-06-26T12:00:00+00:00",
                    }
                },
            }
        }
    )

    runtime = service.get_datapoint_runtime_registry()
    value = runtime.get_value("th_sensor.temperature")

    assert value is not None
    assert value.value == 21.5
    assert value.quality == "good"
    assert value.source == "runtime"


def test_runtime_service_uses_fallback_when_no_runtime_state_exists() -> None:
    service = _service(
        fallback_states={
            "th_sensor": {
                "device_id": "th_sensor",
                "channels": {
                    "temperature": {
                        "value": 20.0,
                    }
                },
            }
        }
    )

    runtime = service.get_datapoint_runtime_registry()
    value = runtime.get_value("th_sensor.temperature")

    assert value is not None
    assert value.value == 20.0
    assert value.quality == "good"
    assert value.source == "sqlite_latest_telegram"
