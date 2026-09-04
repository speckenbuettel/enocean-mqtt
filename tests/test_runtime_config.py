import json

import pytest
from pydantic import ValidationError

from enocean_mqtt.runtime_config import load_runtime_config


def _minimum_config(**updates) -> dict:
    config = {
        "mqtt": {
            "host": "127.0.0.1",
            "client_id": "enocean-mqtt-test",
            "base_topic": "enocean",
        },
        "enocean": {},
    }
    config.update(updates)
    return config


def _load(tmp_path, payload: dict):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return load_runtime_config(config_path)


def test_repository_example_matches_target_model() -> None:
    config = load_runtime_config("config/config.example.json")

    assert config.enocean.default_interface == "usb300"
    assert config.enocean.interfaces[0].tx_enabled is False
    assert config.mqtt.runtime_commands_enabled is True
    assert config.metrics.active_device_window_seconds == 86400
    assert config.logging.format == "text"


def test_runtime_config_loads_nested_enocean_interfaces(tmp_path) -> None:
    config = _load(
        tmp_path,
        _minimum_config(
            enocean={
                "default_interface": "usb300_01",
                "tx_enabled": True,
                "interfaces": [
                    {
                        "interface_id": "usb300_01",
                        "enabled": True,
                        "tx_enabled": True,
                        "device": "/dev/ttyAMA0",
                        "base_id": "FF800000",
                    }
                ],
            }
        ),
    )

    assert config.configured_interfaces()[0].device == "/dev/ttyAMA0"
    assert config.default_tx_base_id() == "FF800000"


def test_runtime_config_loads_base_id_from_sender_registry(tmp_path) -> None:
    registry_path = tmp_path / "sender-id-registry.json"
    registry_path.write_text(
        json.dumps({"interfaces": [{"interface_id": "usb300_01", "base_id": "FFAA8000"}]}),
        encoding="utf-8",
    )
    config = _load(
        tmp_path,
        _minimum_config(
            enocean={
                "default_interface": "usb300_01",
                "interfaces": [{"interface_id": "usb300_01", "device": "/dev/ttyUSB0"}],
            },
            paths={"sender_id_registry": str(registry_path)},
        ),
    )

    assert config.enocean.interfaces[0].base_id == "FFAA8000"
    assert config.default_tx_base_id() == "FFAA8000"


@pytest.mark.parametrize(
    "legacy_key",
    [
        "serial",
        "interfaces",
        "default_tx_interface_id",
        "runtime",
        "status",
        "busmonitor",
        "runtime_commands",
    ],
)
def test_runtime_config_rejects_legacy_top_level_fields(tmp_path, legacy_key) -> None:
    payload = _minimum_config()
    payload[legacy_key] = {}

    with pytest.raises(ValidationError):
        _load(tmp_path, payload)


def test_runtime_config_rejects_duplicate_interface_ids(tmp_path) -> None:
    payload = _minimum_config(
        enocean={
            "interfaces": [
                {"interface_id": "usb300", "device": "/dev/ttyUSB0"},
                {"interface_id": "usb300", "device": "/dev/ttyUSB1"},
            ]
        }
    )

    with pytest.raises(ValidationError, match="must be unique"):
        _load(tmp_path, payload)


def test_runtime_config_rejects_unknown_default_interface(tmp_path) -> None:
    payload = _minimum_config(enocean={"default_interface": "missing"})

    with pytest.raises(ValidationError, match="must reference"):
        _load(tmp_path, payload)


def test_runtime_config_rejects_renamed_default_interface_id(tmp_path) -> None:
    payload = _minimum_config(enocean={"default_interface_id": "usb300"})

    with pytest.raises(ValidationError, match="default_interface_id"):
        _load(tmp_path, payload)


def test_runtime_config_rejects_internal_serial_read_size(tmp_path) -> None:
    payload = _minimum_config(
        enocean={
            "interfaces": [
                {
                    "interface_id": "usb300",
                    "device": "/dev/ttyUSB0",
                    "read_size": 128,
                }
            ]
        }
    )

    with pytest.raises(ValidationError, match="read_size"):
        _load(tmp_path, payload)


def test_runtime_config_rejects_enabled_tls(tmp_path) -> None:
    payload = _minimum_config()
    payload["mqtt"]["tls"] = {"enabled": True}

    with pytest.raises(ValidationError, match="TLS is not implemented"):
        _load(tmp_path, payload)


def test_runtime_config_normalizes_logging_level(tmp_path) -> None:
    config = _load(tmp_path, _minimum_config(logging={"level": "debug", "format": "json"}))

    assert config.logging.level == "DEBUG"
    assert config.logging.format == "json"


def test_runtime_config_rejects_invalid_reconnect_order(tmp_path) -> None:
    payload = _minimum_config()
    payload["mqtt"]["reconnect"] = {
        "initial_delay_seconds": 60,
        "max_delay_seconds": 5,
    }

    with pytest.raises(ValidationError, match="must not exceed"):
        _load(tmp_path, payload)
