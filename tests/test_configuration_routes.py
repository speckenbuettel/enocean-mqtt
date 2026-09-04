from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any, cast

from fastapi.routing import APIRoute

from enocean_mqtt.web_api.configuration_routes import (
    _build_schema,
    create_configuration_router,
)


def _config(password_file, token_file) -> dict[str, Any]:
    return {
        "application": {"name": "enocean-mqtt", "timezone": "Europe/Berlin"},
        "enocean": {
            "default_interface": "usb300",
            "tx_enabled": False,
            "interfaces": [
                {
                    "interface_id": "usb300",
                    "enabled": True,
                    "tx_enabled": False,
                    "type": "serial_esp3",
                    "device": "/dev/ttyUSB0",
                }
            ],
        },
        "mqtt": {
            "host": "localhost",
            "client_id": "test",
            "base_topic": "enocean",
            "password_file": str(password_file),
        },
        "web_api": {
            "authentication": {"enabled": True, "token_file": str(token_file)}
        },
    }


def _endpoint(router, path: str, method: str) -> Callable[..., dict[str, Any]]:
    for route in router.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in (route.methods or set())
        ):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


def _node(schema: dict[str, Any], path: str) -> dict[str, Any]:
    pending = list(schema["sections"])
    while pending:
        node = pending.pop()
        if node["path"] == path:
            return cast(dict[str, Any], node)
        pending.extend(node.get("children", []))
    raise AssertionError(f"Schema node not found: {path}")


def test_settings_schema_exposes_specialized_controls_without_secrets(tmp_path) -> None:
    password_file = tmp_path / "mqtt-password"
    password_file.write_text("secret", encoding="utf-8")
    token_file = tmp_path / "api-tokens.json"
    token_file.write_text(
        json.dumps({"tokens": [{"name": "Admin", "token": "hidden", "roles": ["admin"]}]}),
        encoding="utf-8",
    )
    config_file = tmp_path / "config.json"
    config = _config(password_file, token_file)

    schema = _build_schema(config, config_file)

    assert _node(schema, "application.timezone")["control"] == "select"
    assert "Europe/Berlin" in _node(schema, "application.timezone")["options"]
    assert _node(schema, "enocean.interfaces")["control"] == "interfaces"
    assert _node(schema, "enocean.default_interface")["control"] == "default-interface"
    assert _node(schema, "mqtt.password_file")["configured"] is True
    token_node = _node(schema, "web_api.authentication.token_file")
    assert token_node["tokens"] == [{"name": "Admin", "roles": ["admin"]}]
    assert "hidden" not in json.dumps(schema)


def test_settings_save_writes_mqtt_password_to_secret_file(tmp_path) -> None:
    password_file = tmp_path / "mqtt-password"
    token_file = tmp_path / "api-tokens.json"
    config_file = tmp_path / "config.json"
    config = _config(password_file, token_file)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    endpoint = _endpoint(create_configuration_router(config_file), "/api/v1/config", "PUT")

    result = endpoint({"config": config, "mqtt_password": "new-secret"})

    assert result["saved"] is True
    assert password_file.read_text(encoding="utf-8") == "new-secret"
    assert "new-secret" not in config_file.read_text(encoding="utf-8")


def test_settings_can_create_list_and_delete_api_tokens(tmp_path) -> None:
    password_file = tmp_path / "mqtt-password"
    token_file = tmp_path / "api-tokens.json"
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_config(password_file, token_file)), encoding="utf-8")
    router = create_configuration_router(config_file)

    created = _endpoint(router, "/api/v1/config/api-tokens", "POST")(
        {"name": "OBS", "role": "read"}
    )
    assert len(base64.b64decode(created["token"], validate=True)) == 32
    assert _endpoint(router, "/api/v1/config/api-tokens", "GET")() == {
        "tokens": [{"name": "OBS", "roles": ["read"]}]
    }

    deleted = _endpoint(router, "/api/v1/config/api-tokens/{token_name}", "DELETE")(
        token_name="OBS"
    )
    assert deleted == {"deleted": True, "name": "OBS"}
    assert json.loads(token_file.read_text(encoding="utf-8")) == {"tokens": []}
