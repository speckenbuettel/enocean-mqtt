from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute

from enocean_mqtt.devices.csv_format import import_csv
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.web_api.device_management_routes import (
    _import_preview,
    create_device_management_router,
)


def _endpoint(router, path: str, method: str) -> Callable[..., dict[str, Any]]:
    for route in router.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in (route.methods or set())
        ):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


def _request(*roles: str) -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.web_roles = set(roles)
    return request


def _router(tmp_path, dispatched):
    devices_file = tmp_path / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "059AB393",
                        "device_name": "Window",
                        "alias": "window",
                        "eep": "A5-14-0A",
                        "profile": "A5-14-0A",
                        "communication": "bidirectional_eep",
                        "sender_id": "FF92A703",
                        "metadata": {
                            "teach_in_receivers": [
                                {
                                    "receiver": "BSC",
                                    "status": "user_confirmed",
                                    "confirmed_at": "2026-08-29T00:00:00.000+00:00",
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    virtual_file = tmp_path / "virtual-devices.json"
    virtual_file.write_text(
        json.dumps(
            {
                "virtual_devices": [
                    {
                        "virtual_device_id": "weather",
                        "sender_id": "FF92A701",
                        "eep": "A5-04-02",
                        "channels": ["temperature"],
                        "teach_in_method": "4bs_teach_in",
                        "teach_in_telegram": {
                            "rorg": "A5",
                            "payload": "00000000",
                            "sender_id": "FF92A701",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    database = tmp_path / "telegrams.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE telegrams (
                telegram_id INTEGER PRIMARY KEY,
                sender_id TEXT,
                timestamp_unix REAL,
                direction TEXT,
                rorg BLOB,
                data BLOB,
                raw_telegram BLOB,
                rssi_dbm INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO telegrams
                (sender_id, timestamp_unix, direction, rorg, data, raw_telegram, rssi_dbm)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "059AB393",
                9999999999.0,
                "rx",
                bytes.fromhex("A5"),
                bytes.fromhex("8F000008"),
                bytes.fromhex("A58F000008059AB39300"),
                -70,
            ),
        )
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"metrics": {"active_device_window_seconds": 300}}),
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "A5-14-0A.json").write_text("{}", encoding="utf-8")

    def dispatcher(command, payload):
        dispatched.append((command, payload))
        return {"status": "accepted", "command": command}

    return create_device_management_router(
        devices_file=devices_file,
        virtual_devices_file=virtual_file,
        sqlite_database=database,
        config_file=config_file,
        eep_registry_directory=profiles,
        runtime_command_dispatcher_provider=lambda: dispatcher,
        unknown_devices_provider=lambda **_kwargs: {
            "unknown_devices": [
                {
                    "sender_id": "05000001",
                    "rorg": "A5",
                    "telegrams": 2,
                    "last_seen": "2026-08-29T00:00:00.000+00:00",
                    "last_raw_telegram": "A5 00 00 00 00 05 00 00 01 00",
                }
            ],
            "source": "test",
            "issues": [],
        },
    )


def test_management_projection_combines_registries_activity_and_unknowns(tmp_path) -> None:
    dispatched: list[tuple[str, dict[str, Any] | None]] = []
    router = _router(tmp_path, dispatched)

    payload = _endpoint(router, "/api/v1/device-management", "GET")(
        request=_request("admin")
    )

    assert payload["can_write"] is True
    assert payload["counts"] == {
        "devices": 1,
        "unknown_devices": 1,
        "virtual_devices": 1,
        "active_devices": 1,
    }
    physical = payload["physical_devices"][0]
    assert physical["tx_capable"] is True
    assert physical["last_telegram"]["raw_telegram"] == "A5 8F 00 00 08 05 9A B3 93 00"
    assert physical["teach_in_receivers"][0]["receiver"] == "BSC"


def test_management_mutations_dispatch_existing_runtime_commands(tmp_path) -> None:
    dispatched: list[tuple[str, dict[str, Any] | None]] = []
    router = _router(tmp_path, dispatched)

    _endpoint(
        router,
        "/api/v1/device-management/physical/{device_id}/teach-in",
        "POST",
    )(device_id="059AB393", payload=None)
    _endpoint(
        router,
        "/api/v1/device-management/virtual/{virtual_device_id}/teach-in",
        "POST",
    )(virtual_device_id="weather")

    assert dispatched == [
        ("device.teach_in", {"device_id": "059AB393"}),
        ("virtual_device.teach_in", {"virtual_device_id": "weather"}),
    ]


def test_manual_receiver_confirmation_is_persisted_through_device_import(tmp_path) -> None:
    dispatched: list[tuple[str, dict[str, Any] | None]] = []
    router = _router(tmp_path, dispatched)

    result = _endpoint(
        router,
        "/api/v1/device-management/physical/{device_id}/teach-in-confirmations",
        "POST",
    )(device_id="059AB393", payload={"receiver": "Home Assistant"})

    assert result["status"] == "confirmed"
    command, payload = dispatched[-1]
    assert command == "device.import"
    assert payload is not None
    confirmations = payload["device"]["metadata"]["teach_in_receivers"]
    assert {item["receiver"] for item in confirmations} == {"BSC", "Home Assistant"}
    assert confirmations[-1]["status"] == "user_confirmed"


def test_csv_preview_reports_new_and_updated_devices(tmp_path) -> None:
    devices_file = tmp_path / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "059AB393",
                        "device_name": "Existing",
                        "eep": "A5-14-0A",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    preview = _import_preview(
        "device_id,device_name,eep,communication,enabled\n"
        "059AB393,Updated,A5-14-0A,unidirectional,true\n"
        "05000001,New,A5-04-02,unidirectional,true\n",
        devices_file,
    )

    assert preview["valid"] is True
    assert preview["created"] == 1
    assert preview["updated"] == 1
    assert preview["total_after_import"] == 2


def test_legacy_csv_import_preserves_receiver_confirmations(tmp_path) -> None:
    devices_file = tmp_path / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "059AB393",
                        "device_name": "Existing",
                        "eep": "A5-14-0A",
                        "enabled": False,
                        "metadata": {
                            "teach_in_receivers": [
                                {
                                    "receiver": "BSC",
                                    "status": "user_confirmed",
                                    "confirmed_at": "2026-08-29T00:00:00.000+00:00",
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    csv_file = tmp_path / "devices.csv"
    csv_file.write_text(
        "device_id,device_name,eep\n059AB393,Updated,A5-14-0A\n",
        encoding="utf-8",
    )

    registry = import_csv(
        csv_file,
        existing_registry=DeviceRegistry.from_json(devices_file),
    )

    imported = registry.get_by_device_id("059AB393")
    assert imported is not None
    assert imported.enabled is False
    assert imported.metadata["teach_in_receivers"][0]["receiver"] == "BSC"
