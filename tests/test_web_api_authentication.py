from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from enocean_mqtt.web_api import app as web_app


@pytest.fixture(autouse=True)
def restore_api_authentication_config():
    previous_enabled = web_app.api_authentication_config.enabled
    previous_token_file = web_app.api_authentication_config.token_file

    try:
        yield
    finally:
        web_app.configure_api_authentication(
            enabled=previous_enabled,
            token_file=previous_token_file,
        )


def test_api_token_file_loads_tokens_and_admin_implies_read(tmp_path) -> None:
    token_file = tmp_path / "api-tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "name": "Development",
                        "token": "cp+U7viWR0TAAu2m0dJk1cP/SUET9dvQw/Oz7i/UjWI=",
                        "roles": ["admin"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    web_app.configure_api_authentication(
        enabled=True,
        token_file=token_file,
    )

    tokens = web_app._load_api_tokens()

    assert len(tokens) == 1
    assert tokens[0].name == "Development"
    assert tokens[0].roles == {"admin", "read"}


def test_api_token_file_rejects_unknown_roles(tmp_path) -> None:
    token_file = tmp_path / "api-tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "name": "Broken",
                        "token": "BkdrGWVwba6okIGgCFdjIOYAA26eAppZSE8to/JyDTg=",
                        "roles": ["superuser"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    web_app.configure_api_authentication(
        enabled=True,
        token_file=token_file,
    )

    with pytest.raises(HTTPException) as exc_info:
        web_app._load_api_tokens()

    assert exc_info.value.status_code == 503


def test_api_token_file_rejects_non_base64_tokens(tmp_path) -> None:
    token_file = tmp_path / "api-tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "name": "Broken",
                        "token": "not-a-base64-token",
                        "roles": ["read"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    web_app.configure_api_authentication(
        enabled=True,
        token_file=token_file,
    )

    with pytest.raises(HTTPException) as exc_info:
        web_app._load_api_tokens()

    assert exc_info.value.status_code == 503
    assert "Base64" in str(exc_info.value.detail)


def test_api_token_file_rejects_short_base64_tokens(tmp_path) -> None:
    token_file = tmp_path / "api-tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "name": "Short",
                        "token": "c2hvcnQ=",
                        "roles": ["read"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    web_app.configure_api_authentication(
        enabled=True,
        token_file=token_file,
    )

    with pytest.raises(HTTPException) as exc_info:
        web_app._load_api_tokens()

    assert exc_info.value.status_code == 503
    assert "32 bytes" in str(exc_info.value.detail)


def test_required_api_role_maps_safe_methods_to_read() -> None:
    assert web_app._required_api_role("GET") == "read"
    assert web_app._required_api_role("HEAD") == "read"
    assert web_app._required_api_role("OPTIONS") == "read"
    assert web_app._required_api_role("POST") == "admin"


def test_api_v1_openapi_schema_exposes_bearer_auth() -> None:
    payload = web_app.get_api_v1_openapi()

    assert "/api/v1/openapi.json" in payload["paths"]
    assert (
        payload["components"]["securitySchemes"]["BearerAuth"]
        == web_app.OPENAPI_SECURITY_SCHEME
    )
    assert payload["security"] == [{"BearerAuth": []}]


def test_root_redirects_to_busmonitor_ui() -> None:
    response = web_app.root()

    assert response.headers["location"] == "/busmonitor"
