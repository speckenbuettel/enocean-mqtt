"""Tests for API-facing semantic device projection."""

from __future__ import annotations

import json

from enocean_mqtt.datapoints import DatapointRegistry, projection as datapoint_projection
from enocean_mqtt.devices.projection import ApiDeviceRegistry
from enocean_mqtt.eep.models import ChannelDefinition, EEPDefinition, MessageDefinition


def test_physical_device_projection_uses_datapoint_capabilities(
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
                        "manufacturer": "Example",
                        "model": "Controller",
                        "profile": "A5-20-06",
                        "metadata": {"room": "living_room"},
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

    datapoints = DatapointRegistry.from_config_files(devices_file=devices_file)
    registry = ApiDeviceRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=None,
        datapoint_registry=datapoints,
    )

    payload = registry.to_api_dict()

    assert payload["count"] == 1
    assert payload["devices"][0] == {
        "id": "living_room_thermostat",
        "source_type": "physical_device",
        "device_id": "0185286B",
        "alias": "living_room_thermostat",
        "device_name": "Living Room Thermostat",
        "manufacturer": "Example",
        "model": "Controller",
        "profile": "A5-20-06",
        "readable": True,
        "writable": True,
        "datapoints_count": 2,
        "datapoints_url": "/api/v1/devices/living_room_thermostat/datapoints",
        "metadata": {"room": "living_room"},
    }


def test_virtual_device_projection_uses_virtual_identity(
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
                        "description": "Virtual weather station",
                        "metadata": {
                            "device_name": "Weather Station",
                            "manufacturer": "enocean-mqtt",
                            "model": "virtual",
                        },
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
                )
            ],
        ),
    )

    datapoints = DatapointRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=virtual_devices_file,
    )
    registry = ApiDeviceRegistry.from_config_files(
        devices_file=devices_file,
        virtual_devices_file=virtual_devices_file,
        datapoint_registry=datapoints,
    )

    device = registry.get("weather_station")

    assert device is not None
    assert device.to_api_dict() == {
        "id": "weather_station",
        "source_type": "virtual_device",
        "virtual_device_id": "weather_station",
        "sender_id": "05000001",
        "alias": "weather_station",
        "device_name": "Weather Station",
        "description": "Virtual weather station",
        "manufacturer": "enocean-mqtt",
        "model": "virtual",
        "eep": "A5-04-02",
        "profile": "A5-04-02",
        "enabled": True,
        "readable": False,
        "writable": True,
        "datapoints_count": 1,
        "datapoints_url": "/api/v1/devices/weather_station/datapoints",
        "metadata": {
            "device_name": "Weather Station",
            "manufacturer": "enocean-mqtt",
            "model": "virtual",
        },
    }
