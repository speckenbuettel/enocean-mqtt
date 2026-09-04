"""Tests for semantic datapoint projection."""

from __future__ import annotations

import json

from enocean_mqtt.datapoints import DatapointRegistry, projection as datapoint_projection
from enocean_mqtt.eep.models import ChannelDefinition, EEPDefinition, MessageDefinition


def test_physical_device_projects_readable_and_writable_datapoints(
    tmp_path,
    monkeypatch,
):
    devices_file = tmp_path / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "0185286B",
                        "alias": "living_room_thermostat",
                        "device_name": "Living Room Thermostat",
                        "profile": "A5-20-06",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        datapoint_projection,
        "load_eep_definition",
        lambda profile: EEPDefinition(
            eep=profile,
            rorg="A5",
            func="20",
            type="06",
            channels=[
                ChannelDefinition(
                    name="temperature",
                    data_type="float",
                    semantic_role="climate.temperature.measurement",
                    object_type="measurement",
                    unit="°C",
                )
            ],
            messages=[
                MessageDefinition(
                    name="temperature_setpoint",
                    data_type="float",
                    semantic_role="climate.temperature.setpoint",
                    object_type="setpoint",
                    unit="°C",
                )
            ],
        ),
    )

    registry = DatapointRegistry.from_config_files(devices_file=devices_file)

    datapoints = registry.to_api_dict()["datapoints"]

    assert [item["id"] for item in datapoints] == [
        "living_room_thermostat.temperature",
        "living_room_thermostat.temperature_setpoint",
    ]
    assert datapoints[0]["readable"] is True
    assert datapoints[0]["writable"] is False
    assert datapoints[0]["source"]["collection"] == "channels"
    assert datapoints[1]["readable"] is False
    assert datapoints[1]["writable"] is True
    assert datapoints[1]["source"]["collection"] == "messages"


def test_virtual_device_projects_enabled_channels_as_writable_datapoints(
    tmp_path,
    monkeypatch,
):
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
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        datapoint_projection,
        "load_eep_definition",
        lambda profile: EEPDefinition(
            eep=profile,
            rorg="A5",
            func="04",
            type="02",
            channels=[
                ChannelDefinition(
                    name="temperature",
                    data_type="float",
                    semantic_role="climate.temperature.measurement",
                    object_type="measurement",
                    unit="°C",
                ),
                ChannelDefinition(
                    name="humidity",
                    data_type="float",
                    semantic_role="climate.humidity.measurement",
                    object_type="measurement",
                    unit="%",
                ),
            ],
        ),
    )

    registry = DatapointRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=virtual_devices_file,
    )

    datapoints = registry.to_api_dict()["datapoints"]

    assert [item["id"] for item in datapoints] == [
        "weather_station.temperature"
    ]
    assert datapoints[0]["readable"] is False
    assert datapoints[0]["writable"] is True
    assert datapoints[0]["source"]["collection"] == "virtual_channels"
    assert datapoints[0]["source"]["virtual_device_id"] == "weather_station"
