from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from enocean_mqtt.gateway.runtime_schema import RuntimeCommandValidationError
from enocean_mqtt.web_api import app as web_app
from enocean_mqtt.web_api.semantic_routes import create_semantic_router


@pytest.fixture(autouse=True)
def restore_runtime_command_dispatcher():
    previous_dispatcher = web_app.runtime_command_dispatcher

    try:
        yield
    finally:
        web_app.configure_runtime_command_dispatcher(previous_dispatcher)


def test_runtime_commands_are_exposed_for_discovery() -> None:
    web_app.configure_runtime_command_dispatcher(None)

    payload = web_app._runtime_commands_payload()

    command_names = {
        command["name"]
        for command in payload["commands"]
    }

    assert "gateway.exit" in command_names
    assert "device.teach_in" in command_names
    assert "devices.export" in command_names
    assert "virtual_device.teach_in" in command_names
    assert "replay.start" in command_names
    assert "interface.network_bridge.start" in command_names
    assert "interface.network_bridge.stop" in command_names
    assert payload["dispatch"]["http_available"] is False
    assert payload["count"] == len(payload["commands"])


def test_runtime_commands_report_http_dispatch_available() -> None:
    web_app.configure_runtime_command_dispatcher(
        lambda command, payload: {
            "status": "accepted",
            "command": command,
        }
    )

    payload = web_app._runtime_commands_payload()

    assert payload["dispatch"]["http_available"] is True
    assert payload["issues"] == []


def test_unknown_devices_returns_warning_when_sqlite_is_missing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        web_app,
        "SQLITE_DATABASE",
        tmp_path / "missing.sqlite",
    )

    payload = web_app._unknown_devices_payload(lookback_limit=100)

    assert payload["unknown_devices"] == []
    assert payload["count"] == 0
    assert payload["source"] == "sqlite"
    assert payload["issues"][0]["severity"] == "warning"


def _registered_routes(routes: Sequence[object]) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in routes
        if isinstance(route, APIRoute)
        for method in getattr(route, "methods", set())
    }


def test_interface_network_bridge_routes_are_registered() -> None:
    routes = _registered_routes(web_app.app.routes)

    assert (
        "POST",
        "/api/v1/interfaces/{interface_id}/network-bridge/start",
    ) in routes
    assert (
        "POST",
        "/api/v1/interfaces/{interface_id}/network-bridge/stop",
    ) in routes
    assert (
        "POST",
        "/api/v1/interfaces/{interface_id}/network-bridge/restart",
    ) in routes


def test_documented_workflow_paths_are_registered() -> None:
    app_routes = _registered_routes(web_app.app.routes)
    semantic_routes = _registered_routes(
        create_semantic_router(web_app.get_runtime_service).routes,
    )

    expected_app_routes = {
        ("POST", "/api/v1/runtime/commands/{command_name}"),
        ("GET", "/api/v1/profile-drafts"),
        ("POST", "/api/v1/profile-drafts"),
        ("GET", "/api/v1/profile-drafts/{draft_id}"),
        ("PATCH", "/api/v1/profile-drafts/{draft_id}"),
        ("POST", "/api/v1/profile-drafts/{draft_id}/validate"),
        ("POST", "/api/v1/profile-drafts/{draft_id}/approve"),
        ("DELETE", "/api/v1/profile-drafts/{draft_id}"),
    }
    expected_semantic_routes = {
        ("POST", "/api/v1/devices"),
        ("POST", "/api/v1/devices/import"),
        ("GET", "/api/v1/devices/export"),
        ("POST", "/api/v1/devices/{device_id}/republish"),
        ("POST", "/api/v1/devices/{device_id}/teach-in"),
        ("DELETE", "/api/v1/devices/{device_id}"),
        ("POST", "/api/v1/datapoints/{datapoint_id}/value"),
        ("GET", "/api/v1/datapoints/tags"),
    }

    assert expected_app_routes <= app_routes
    assert expected_semantic_routes <= semantic_routes


def test_runtime_command_dispatch_returns_503_without_dispatcher() -> None:
    web_app.configure_runtime_command_dispatcher(None)

    with pytest.raises(HTTPException) as exc_info:
        web_app.post_runtime_command(
            command_name="gateway.exit",
            payload={"transaction_id": "test"},
        )

    assert exc_info.value.status_code == 503
    assert "unavailable" in str(exc_info.value.detail)


def test_runtime_command_dispatch_uses_configured_dispatcher() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def dispatch(
        command: str,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        calls.append((command, payload))
        return {
            "status": "accepted",
            "command": command,
        }

    web_app.configure_runtime_command_dispatcher(dispatch)

    payload = web_app.post_runtime_command(
        command_name="gateway.republish",
        payload={"transaction_id": "test"},
    )

    assert payload == {
        "status": "accepted",
        "command": "gateway.republish",
    }
    assert calls == [
        (
            "gateway.republish",
            {"transaction_id": "test"},
        )
    ]


def test_runtime_command_validation_error_maps_to_http_error() -> None:
    def dispatch(
        command: str,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        raise RuntimeCommandValidationError(
            "missing_argument",
            "Missing required argument",
            command=command,
            argument="capture_file",
        )

    web_app.configure_runtime_command_dispatcher(dispatch)

    with pytest.raises(HTTPException) as exc_info:
        web_app.post_runtime_command(
            command_name="replay.start",
            payload={},
        )

    assert exc_info.value.status_code == 400
    assert "missing_argument" in str(exc_info.value.detail)
