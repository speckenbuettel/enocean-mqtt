"""Tests for semantic API device projection."""

from __future__ import annotations

import json

from enocean_mqtt.datapoints import Datapoint, DatapointRegistry, DatapointSource
from enocean_mqtt.devices.projection import ApiDeviceRegistry


def test_physical_device_projects_api_device_with_datapoint_flags(tmp_path):
    devices_file = tmp_path / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "0185286B",
                        "alias": "living_room_thermostat",
                        "device_name": "Living Room Thermostat",
                        "manufacturer": "Example",
                        "model": "Heating Controller",
                        "profile": "A5-20-06",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    datapoint_registry = DatapointRegistry(
        datapoints=[
            Datapoint(
                id="living_room_thermostat.temperature",
                device_id="living_room_thermostat",
                name="temperature",
                display_name=None,
                semantic_role=None,
                object_type=None,
                data_type="float",
                unit=None,
                readable=True,
                writable=False,
                direction="read",
                stateful=True,
                source=DatapointSource(
                    source_type="physical_device",
                    collection="channels",
                    name="temperature",
                    profile="A5-20-06",
                ),
            ),
            Datapoint(
                id="living_room_thermostat.temperature_setpoint",
                device_id="living_room_thermostat",
                name="temperature_setpoint",
                display_name=None,
                semantic_role=None,
                object_type=None,
                data_type="float",
                unit=None,
                readable=False,
                writable=True,
                direction="write",
                stateful=True,
                source=DatapointSource(
                    source_type="physical_device",
                    collection="messages",
                    name="temperature_setpoint",
                    profile="A5-20-06",
                ),
            ),
        ]
    )

    registry = ApiDeviceRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=None,
        datapoint_registry=datapoint_registry,
    )

    device = registry.to_api_dict()["devices"][0]

    assert device["id"] == "living_room_thermostat"
    assert device["source_type"] == "physical_device"
    assert device["device_id"] == "0185286B"
    assert device["readable"] is True
    assert device["writable"] is True
    assert device["datapoints_count"] == 2
    assert device["datapoints_url"] == (
        "/api/v1/devices/living_room_thermostat/datapoints"
    )


def test_virtual_device_projects_api_device_with_writable_flag(tmp_path):
    devices_file = tmp_path / "devices.json"
    devices_file.write_text('{"devices": []}', encoding="utf-8")
    virtual_devices_file = tmp_path / "virtual-devices.json"
    virtual_devices_file.write_text(
        json.dumps(
            {
                "virtual_devices": [
                    {
                        "virtual_device_id": "weather_station",
                        "sender_id": "05000001",
                        "eep": "A5-04-02",
                        "channels": ["temperature"],
                        "metadata": {"manufacturer": "Example"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    datapoint_registry = DatapointRegistry(
        datapoints=[
            Datapoint(
                id="weather_station.temperature",
                device_id="weather_station",
                name="temperature",
                display_name=None,
                semantic_role="climate.temperature.measurement",
                object_type="measurement",
                data_type="float",
                unit="°C",
                readable=False,
                writable=True,
                direction="write",
                stateful=True,
                source=DatapointSource(
                    source_type="virtual_device",
                    collection="virtual_channels",
                    name="temperature",
                    profile="A5-04-02",
                    virtual_device_id="weather_station",
                    sender_id="05000001",
                ),
            )
        ]
    )

    registry = ApiDeviceRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=virtual_devices_file,
        datapoint_registry=datapoint_registry,
    )

    device = registry.to_api_dict()["devices"][0]

    assert device["id"] == "weather_station"
    assert device["source_type"] == "virtual_device"
    assert device["virtual_device_id"] == "weather_station"
    assert device["sender_id"] == "05000001"
    assert device["readable"] is False
    assert device["writable"] is True
    assert device["datapoints_count"] == 1


def test_device_without_datapoints_still_appears(tmp_path):
    devices_file = tmp_path / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "01020304",
                        "device_name": "Unknown Device",
                        "profile": "A5-99-99",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    datapoint_registry = DatapointRegistry(datapoints=[])

    registry = ApiDeviceRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=None,
        datapoint_registry=datapoint_registry,
    )

    device = registry.to_api_dict()["devices"][0]

    assert device["id"] == "01020304"
    assert device["readable"] is False
    assert device["writable"] is False
    assert device["datapoints_count"] == 0
