from __future__ import annotations

from datetime import UTC, datetime

from enocean_mqtt.datapoints import DatapointRegistry
from enocean_mqtt.datapoints.models import Datapoint, DatapointSource
from enocean_mqtt.devices.projection import ApiDevice, ApiDeviceRegistry
from enocean_mqtt.runtime.service import RuntimeService
from enocean_mqtt.web_api.services.project_export import (
    build_enocean_project_export,
)


def test_project_export_projects_devices_channels_and_messages() -> None:
    service = RuntimeService(
        datapoint_registry=DatapointRegistry(
            datapoints=[
                Datapoint(
                    id="living_room.temperature",
                    device_id="living_room",
                    name="temperature",
                    display_name="Living Room Temperature",
                    semantic_role="climate.temperature.measurement",
                    object_type="measurement",
                    data_type="float",
                    unit="degC",
                    readable=True,
                    writable=False,
                    direction="read",
                    stateful=True,
                    source=DatapointSource(
                        source_type="physical_device",
                        collection="channels",
                        name="temperature",
                        profile="A5-04-02",
                        eep="A5-04-02",
                        device_id="052523B1",
                        sender_id="052523B1",
                    ),
                ),
                Datapoint(
                    id="living_room.setpoint",
                    device_id="living_room",
                    name="setpoint",
                    display_name="Living Room Setpoint",
                    semantic_role="climate.temperature.setpoint",
                    object_type="setpoint",
                    data_type="float",
                    unit="degC",
                    readable=False,
                    writable=True,
                    direction="write",
                    stateful=True,
                    source=DatapointSource(
                        source_type="physical_device",
                        collection="messages",
                        name="setpoint",
                        profile="A5-04-02",
                        eep="A5-04-02",
                        device_id="052523B1",
                        sender_id="052523B1",
                    ),
                ),
            ]
        ),
        api_device_registry=ApiDeviceRegistry(
            devices=[
                ApiDevice(
                    id="living_room",
                    source_type="physical_device",
                    device_id="052523B1",
                    sender_id="052523B1",
                    alias="living_room",
                    device_name="Living Room Sensor",
                    eep="A5-04-02",
                    profile="A5-04-02",
                    enabled=True,
                    metadata={"room": "living_room"},
                    readable=True,
                    writable=True,
                    datapoints_count=2,
                    datapoints_url="/api/v1/devices/living_room/datapoints",
                )
            ]
        ),
    )

    payload = build_enocean_project_export(
        service,
        project_id="house",
        base_topic="enocean",
        generator_version="test",
        generated_at=datetime(2026, 7, 2, 10, 15, tzinfo=UTC),
    )

    device = payload["devices"][0]

    assert payload["format"] == "enocean-project"
    assert payload["format_version"] == 1
    assert payload["generated_at"] == "2026-07-02T10:15:00+00:00"
    assert payload["source"] == {
        "project_id": "house",
        "base_topic": "enocean",
        "api_version": "v1",
    }
    assert device["id"] == "living_room"
    assert device["display_name"] == "Living Room Sensor"
    assert device["capabilities"] == {
        "readable": True,
        "writable": True,
        "channels_count": 1,
        "messages_count": 1,
    }
    assert device["channels"][0]["kind"] == "channel"
    assert device["channels"][0]["obs"]["suggested_binding_direction"] == "SOURCE"
    assert device["messages"][0]["kind"] == "message"
    assert device["messages"][0]["obs"]["suggested_binding_direction"] == "TARGET"
