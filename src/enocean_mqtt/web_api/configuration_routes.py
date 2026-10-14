"""Configuration API routes for the Web UI and external clients."""

from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from enocean_mqtt.notifications import (
    Notification,
    NotificationError,
    PushoverClient,
    validate_token,
)
from enocean_mqtt.runtime_config import NotificationsConfig, RuntimeConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_FILE = PROJECT_ROOT / "config" / "config.json"

_SELECT_OPTIONS: dict[str, list[str]] = {
    "application.timezone": sorted(available_timezones()),
    "topics.device_topic_identifier": ["device_id", "alias", "both"],
    "logging.level": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "logging.format": ["text", "json"],
}
_API_TOKEN_ROLES = {"read", "admin"}


def create_configuration_router(
    config_file: Path = CONFIG_FILE,
) -> APIRouter:
    """Create read/validate/write routes for ``config.json``.

    Authorization remains the responsibility of the global API middleware:
    GET requires ``read`` and mutating requests require ``admin``.
    """

    router = APIRouter()

    @router.get("/api/v1/config")
    def get_configuration(request: Request) -> dict[str, Any]:
        config = _load_configuration(config_file)
        return {
            "config": config,
            "schema": _build_schema(config, config_file),
            "can_write": "admin" in getattr(request.state, "web_roles", set()),
            "restart_required_on_change": True,
        }

    @router.post("/api/v1/config/validate")
    def validate_configuration(payload: dict[str, Any]) -> dict[str, Any]:
        config = _extract_config_payload(payload)
        _validate_configuration(config)
        return {
            "valid": True,
            "restart_required": True,
        }

    @router.put("/api/v1/config")
    def put_configuration(payload: dict[str, Any]) -> dict[str, Any]:
        config = _extract_config_payload(payload)
        _validate_configuration(config)
        pushover = RuntimeConfig.model_validate(config).notifications.pushover
        token_writes: list[tuple[Path, str]] = []
        for name in ("user_token", "api_token"):
            value = payload.get(f"pushover_{name}")
            if value is not None:
                try:
                    if not isinstance(value, str):
                        raise NotificationError("Pushover token must be a string")
                    token_writes.append((
                        _resolve_path(getattr(pushover, f"{name}_file"), config_file),
                        validate_token(value),
                    ))
                except NotificationError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from None
        mqtt_password = payload.get("mqtt_password")
        if mqtt_password is not None:
            if not isinstance(mqtt_password, str) or not mqtt_password:
                raise HTTPException(status_code=422, detail="MQTT password must not be empty")
            password_file = config.get("mqtt", {}).get("password_file")
            if not isinstance(password_file, str) or not password_file:
                raise HTTPException(status_code=422, detail="MQTT password_file is not configured")
            _write_text_atomic(_resolve_path(password_file, config_file), mqtt_password)
        for token_path, token_value in token_writes:
            _write_text_atomic(token_path, token_value)
        _write_configuration_atomic(config_file, config)
        return {
            "saved": True,
            "valid": True,
            "restart_required": True,
            "config": config,
            "schema": _build_schema(config, config_file),
        }

    @router.post("/api/v1/notifications/pushover/send")
    def send_pushover(notification: Notification) -> dict[str, bool]:
        """Admin-only through global middleware; send using saved settings."""
        config = _load_configuration(config_file)
        _validate_configuration(config)
        settings = RuntimeConfig.model_validate(config).notifications.pushover
        settings = settings.model_copy(update={
            "user_token_file": str(_resolve_path(settings.user_token_file, config_file)),
            "api_token_file": str(_resolve_path(settings.api_token_file, config_file)),
        })
        if not settings.enabled:
            raise HTTPException(status_code=409, detail="Pushover is disabled")
        try:
            PushoverClient(settings).send(notification)
        except NotificationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return {"accepted_by_pushover": True}

    @router.get("/api/v1/config/api-tokens")
    def list_api_tokens() -> dict[str, Any]:
        config = _load_configuration(config_file)
        return {"tokens": _public_token_entries(_token_file(config, config_file))}

    @router.post("/api/v1/config/api-tokens")
    def create_api_token(payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        role = str(payload.get("role") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Token name must not be empty")
        if role not in _API_TOKEN_ROLES:
            raise HTTPException(status_code=422, detail="Token role must be read or admin")

        config = _load_configuration(config_file)
        token_file = _token_file(config, config_file)
        entries = _load_token_entries(token_file)
        if any(str(entry.get("name")) == name for entry in entries):
            raise HTTPException(status_code=409, detail="Token name already exists")

        token = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        entries.append({"name": name, "token": token, "roles": [role]})
        _write_json_atomic(token_file, {"tokens": entries})
        return {"name": name, "role": role, "token": token}

    @router.delete("/api/v1/config/api-tokens/{token_name}")
    def delete_api_token(token_name: str) -> dict[str, Any]:
        config = _load_configuration(config_file)
        token_file = _token_file(config, config_file)
        entries = _load_token_entries(token_file)
        remaining = [entry for entry in entries if str(entry.get("name")) != token_name]
        if len(remaining) == len(entries):
            raise HTTPException(status_code=404, detail="API token not found")
        _write_json_atomic(token_file, {"tokens": remaining})
        return {"deleted": True, "name": token_name}

    return router


def _load_configuration(config_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Configuration file not found") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Configuration file is invalid") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Configuration root must be an object")

    # Surface the optional section for existing installations without rewriting the file.
    if "notifications" not in payload:
        payload["notifications"] = NotificationsConfig().model_dump(mode="json")
    elif isinstance(payload["notifications"], dict):
        existing = payload["notifications"].get("pushover", {})
        if isinstance(existing, dict):
            payload["notifications"]["pushover"] = {
                **NotificationsConfig().pushover.model_dump(mode="json"), **existing,
            }
    return payload


def _extract_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("config", payload)
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=422, detail="Configuration root must be an object")
    return candidate


def _validate_configuration(config: dict[str, Any]) -> None:
    try:
        RuntimeConfig.model_validate(config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Configuration validation failed",
                "errors": exc.errors(include_url=False),
            },
        ) from exc


def _write_configuration_atomic(config_file: Path, config: dict[str, Any]) -> None:
    _write_text_atomic(config_file, json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _write_text_atomic(config_file: Path, serialized: str) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    mode: int | None = None
    try:
        mode = config_file.stat().st_mode & 0o777
    except OSError:
        pass

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_file.parent,
            prefix=f".{config_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)

        if mode is not None:
            temporary_path.chmod(mode)
        os.replace(temporary_path, config_file)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail="Failed to write configuration") from exc


def _build_schema(config: dict[str, Any], config_file: Path) -> dict[str, Any]:
    return {
        "version": 1,
        "sections": [
            _schema_node(key, value, key, config, config_file)
            for key, value in config.items()
        ],
    }


def _schema_node(
    key: str,
    value: Any,
    path: str,
    config: dict[str, Any],
    config_file: Path,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "key": key,
        "path": path,
        "label": _label(key),
    }

    if isinstance(value, dict):
        node["type"] = "object"
        node["children"] = [
            _schema_node(child_key, child_value, f"{path}.{child_key}", config, config_file)
            for child_key, child_value in value.items()
        ]
        return node

    if isinstance(value, list):
        node["type"] = "array"
        node["value"] = value
        if path == "enocean.interfaces":
            node["control"] = "interfaces"
        return node

    if isinstance(value, bool):
        node["type"] = "boolean"
    elif isinstance(value, int):
        node["type"] = "integer"
    elif isinstance(value, float):
        node["type"] = "number"
    elif value is None:
        node["type"] = "nullable"
    else:
        node["type"] = "string"

    node["value"] = value
    if path == "enocean.default_interface":
        node["control"] = "default-interface"
    elif path == "mqtt.password_file":
        node["control"] = "password-secret"
        node["label"] = "Password"
        node["configured"] = _resolve_path(str(value), config_file).is_file() if value else False
    elif path in {
        "notifications.pushover.user_token_file", "notifications.pushover.api_token_file",
    }:
        node["control"] = "pushover-secret"
        node["secret_name"] = f"pushover_{key.removesuffix('_file')}"
        node["label"] = "User Token" if key == "user_token_file" else "API Token"
        node["configured"] = _resolve_path(str(value), config_file).is_file() if value else False
    elif path == "web_api.authentication.token_file":
        node["control"] = "api-tokens"
        node["label"] = "API Tokens"
        node["roles"] = sorted(_API_TOKEN_ROLES)
        node["tokens"] = (
            _public_token_entries(_resolve_path(str(value), config_file)) if value else []
        )
    if path in _SELECT_OPTIONS:
        node["control"] = "select"
        node["options"] = _SELECT_OPTIONS[path]

    return node


def _resolve_path(value: str, config_file: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if config_file.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        return PROJECT_ROOT / path
    return config_file.parent / path


def _token_file(config: dict[str, Any], config_file: Path) -> Path:
    value = config.get("web_api", {}).get("authentication", {}).get("token_file")
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=422, detail="API token_file is not configured")
    return _resolve_path(value, config_file)


def _load_token_entries(token_file: Path) -> list[dict[str, Any]]:
    if not token_file.exists():
        return []
    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="API token file is invalid") from exc
    entries = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise HTTPException(status_code=500, detail="API token file is invalid")
    return entries


def _public_token_entries(token_file: Path) -> list[dict[str, Any]]:
    return [
        {"name": str(entry.get("name") or ""), "roles": list(entry.get("roles") or [])}
        for entry in _load_token_entries(token_file)
    ]


def _label(key: str) -> str:
    words = key.replace("_", " ").strip().split()
    if not words:
        return key
    return " ".join(
        word.upper()
        if word in {"api", "mqtt", "rx", "tx", "sse", "tls", "qos"}
        else word.capitalize()
        for word in words
    )
