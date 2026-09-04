import json
import subprocess
from unittest.mock import patch

from enocean_mqtt.web_api.ui_routes import (
    _configured_enocean_directions,
    _dashboard_interfaces,
    _devices_by_sender,
    _journal_entries,
    _last_rx_activity,
    _overall_health,
)


def test_journal_entries_normalizes_text_and_json_formats() -> None:
    records = [
        {
            "MESSAGE": (
                "2026-08-28 12:32:20,710 WARNING "
                "enocean_mqtt.mqtt.client: connection lost"
            ),
            "PRIORITY": "6",
        },
        {
            "MESSAGE": json.dumps(
                {
                    "timestamp": "2026-08-28T10:35:17.758Z",
                    "level": "ERROR",
                    "logger": "enocean_mqtt.test",
                    "message": "structured",
                    "exception": "Traceback: example",
                }
            ),
            "PRIORITY": "6",
        },
    ]
    result = subprocess.CompletedProcess([], 0, "\n".join(json.dumps(item) for item in records), "")

    with patch("enocean_mqtt.web_api.ui_routes.subprocess.run", return_value=result):
        payload = _journal_entries(limit=10)

    assert [entry["level"] for entry in payload["entries"]] == ["WARNING", "ERROR"]
    assert payload["entries"][0]["logger"] == "enocean_mqtt.mqtt.client"
    assert payload["entries"][0]["message"] == "connection lost"
    assert payload["entries"][1]["message"] == "structured\nTraceback: example"


class _RuntimeServiceWithDevices:
    def get_devices(self) -> dict:
        return {
            "devices": [
                {
                    "device_id": "059AB393",
                    "sender_id": None,
                    "device_name": "Fenstersensor Gästebad",
                }
            ]
        }


def _health(**overrides: bool | str) -> dict:
    values: dict[str, bool | str] = {
        "online": True,
        "runtime_mode": "live",
        "mqtt_connected": True,
        "enocean_connected": True,
        "api_enabled": True,
        "api_operational": True,
        "sqlite_enabled": True,
        "sqlite_operational": True,
    }
    values.update(overrides)
    return _overall_health(**values)  # type: ignore[arg-type]


def test_overall_health_is_green_when_all_enabled_services_are_operational() -> None:
    assert _health()["level"] == "ok"


def test_overall_health_ignores_disabled_sqlite() -> None:
    payload = _health(sqlite_enabled=False, sqlite_operational=False)

    assert payload["level"] == "ok"
    assert payload["checks"][-1]["state"] == "ignored"


def test_overall_health_uses_documented_severity_precedence() -> None:
    assert _health(mqtt_connected=False)["level"] == "warn"
    assert _health(mqtt_connected=False, enocean_connected=False)["level"] == "problem"


def test_dashboard_reads_rx_and_effective_tx_from_enocean_config() -> None:
    config = {
        "enocean": {
            "tx_enabled": True,
            "interfaces": [
                {
                    "interface_id": "usb300_01",
                    "enabled": True,
                    "tx_enabled": True,
                }
            ],
        }
    }

    assert _configured_enocean_directions(config, "usb300_01") == {
        "rx_enabled": True,
        "tx_enabled": True,
    }


def test_dashboard_projects_named_interfaces_for_selection() -> None:
    interfaces = {
        "fam14_01": {"connected": False, "base_id": "FF800000"},
        "usb300_01": {"connected": True, "base_id": "FF92A700"},
    }
    config = {
        "enocean": {
            "tx_enabled": True,
            "interfaces": [
                {"interface_id": "fam14_01", "enabled": True, "tx_enabled": False},
                {"interface_id": "usb300_01", "enabled": True, "tx_enabled": True},
            ],
        }
    }

    assert _dashboard_interfaces(
        interfaces,
        {},
        config,
    ) == [
        {
            "interface_id": "fam14_01",
            "connected": False,
            "base_id": "FF800000",
            "transport_status": None,
            "rx_enabled": True,
            "tx_enabled": False,
        },
        {
            "interface_id": "usb300_01",
            "connected": True,
            "base_id": "FF92A700",
            "transport_status": None,
            "rx_enabled": True,
            "tx_enabled": True,
        },
    ]


def test_last_rx_activity_resolves_known_sender_name() -> None:
    activity = _last_rx_activity(
        {
            "last_rx": {
                "raw_telegram": "AABBCC",
                "sender_id": "05A3CADA",
            }
        },
        {
            "05A3CADA": {
                "sender_id": "05A3CADA",
                "device_name": "Living room sensor",
            }
        },
    )

    assert activity["raw_telegram"] == "AABBCC"
    assert activity["sender_name"] == "Living room sensor"
    assert activity["decoded_tooltip"] == "Decode unavailable"


def test_device_lookup_uses_physical_device_id_as_sender_id() -> None:
    indexed = _devices_by_sender(_RuntimeServiceWithDevices())  # type: ignore[arg-type]

    assert indexed["059AB393"]["device_name"] == "Fenstersensor Gästebad"
