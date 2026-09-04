import pytest

from enocean_mqtt.config import ConfigurationError, validate_runtime_config


@pytest.fixture
def valid_config() -> dict:
    return {
        "application": {
            "input_mode": "simulation",
        },
        "mqtt": {
            "host": "127.0.0.1",
            "port": 1883,
            "client_id": "enocean-mqtt",
            "base_topic": "enocean",
        },
        "simulation": {
            "interval_seconds": 5,
        },
        "status": {
            "availability_topic": "status/availability",
            "health_topic": "status/health",
            "last_will": {
                "online_payload": "online",
                "offline_payload": "offline",
                "retain": True,
                "qos": 1,
            },
        },
        "files": {
            "devices_file": "config/devices.json",
        },
    }



def test_missing_required_section(valid_config: dict) -> None:
    del valid_config["mqtt"]

    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(valid_config)

    assert "Missing required configuration sections" in str(exc.value)



def test_empty_mqtt_host(valid_config: dict) -> None:
    valid_config["mqtt"]["host"] = ""

    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(valid_config)

    assert "MQTT host must not be empty" in str(exc.value)



def test_invalid_mqtt_port(valid_config: dict) -> None:
    valid_config["mqtt"]["port"] = 70000

    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(valid_config)

    assert "MQTT port must be between 1 and 65535" in str(exc.value)



def test_invalid_input_mode(valid_config: dict) -> None:
    valid_config["application"]["input_mode"] = "serial"

    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(valid_config)

    assert "Unsupported input_mode" in str(exc.value)



def test_negative_simulation_interval(valid_config: dict) -> None:
    valid_config["simulation"]["interval_seconds"] = -1

    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(valid_config)

    assert "simulation.interval_seconds must be greater than zero" in str(exc.value)



def test_missing_devices_file(valid_config: dict) -> None:
    valid_config["files"]["devices_file"] = ""

    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(valid_config)

    assert "files.devices_file must not be empty" in str(exc.value)
