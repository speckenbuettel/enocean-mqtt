from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from enocean_mqtt.datapoints import DatapointRegistry
from enocean_mqtt.datapoints.models import Datapoint, DatapointSource
from enocean_mqtt.devices.projection import ApiDevice, ApiDeviceRegistry
from enocean_mqtt.runtime.service import RuntimeService
from enocean_mqtt.web_api.semantic_routes import _sse_event, create_semantic_router


def _runtime_service() -> RuntimeService:
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
                metadata={
                    "tags": ["climate", "room"],
                },
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
            )
        ],
    )

    return RuntimeService(
        datapoint_registry=datapoint_registry,
        api_device_registry=api_device_registry,
        fallback_device_states_provider=_fallback_device_states,
        fallback_source="sqlite_latest_telegram",
    )


def _fallback_device_states() -> dict[str, dict[str, Any]]:
    return {
        "th_sensor": {
            "device_id": "th_sensor",
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


def _endpoint(path: str) -> Callable[..., dict[str, Any]]:
    router = create_semantic_router(_runtime_service)

    for route in router.routes:
        if isinstance(route, APIRoute) and route.path == path:
            endpoint = route.endpoint
            return endpoint

    raise AssertionError(f"Route not found: {path}")


def test_semantic_routes_return_devices_via_runtime_service() -> None:
    payload = _endpoint("/api/v1/devices")()

    assert payload["count"] == 1
    assert payload["devices"][0]["id"] == "th_sensor"


def test_semantic_routes_export_devices_before_dynamic_device_route() -> None:
    payload = _endpoint("/api/v1/devices/export")()

    assert payload["format"] == "enocean-devices"
    assert payload["format_version"] == 1
    assert payload["count"] == 1
    assert payload["devices"][0]["id"] == "th_sensor"


def test_semantic_routes_return_device_datapoints() -> None:
    payload = _endpoint("/api/v1/devices/{device_id}/datapoints")(
        device_id="th_sensor",
    )

    assert payload["count"] == 1
    assert payload["datapoints"][0]["id"] == "th_sensor.temperature"


def test_semantic_routes_return_filtered_datapoints() -> None:
    payload = _endpoint("/api/v1/datapoints")(
        semantic_role="climate.temperature.measurement",
    )

    assert payload["count"] == 1
    assert payload["datapoints"][0]["name"] == "temperature"


def test_semantic_routes_return_datapoints_filtered_by_tag() -> None:
    payload = _endpoint("/api/v1/datapoints")(
        tag="climate",
    )

    assert payload["count"] == 1
    assert payload["datapoints"][0]["id"] == "th_sensor.temperature"


def test_semantic_routes_return_datapoint_tags() -> None:
    payload = _endpoint("/api/v1/datapoints/tags")()

    assert payload == {
        "tags": [
            {
                "tag": "climate",
                "datapoints_count": 1,
                "datapoints": ["th_sensor.temperature"],
            },
            {
                "tag": "room",
                "datapoints_count": 1,
                "datapoints": ["th_sensor.temperature"],
            },
        ],
        "count": 2,
    }


def test_semantic_routes_return_datapoint_value_without_global_issues() -> None:
    payload = _endpoint("/api/v1/datapoints/{datapoint_id}/value")(
        datapoint_id="th_sensor.temperature",
    )

    assert payload == {
        "value": {
            "datapoint_id": "th_sensor.temperature",
            "value": 21.5,
            "unit": "°C",
            "quality": "good",
            "timestamp": "2026-06-26T12:00:00+00:00",
            "source": "sqlite_latest_telegram",
        }
    }


def test_semantic_routes_format_datapoint_sse_event() -> None:
    event = _sse_event(
        "datapoint",
        {
            "datapoint_id": "th_sensor.temperature",
            "value": 21.5,
            "quality": "good",
        },
    )

    assert event == (
        'event: datapoint\n'
        'data: {"datapoint_id":"th_sensor.temperature","value":21.5,"quality":"good"}\n\n'
    )


def test_semantic_routes_return_404_for_unknown_datapoint() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _endpoint("/api/v1/datapoints/{datapoint_id}")(
            datapoint_id="unknown.value",
        )

    assert exc_info.value.status_code == 404
