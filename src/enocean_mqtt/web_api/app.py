"""Web API prototype for enocean-mqtt."""

from __future__ import annotations

import base64
import binascii
import csv
import hmac
import io
import json
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from enocean_mqtt.datapoints import DatapointRegistry
from enocean_mqtt.devices.foreign_registry import foreign_registry
from enocean_mqtt.devices.projection import ApiDeviceRegistry
from enocean_mqtt.eep.decoder import EEPDecodeError
from enocean_mqtt.eep.json_registry import (
    EEPRegistryError,
    load_eep_definition,
)
from enocean_mqtt.eep.runtime_decoder import decode_runtime_with_definition
from enocean_mqtt.esp3.radio import decode_f6_status
from enocean_mqtt.esp3.signal import RORG_NAMES, radio_diagnostics
from enocean_mqtt.gateway.runtime_commands import RuntimeCommandExecutionError
from enocean_mqtt.gateway.runtime_schema import RuntimeCommandValidationError
from enocean_mqtt.runtime.service import RuntimeService
from enocean_mqtt.version import load_project_version
from enocean_mqtt.web_api.device_management_routes import (
    create_device_management_router,
)
from enocean_mqtt.web_api.live_events import LIVE_EVENT_QUEUE, get_live_event
from enocean_mqtt.web_api.runtime_controls import (
    interface_connect,
    interface_controls_available,
    interface_disconnect,
    interface_network_bridge_restart,
    interface_network_bridge_start,
    interface_network_bridge_stop,
    interface_reconnect,
    interface_status,
)
from enocean_mqtt.web_api.semantic_routes import create_semantic_router
from enocean_mqtt.web_api.services.project_export import (
    build_enocean_project_export,
)

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
TELEGRAM_ACTIVITY_RANGE_HOURS = 48
RUNTIME_STATE_LOOKBACK_LIMIT = 1000
UNKNOWN_DEVICE_LOOKBACK_LIMIT = 10000

BASE_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIRECTORY.parent.parent.parent
TEMPLATE_DIRECTORY = BASE_DIRECTORY / "templates"
STATIC_DIRECTORY = BASE_DIRECTORY / "static"
CONFIG_DIRECTORY = PROJECT_ROOT / "config"
DEVICES_FILE = CONFIG_DIRECTORY / "devices.json"
VIRTUAL_DEVICES_FILE = CONFIG_DIRECTORY / "virtual-devices.json"
SQLITE_DATABASE = PROJECT_ROOT / "data" / "sqlite" / "enocean-mqtt.sqlite"
DEFAULT_API_TOKEN_FILE = CONFIG_DIRECTORY / "secrets" / "api-tokens.json"
EEP_REGISTRY_DIRECTORY = PROJECT_ROOT / "eep" / "registry"
TX_PROFILES_DIRECTORY = PROJECT_ROOT / "tx_profiles"
CONFIG_FILE = CONFIG_DIRECTORY / "config.json"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
VALID_API_ROLES = {"read", "admin"}
MIN_API_TOKEN_BYTES = 32
OPENAPI_SECURITY_SCHEME = {
    "type": "http",
    "scheme": "bearer",
}

DEVICE_SUMMARY_FIELDS = (
    "device_id",
    "device_name",
    "alias",
    "description",
    "manufacturer",
    "model",
    "eep",
    "profile",
    "metadata",
)

RELATIVE_TIME_RE = re.compile(
    r"^now(?P<offset>[+-]\d+[smhdw])?(?P<rounding>/[smhdw])?$"
)
UNIX_TIMESTAMP_RE = re.compile(r"^\d+(\.\d+)?$")
IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_.-]+")

app = FastAPI(
    title="enocean-mqtt Web API",
    version=load_project_version(),
    description="REST API for enocean-mqtt runtime, busmonitor and integration clients.",
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIRECTORY)),
    name="static",
)

templates = Jinja2Templates(directory=str(TEMPLATE_DIRECTORY))


def _custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = OPENAPI_SECURITY_SCHEME
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[method-assign]


@dataclass(slots=True)
class APIAuthenticationConfig:
    enabled: bool = False
    token_file: Path = DEFAULT_API_TOKEN_FILE


@dataclass(slots=True)
class APIToken:
    name: str
    token: str
    roles: set[str]


api_authentication_config = APIAuthenticationConfig()
RuntimeCommandDispatcher = Callable[
    [str, dict[str, Any] | None],
    dict[str, Any],
]
runtime_command_dispatcher: RuntimeCommandDispatcher | None = None


def configure_runtime_command_dispatcher(
    dispatcher: RuntimeCommandDispatcher | None,
) -> None:
    """Configure runtime command dispatch for the embedded API."""

    global runtime_command_dispatcher

    runtime_command_dispatcher = dispatcher


def _resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)

    if candidate.is_absolute():
        return candidate

    return PROJECT_ROOT / candidate


def _load_default_api_authentication_config() -> APIAuthenticationConfig:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return APIAuthenticationConfig()

    if not isinstance(payload, dict):
        return APIAuthenticationConfig()

    web_api = payload.get("web_api", {})

    if not isinstance(web_api, dict):
        return APIAuthenticationConfig()

    authentication = web_api.get("authentication", {})

    if not isinstance(authentication, dict):
        return APIAuthenticationConfig()

    return APIAuthenticationConfig(
        enabled=bool(authentication.get("enabled", False)),
        token_file=_resolve_project_path(
            str(
                authentication.get(
                    "token_file",
                    "config/secrets/api-tokens.json",
                )
            )
        ),
    )


def _load_project_export_source() -> dict[str, str | None]:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        payload = {}

    application = (
        payload.get("application", {})
        if isinstance(payload, dict)
        else {}
    )
    mqtt = payload.get("mqtt", {}) if isinstance(payload, dict) else {}

    project_id = None
    base_topic = None

    if isinstance(application, dict):
        project_id = _text_or_none(
            application.get("project_id")
            or application.get("name")
        )

    if isinstance(mqtt, dict):
        base_topic = _text_or_none(mqtt.get("base_topic"))

    return {
        "project_id": project_id or "enocean-mqtt",
        "base_topic": base_topic,
    }


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def configure_api_authentication(
    *,
    enabled: bool,
    token_file: str | Path,
) -> None:
    api_authentication_config.enabled = enabled
    api_authentication_config.token_file = _resolve_project_path(token_file)


def _validate_api_token_format(token: str, *, name: str) -> None:
    try:
        decoded = base64.b64decode(token, validate=True)
    except binascii.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=f"API token entry {name} is not valid Base64",
        ) from exc

    if len(decoded) < MIN_API_TOKEN_BYTES:
        raise HTTPException(
            status_code=503,
            detail=(
                f"API token entry {name} must decode to at least "
                f"{MIN_API_TOKEN_BYTES} bytes"
            ),
        )


def _load_api_tokens() -> list[APIToken]:
    try:
        with api_authentication_config.token_file.open(
            "r",
            encoding="utf-8",
        ) as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="API authentication token file not found",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="API authentication token file is invalid",
        ) from exc

    tokens = payload.get("tokens") if isinstance(payload, dict) else None

    if not isinstance(tokens, list):
        raise HTTPException(
            status_code=503,
            detail="API authentication token file has no tokens list",
        )

    loaded_tokens: list[APIToken] = []

    for index, item in enumerate(tokens):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=503,
                detail=f"API token entry {index} is not an object",
            )

        name = str(item.get("name") or f"token-{index}")
        token = item.get("token")
        roles = item.get("roles", [])

        if not isinstance(token, str) or not token:
            raise HTTPException(
                status_code=503,
                detail=f"API token entry {name} has no token",
            )

        _validate_api_token_format(token, name=name)

        if not isinstance(roles, list):
            raise HTTPException(
                status_code=503,
                detail=f"API token entry {name} has invalid roles",
            )

        role_set = {str(role) for role in roles}
        invalid_roles = role_set - VALID_API_ROLES

        if invalid_roles:
            raise HTTPException(
                status_code=503,
                detail=f"API token entry {name} has unknown roles",
            )

        if "admin" in role_set:
            role_set.add("read")

        loaded_tokens.append(
            APIToken(
                name=name,
                token=token,
                roles=role_set,
            )
        )

    return loaded_tokens


def _required_api_role(method: str) -> str:
    return "read" if method.upper() in READ_METHODS else "admin"


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() == "bearer" and token:
        return token

    if request.url.path == "/api/v1/busmonitor/stream":
        query_token = request.query_params.get("access_token")

        if query_token:
            return query_token

    return None


api_authentication_config = _load_default_api_authentication_config()


@app.middleware("http")
async def api_token_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request.state.api_roles = (
        set() if api_authentication_config.enabled else {"read", "admin"}
    )
    if request.url.path.startswith("/api/v1/") and api_authentication_config.enabled:
        provided_token = _extract_bearer_token(request)

        if provided_token is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        required_role = _required_api_role(request.method)

        try:
            api_tokens = _load_api_tokens()
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )

        for api_token in api_tokens:
            if hmac.compare_digest(provided_token, api_token.token):
                if required_role in api_token.roles:
                    request.state.api_roles = api_token.roles
                    return await call_next(request)

                return JSONResponse(
                    status_code=403,
                    content={"detail": "API token lacks required role"},
                )

        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid bearer token"},
        )

    return await call_next(request)


def parse_time_expression(expression: str | None) -> float | None:
    """Parse a Grafana-style time expression into Unix seconds."""

    if expression is None:
        return None

    value = expression.strip()

    if not value:
        return None

    if UNIX_TIMESTAMP_RE.match(value):
        return float(value)

    relative_match = RELATIVE_TIME_RE.match(value)

    if relative_match:
        result = datetime.now().astimezone()
        offset = relative_match.group("offset")
        rounding = relative_match.group("rounding")

        if offset:
            result += _parse_relative_offset(offset)

        if rounding:
            result = _round_datetime(result, rounding[1:])

        return result.timestamp()

    return _parse_absolute_time(value).timestamp()


def _parse_relative_offset(offset: str) -> timedelta:
    sign = -1 if offset[0] == "-" else 1
    amount = int(offset[1:-1])
    unit = offset[-1]

    if unit == "s":
        return timedelta(seconds=sign * amount)

    if unit == "m":
        return timedelta(minutes=sign * amount)

    if unit == "h":
        return timedelta(hours=sign * amount)

    if unit == "d":
        return timedelta(days=sign * amount)

    if unit == "w":
        return timedelta(weeks=sign * amount)

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported relative time unit: {unit}",
    )


def _round_datetime(value: datetime, unit: str) -> datetime:
    if unit == "s":
        return value.replace(microsecond=0)

    if unit == "m":
        return value.replace(second=0, microsecond=0)

    if unit == "h":
        return value.replace(minute=0, second=0, microsecond=0)

    if unit == "d":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)

    if unit == "w":
        start_of_day = value.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start_of_day - timedelta(days=start_of_day.weekday())

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported rounding unit: {unit}",
    )


def _parse_absolute_time(value: str) -> datetime:
    candidates = [
        value,
        value.replace("Z", "+00:00"),
        value.replace(" ", "T"),
    ]

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue

        if parsed.tzinfo is None:
            return parsed.astimezone()

        return parsed

    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S.%f",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ]

    for time_format in formats:
        try:
            parsed = datetime.strptime(value, time_format)
        except ValueError:
            continue

        return parsed.astimezone()

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported time expression: {value}",
    )


def _normalize_sender_id(sender_id: Any) -> str | None:
    if sender_id is None:
        return None

    value = (
        str(sender_id)
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace(":", "")
    )

    if not value:
        return None

    if value.lower().startswith("0x"):
        value = value[2:]

    return value.upper()


def _safe_identifier(value: str) -> str:
    return IDENTIFIER_RE.sub("_", value.strip()).strip("_") or "unnamed"


def _api_device_id_from_summary(summary: Mapping[str, Any]) -> str | None:
    for key in ("alias", "device_id", "sender_id"):
        value = summary.get(key)

        if value is not None and str(value).strip():
            return _safe_identifier(str(value))

    return None


def _hex_or_none(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, bytes):
        return value.hex().upper()

    if isinstance(value, int):
        return f"{value:02X}"

    text = str(value).replace(" ", "").replace("-", "").replace(":", "")

    if not text:
        return None

    return text.upper()


def _load_device_index() -> dict[str, dict[str, Any]]:
    if not DEVICES_FILE.exists():
        return {}

    try:
        with DEVICES_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    devices = payload.get("devices", [])
    device_index: dict[str, dict[str, Any]] = {}

    if not isinstance(devices, list):
        return device_index

    for device in devices:
        if not isinstance(device, dict):
            continue

        device_id = _normalize_sender_id(device.get("device_id"))

        if device_id is None:
            continue

        normalized_device = dict(device)
        normalized_device["device_id"] = device_id
        device_index[device_id] = normalized_device

    return device_index


def _device_summary(
    sender_id: Any,
    device_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized_sender_id = _normalize_sender_id(sender_id)

    if normalized_sender_id is None:
        return {"known": False}

    device = device_index.get(normalized_sender_id)

    if device is None:
        return {
            "known": False,
            "sender_id": normalized_sender_id,
        }

    summary = {
        field: device.get(field)
        for field in DEVICE_SUMMARY_FIELDS
        if field in device
    }
    summary["known"] = True
    summary["sender_id"] = normalized_sender_id

    return summary


def _device_list(
    device_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _device_summary(sender_id, device_index)
        for sender_id in sorted(device_index)
    ]


def _decode_telegram(
    telegram: dict[str, Any],
    device_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    rorg = str(telegram.get("rorg") or "").upper()
    if rorg == "D0" or rorg not in RORG_NAMES:
        return None, None
    normalized_sender_id = _normalize_sender_id(telegram.get("sender_id"))

    if normalized_sender_id is None:
        return None, None

    device = device_index.get(normalized_sender_id)

    if device is None:
        return None, None

    profile = device.get("profile") or device.get("eep")

    if not profile:
        return None, "Known device has no profile/eep assignment"

    payload_hex = _hex_or_none(telegram.get("data"))

    if not payload_hex:
        return None, "Telegram has no payload data"

    status_hex = _hex_or_none(telegram.get("erp1_status"))

    try:
        eep_definition = load_eep_definition(str(profile))
        decoded = decode_runtime_with_definition(
            eep_definition=eep_definition,
            payload_hex=payload_hex,
            status_hex=status_hex,
            telegram_id=None,
            rorg=telegram.get("rorg"),
            external_context={
                "direction": telegram.get("direction"),
                "sender_id": normalized_sender_id,
                "rorg": telegram.get("rorg"),
            },
        )
    except (EEPDecodeError, EEPRegistryError, ValueError) as exc:
        return None, str(exc)

    decoded_channels = {
        channel_name: {
            "value": channel.value,
            "raw_value": channel.raw_value,
            "unit": channel.unit,
            "semantic_role": channel.semantic_role,
            "range_label": channel.range_label,
            "channel_type": channel.definition.channel_type,
            "object_type": channel.object_type,
            "data_type": channel.data_type,
        }
        for channel_name, channel in decoded.values.items()
    }

    return {
        "profile": str(profile),
        "eep": decoded.eep,
        "telegram_type_id": decoded.telegram_type_id,
        "fields": decoded.fields,
        "status_fields": decoded.status_fields,
        "channels": decoded_channels,
    }, None


def _decoded_tooltip(
    decoded: dict[str, Any] | None,
    error: str | None,
) -> str | None:
    if decoded is None:
        return f"Decode unavailable: {error}" if error else None

    channels = decoded.get("channels") or {}

    if not channels:
        return "No decoded channels"

    lines = []

    for channel_name, channel in channels.items():
        value = channel.get("value")
        unit = channel.get("unit")
        line = f"{channel_name}: {value}"

        if unit:
            line += f" {unit}"

        lines.append(line)

    return "\n".join(lines)


def _normalize_telegram_payload(
    telegram: dict[str, Any],
    device_index: dict[str, dict[str, Any]],
    include_decoded: bool,
) -> dict[str, Any]:
    telegram["raw_telegram"] = _hex_or_none(telegram.get("raw_telegram"))
    telegram["data"] = _hex_or_none(telegram.get("data"))
    telegram["erp1_status"] = _hex_or_none(telegram.get("erp1_status"))
    rorg = str(telegram.get("rorg") or "").upper()
    data = telegram["data"] or ""
    telegram["contains_teach_in"] = bool(
        ((rorg == "A5" and len(data) == 8) or (rorg == "D5" and len(data) == 2))
        and re.fullmatch(r"[0-9A-Fa-f]+", data)
        and not (int(data[-2:], 16) & 0x08)
    )
    if str(telegram.get("rorg") or "").upper() == "F6":
        # Recompute old archive metadata too; the raw status is authoritative.
        status = decode_f6_status(telegram["erp1_status"])
        telegram["erp1_status_decoded"] = status
        telegram["contains_teach_in"] = False
        if status is not None:
            for key in ("repeater_count", "repeater_permitted", "hash_type", "contains_teach_in"):
                telegram[key] = status[key]

    normalized_sender_id = _normalize_sender_id(telegram.get("sender_id"))
    known_device = (
        normalized_sender_id in device_index
        if normalized_sender_id
        else False
    )

    if normalized_sender_id is not None:
        telegram["sender_id"] = normalized_sender_id

    telegram["known_device"] = known_device
    telegram["foreign_device"] = normalized_sender_id in foreign_registry(
        DEVICES_FILE.parent / "foreign-devices.json"
    ).snapshot()
    telegram["device"] = _device_summary(normalized_sender_id, device_index)
    telegram.update(radio_diagnostics(telegram.get("rorg"), telegram.get("data")))

    decoded = None
    decode_error = None

    if known_device:
        decoded, decode_error = _decode_telegram(telegram, device_index)

    telegram["decoded_tooltip"] = _decoded_tooltip(decoded, decode_error)
    telegram["decode_error"] = decode_error
    if "signal" in telegram:
        signal = telegram["signal"]
        telegram["decoded_tooltip"] = "\n".join(
            [f"SIGNAL MID: {signal.get('mid', '?')} | {signal.get('name', 'Malformed')}"]
            + [f"{key}: {value}" for key, value in signal["fields"].items()]
            + ([f"Error: {signal['error']}"] if "error" in signal else [])
        )
    elif "protocol_warning" in telegram:
        telegram["decoded_tooltip"] = telegram["protocol_warning"]

    if include_decoded:
        telegram["decoded"] = decoded

    return telegram


def _selected_device_types(value: str | None) -> set[str]:
    if value is None:
        return {"known", "unknown", "foreign"}
    if value == "none":
        return set()
    selected = {item.strip() for item in value.split(",")}
    if not selected or not selected <= {"known", "unknown", "foreign"}:
        raise HTTPException(status_code=422, detail="Invalid device_types selection")
    return selected


class SQLiteTelegramQuery:
    """Minimal SQLite telegram query helper."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def query_telegrams(
        self,
        *,
        limit: int,
        sender_id: str | None,
        rorg: str | None,
        direction: str | None,
        runtime_mode: str | None,
        known_filter: str | None,
        time_from: float | None,
        time_to: float | None,
        cursor_timestamp: float | None,
        cursor_telegram_id: int | None,
        hide_foreign: bool = False,
        device_types: str | None = None,
        teach_in: bool | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        conditions: list[str] = []
        parameters: list[Any] = []
        device_index = _load_device_index()
        known_devices = set(device_index.keys())

        if teach_in is not None:
            # Match the raw LRN bit, not stale archive status/Teach-In metadata.
            payload = (
                "CASE WHEN typeof(data) = 'blob' THEN HEX(data) "
                "ELSE UPPER(REPLACE(REPLACE(REPLACE(COALESCE(data, ''), "
                "' ', ''), '-', ''), ':', '')) END"
            )
            is_teach_in = (
                f"(((UPPER(rorg) = 'A5' AND LENGTH({payload}) = 8) OR "
                f"(UPPER(rorg) = 'D5' AND LENGTH({payload}) = 2)) "
                f"AND ({payload}) NOT GLOB '*[^0-9A-F]*' "
                f"AND SUBSTR({payload}, -1) IN ('0','1','2','3','4','5','6','7'))"
            )
            conditions.append(f"COALESCE({is_teach_in}, 0) = ?")
            parameters.append(int(teach_in))

        if device_types is not None:
            selected = _selected_device_types(device_types)
            foreign_ids = set(
                foreign_registry(DEVICES_FILE.parent / "foreign-devices.json").snapshot()
            )
            clauses = []
            for category in sorted(selected):
                ids = sorted(foreign_ids if category == "foreign" else known_devices - foreign_ids)
                if category == "unknown":
                    ids = sorted(known_devices | foreign_ids)
                    placeholders = ", ".join("?" for _ in ids)
                    clauses.append(
                        f"(sender_id IS NULL OR UPPER(sender_id) NOT IN ({placeholders}))"
                        if ids else "1 = 1"
                    )
                else:
                    placeholders = ", ".join("?" for _ in ids)
                    clauses.append(f"UPPER(sender_id) IN ({placeholders})" if ids else "1 = 0")
                parameters.extend(ids)
            conditions.append("(" + " OR ".join(clauses) + ")" if clauses else "1 = 0")

        if hide_foreign:
            excluded_foreign_ids = sorted(
                foreign_registry(DEVICES_FILE.parent / "foreign-devices.json").snapshot()
            )
            if excluded_foreign_ids:
                placeholders = ", ".join("?" for _ in excluded_foreign_ids)
                conditions.append(
                    f"(sender_id IS NULL OR UPPER(sender_id) NOT IN ({placeholders}))"
                )
                parameters.extend(excluded_foreign_ids)

        if sender_id:
            sender_values = [
                normalized
                for value in sender_id.split(",")
                if (normalized := _normalize_sender_id(value))
            ]

            if sender_values:
                placeholders = ", ".join("?" for _ in sender_values)
                conditions.append(f"sender_id IN ({placeholders})")
                parameters.extend(sender_values)

        if rorg:
            rorg_values = [
                value.strip().upper()
                for value in rorg.split(",")
                if value.strip()
            ]

            if rorg_values:
                placeholders = ", ".join("?" for _ in rorg_values)
                conditions.append(f"rorg IN ({placeholders})")
                parameters.extend(rorg_values)

        if direction:
            conditions.append("direction = ?")
            parameters.append(direction)

        if runtime_mode:
            conditions.append("runtime_mode = ?")
            parameters.append(runtime_mode)

        if known_filter == "known":
            if known_devices:
                placeholders = ", ".join("?" for _ in known_devices)
                conditions.append(f"sender_id IN ({placeholders})")
                parameters.extend(sorted(known_devices))
            else:
                conditions.append("1 = 0")

        elif known_filter == "unknown" and known_devices:
            placeholders = ", ".join("?" for _ in known_devices)
            conditions.append(f"sender_id NOT IN ({placeholders})")
            parameters.extend(sorted(known_devices))

        if time_from is not None:
            conditions.append("timestamp_unix >= ?")
            parameters.append(time_from)

        if time_to is not None:
            conditions.append("timestamp_unix <= ?")
            parameters.append(time_to)

        if cursor_timestamp is not None and cursor_telegram_id is not None:
            conditions.append(
                """
                (
                    timestamp_unix < ?
                    OR (
                        timestamp_unix = ?
                        AND telegram_id < ?
                    )
                )
                """
            )
            parameters.extend(
                [
                    cursor_timestamp,
                    cursor_timestamp,
                    cursor_telegram_id,
                ]
            )

        where_clause = ""

        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
        SELECT *
        FROM telegrams
        {where_clause}
        ORDER BY timestamp_unix DESC, telegram_id DESC
        LIMIT ?
        """
        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        telegrams = [
            _normalize_telegram_payload(
                telegram=dict(row),
                device_index=device_index,
                include_decoded=False,
            )
            for row in rows
        ]
        next_cursor = None

        if telegrams:
            last = telegrams[-1]
            next_cursor = {
                "timestamp_unix": last.get("timestamp_unix"),
                "telegram_id": last.get("telegram_id"),
            }

        return telegrams, next_cursor

    def get_hourly_direction_counts(
        self,
        range_hours: int = TELEGRAM_ACTIVITY_RANGE_HOURS,
    ) -> dict[str, Any]:
        now = datetime.now().astimezone()
        timezone = now.tzinfo
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=range_hours - 1)
        end_time = current_hour + timedelta(hours=1)
        buckets: dict[datetime, dict[str, Any]] = {}

        for hour_index in range(range_hours):
            bucket_hour = start_hour + timedelta(hours=hour_index)
            buckets[bucket_hour] = {
                "hour": bucket_hour.isoformat(),
                "rx": 0,
                "tx": 0,
                "total": 0,
            }

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT timestamp_unix, direction
                FROM telegrams
                WHERE timestamp_unix >= ?
                  AND timestamp_unix < ?
                """,
                (start_hour.timestamp(), end_time.timestamp()),
            ).fetchall()

        for row in rows:
            direction = str(row["direction"] or "").lower()

            if direction not in {"rx", "tx"}:
                continue

            timestamp = datetime.fromtimestamp(
                float(row["timestamp_unix"]),
                tz=timezone,
            )
            bucket_hour = timestamp.replace(
                minute=0,
                second=0,
                microsecond=0,
            )
            bucket = buckets.get(bucket_hour)

            if bucket is None:
                continue

            bucket[direction] += 1
            bucket["total"] += 1

        return {
            "range_hours": range_hours,
            "bucket": "hour",
            "from": start_hour.isoformat(),
            "to": end_time.isoformat(),
            "telegrams": list(buckets.values()),
        }

    def get_telegram(self, telegram_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegrams WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()

        if row is None:
            return None

        return _normalize_telegram_payload(
            telegram=dict(row),
            device_index=_load_device_index(),
            include_decoded=True,
        )

    def get_latest_device_states(
        self,
        limit: int = RUNTIME_STATE_LOOKBACK_LIMIT,
    ) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM telegrams
                ORDER BY timestamp_unix DESC, telegram_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        device_index = _load_device_index()
        states: dict[str, dict[str, Any]] = {}

        for row in rows:
            telegram = _normalize_telegram_payload(
                telegram=dict(row),
                device_index=device_index,
                include_decoded=True,
            )
            device = telegram.get("device")

            if not isinstance(device, Mapping) or not device.get("known"):
                continue

            api_device_id = _api_device_id_from_summary(device)

            if api_device_id is None:
                continue

            decoded = telegram.get("decoded")

            if not isinstance(decoded, Mapping):
                continue

            decoded_channels = decoded.get("channels")

            if not isinstance(decoded_channels, Mapping):
                continue

            state = states.setdefault(
                api_device_id,
                {
                    "device_id": api_device_id,
                    "last_update": telegram.get("timestamp_local"),
                    "channels": {},
                },
            )
            channels = state["channels"]

            if not isinstance(channels, dict):
                continue

            for channel_name, channel_payload in decoded_channels.items():
                if channel_name in channels:
                    continue

                if not isinstance(channel_payload, Mapping):
                    continue

                channels[str(channel_name)] = {
                    "value": channel_payload.get("value"),
                    "unit": channel_payload.get("unit"),
                    "semantic_role": channel_payload.get("semantic_role"),
                    "object_type": channel_payload.get("object_type"),
                    "last_update": telegram.get("timestamp_local"),
                }

        return states


def get_query_backend() -> SQLiteTelegramQuery:
    return SQLiteTelegramQuery(SQLITE_DATABASE)


def get_datapoint_registry() -> DatapointRegistry:
    return DatapointRegistry.from_config_files(
        devices_file=DEVICES_FILE,
        virtual_devices_file=VIRTUAL_DEVICES_FILE,
    )


def get_api_device_registry() -> ApiDeviceRegistry:
    return ApiDeviceRegistry.from_config_files(
        devices_file=DEVICES_FILE,
        virtual_devices_file=VIRTUAL_DEVICES_FILE,
        datapoint_registry=get_datapoint_registry(),
    )


def get_latest_device_states() -> dict[str, dict[str, Any]]:
    try:
        return get_query_backend().get_latest_device_states()
    except sqlite3.Error:
        return {}


def get_runtime_service() -> RuntimeService:
    datapoints = get_datapoint_registry()
    return RuntimeService(
        datapoint_registry=datapoints,
        api_device_registry=ApiDeviceRegistry.from_config_files(
            devices_file=DEVICES_FILE,
            virtual_devices_file=VIRTUAL_DEVICES_FILE,
            datapoint_registry=datapoints,
        ),
        fallback_device_states_provider=get_latest_device_states,
        fallback_source="sqlite_latest_telegram",
    )


app.include_router(
    create_semantic_router(
        get_runtime_service,
        runtime_command_dispatcher_provider=lambda: runtime_command_dispatcher,
    )
)


def _normalize_live_telegram(payload: dict[str, Any]) -> dict[str, Any]:
    telegram = {
        "telegram_id": payload.get("telegram_id"),
        "timestamp_local": payload.get("timestamp_local"),
        "timestamp_unix": payload.get("timestamp_unix"),
        "direction": payload.get("direction"),
        "runtime_mode": payload.get("runtime_mode"),
        "sender_id": payload.get("sender_id"),
        "destination_id": payload.get("destination_id"),
        "rorg": payload.get("rorg"),
        "data": payload.get("data"),
        "erp1_status": payload.get("erp1_status"),
        "raw_telegram": payload.get("raw_telegram"),
        "rssi_dbm": payload.get("rssi_dbm"),
        "port": payload.get("port"),
        "interface_id": payload.get("interface_id"),
        "subtelegram_count": payload.get("subtelegram_count"),
    }

    return _normalize_telegram_payload(
        telegram=telegram,
        device_index=_load_device_index(),
        include_decoded=False,
    )


async def _live_event_stream(request: Request) -> AsyncIterator[str]:
    LIVE_EVENT_QUEUE.connect()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await get_live_event(poll=True)
            except TimeoutError:
                continue
            if payload is None:
                break

            telegram = _normalize_live_telegram(payload)
            data = json.dumps(telegram, separators=(",", ":"))
            yield f"event: telegram\ndata: {data}\n\n"
    finally:
        LIVE_EVENT_QUEUE.disconnect()


def _health_payload() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "enocean-mqtt-web-api",
    }


def _busmonitor_devices_payload(
    hide_foreign: bool = False, device_types: str | None = None,
) -> dict[str, Any]:
    device_index = _load_device_index()
    known_ids = set(device_index)
    foreign_ids = foreign_registry(DEVICES_FILE.parent / "foreign-devices.json").snapshot()
    if device_types is not None:
        for sender_id in foreign_ids:
            device_index.setdefault(sender_id, {"device_id": sender_id})
        selected = _selected_device_types(device_types)
        device_index = {
            key: device for key, device in device_index.items()
            if ("foreign" if key in foreign_ids else "known") in selected
        }
    if hide_foreign:
        device_index = {
            key: device for key, device in device_index.items() if key not in foreign_ids
        }
    return {
        "devices": [
            {**device, "known": device["sender_id"] in known_ids,
             "foreign_device": device["sender_id"] in foreign_ids}
            for device in _device_list(device_index)
        ],
        "count": len(device_index),
    }


def _runtime_commands_payload() -> dict[str, Any]:
    commands = [
        _runtime_command_payload("gateway.exit"),
        _runtime_command_payload("gateway.restart"),
        _runtime_command_payload("gateway.republish"),
        _runtime_command_payload("eeps.reload"),
        _runtime_command_payload("devices.republish"),
        _runtime_command_payload("interface.connect", optional=["interface_id"]),
        _runtime_command_payload("interface.disconnect", optional=["interface_id"]),
        _runtime_command_payload("devices.import", optional=["import_file"]),
        _runtime_command_payload("devices.reload"),
        _runtime_command_payload("devices.export", optional=["export_file"]),
        _runtime_command_payload(
            "unknown_devices.export",
            optional=["export_file"],
        ),
        _runtime_command_payload("device.import", required=["device"]),
        _runtime_command_payload("device.delete", required=["device_id"]),
        _runtime_command_payload("device.teach_in", required=["device_id"]),
        _runtime_command_payload(
            "virtual_device.create",
            required=["virtual_device"],
        ),
        _runtime_command_payload(
            "virtual_device.delete",
            required=["virtual_device_id"],
        ),
        _runtime_command_payload(
            "virtual_device.teach_in",
            required=["virtual_device_id"],
        ),
        _runtime_command_payload("replay.start", required=["capture_file"]),
        _runtime_command_payload("replay.stop"),
        _runtime_command_payload(
            "interface.network_bridge.start",
            optional=["interface_id"],
        ),
        _runtime_command_payload(
            "interface.network_bridge.stop",
            optional=["interface_id"],
        ),
        _runtime_command_payload(
            "interface.network_bridge.restart",
            optional=["interface_id"],
        ),
    ]
    return {
        "commands": commands,
        "count": len(commands),
        "dispatch": {
            "http_available": runtime_command_dispatcher is not None,
            "mqtt_topic": "<base_topic>/gateway/command",
        },
        "issues": (
            []
            if runtime_command_dispatcher is not None
            else [
                {
                    "severity": "warning",
                    "message": (
                        "HTTP command dispatch is not available in this "
                        "process; commands are exposed for discovery only."
                    ),
                }
            ]
        ),
    }


def _runtime_command_payload(
    command: str,
    *,
    required: list[str] | None = None,
    optional: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": command,
        "required_fields": required or [],
        "optional_fields": optional or [],
    }


def _not_implemented_payload(message: str) -> dict[str, str]:
    return {
        "status": "not_implemented",
        "message": message,
    }


def _require_interface_controls() -> None:
    if not interface_controls_available():
        raise HTTPException(
            status_code=503,
            detail="Live interface controls are not available",
        )


def _gateway_payload() -> dict[str, Any]:
    return {
        "service": "enocean-mqtt-web-api",
        "api_version": app.version,
        "project_root": str(PROJECT_ROOT),
        "database": {
            "path": str(SQLITE_DATABASE),
            "exists": SQLITE_DATABASE.exists(),
        },
        "auth": {
            "bearer_token_enabled": api_authentication_config.enabled,
        },
        "links": {
            "health": "/api/v1/gateway/health",
            "runtime_status": "/api/v1/runtime/status",
            "busmonitor_telegrams": "/api/v1/busmonitor/telegrams",
            "devices": "/api/v1/devices",
            "datapoints": "/api/v1/datapoints",
            "eeps": "/api/v1/eeps",
            "profiles": "/api/v1/profiles",
        },
    }


def _gateway_status_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "enocean-mqtt-web-api",
        "database_available": SQLITE_DATABASE.exists(),
        "auth_enabled": api_authentication_config.enabled,
    }


def _gateway_config_payload() -> dict[str, Any]:
    return {
        "paths": {
            "config_directory": str(CONFIG_DIRECTORY),
            "devices_file": str(DEVICES_FILE),
            "virtual_devices_file": str(VIRTUAL_DEVICES_FILE),
            "sqlite_database": str(SQLITE_DATABASE),
            "eep_registry_directory": str(EEP_REGISTRY_DIRECTORY),
            "tx_profiles_directory": str(TX_PROFILES_DIRECTORY),
        },
        "limits": {
            "default_limit": DEFAULT_LIMIT,
            "max_limit": MAX_LIMIT,
            "telegram_activity_range_hours": TELEGRAM_ACTIVITY_RANGE_HOURS,
            "runtime_state_lookback_limit": RUNTIME_STATE_LOOKBACK_LIMIT,
        },
        "auth": {
            "bearer_token_enabled": api_authentication_config.enabled,
            "token_file": str(api_authentication_config.token_file),
            "roles": sorted(VALID_API_ROLES),
        },
    }


def _runtime_status_payload() -> dict[str, Any]:
    devices = get_runtime_service().get_devices()
    datapoints = get_runtime_service().get_datapoints()
    return {
        "status": "ok",
        "runtime_mode": "web_api",
        "devices_count": devices.get("count", 0),
        "datapoints_count": datapoints.get("count", 0),
        "sqlite_fallback_available": SQLITE_DATABASE.exists(),
        "state_source": "runtime_or_sqlite_latest_telegram",
    }


def _runtime_diagnostics_payload() -> dict[str, Any]:
    service = get_runtime_service()
    datapoint_runtime = service.get_datapoint_runtime_registry()
    diagnostics: list[dict[str, Any]] = []

    if not SQLITE_DATABASE.exists():
        diagnostics.append(
            {
                "severity": "warning",
                "source": "sqlite",
                "message": "SQLite database does not exist.",
            }
        )

    return {
        "status": "ok" if not diagnostics else "warning",
        "diagnostics": diagnostics,
        "issues": [
            *service.api_device_registry.issues,
            *service.datapoint_registry.issues,
            *datapoint_runtime.issues,
        ],
    }


def _unknown_devices_payload(
    *,
    lookback_limit: int | None,
) -> dict[str, Any]:
    if not SQLITE_DATABASE.exists():
        return {
            "unknown_devices": [],
            "count": 0,
            "source": "sqlite",
            "issues": [
                {
                    "severity": "warning",
                    "source": "sqlite",
                    "message": "SQLite database does not exist.",
                }
            ],
        }

    device_index = _load_device_index()
    known_devices = set(device_index)
    records: dict[str, dict[str, Any]] = {}

    query = """
            SELECT sender_id, rorg, timestamp_unix, rssi_dbm, data, raw_telegram
            FROM telegrams
            WHERE sender_id IS NOT NULL AND direction = 'rx'
            ORDER BY timestamp_unix DESC, telegram_id DESC
            """
    parameters: tuple[Any, ...] = ()
    if lookback_limit is not None:
        query += " LIMIT ?"
        parameters = (lookback_limit,)

    with get_query_backend()._connect() as connection:
        rows = connection.execute(query, parameters).fetchall()

    for row in rows:
        sender_id = _normalize_sender_id(row["sender_id"])

        if sender_id is None or sender_id in known_devices:
            continue

        record = records.setdefault(
            sender_id,
            {
                "sender_id": sender_id,
                "rorg": _hex_or_none(row["rorg"]),
                "telegrams": 0,
                "first_seen": None,
                "last_seen": None,
                "last_rssi_dbm": None,
                "last_data": None,
                "last_raw_telegram": None,
            },
        )
        timestamp = row["timestamp_unix"]
        record["telegrams"] += 1
        record["first_seen"] = _timestamp_to_iso(timestamp)

        if record["last_seen"] is None:
            record["last_seen"] = _timestamp_to_iso(timestamp)
            record["last_rssi_dbm"] = row["rssi_dbm"]
            record["last_data"] = _hex_or_none(row["data"])
            record["last_raw_telegram"] = _hex_or_none(row["raw_telegram"])
            record["rorg"] = _hex_or_none(row["rorg"])

    return {
        "unknown_devices": [
            records[sender_id]
            for sender_id in sorted(records)
        ],
        "count": len(records),
        "source": "sqlite_latest_telegrams",
        "lookback_limit": lookback_limit,
        "issues": [],
    }


app.include_router(
    create_device_management_router(
        devices_file=DEVICES_FILE,
        virtual_devices_file=VIRTUAL_DEVICES_FILE,
        sqlite_database=SQLITE_DATABASE,
        config_file=CONFIG_FILE,
        eep_registry_directory=EEP_REGISTRY_DIRECTORY,
        runtime_command_dispatcher_provider=lambda: runtime_command_dispatcher,
        unknown_devices_provider=_unknown_devices_payload,
    )
)


def _timestamp_to_iso(timestamp: Any) -> str | None:
    if timestamp is None:
        return None

    try:
        return (
            datetime.fromtimestamp(float(timestamp))
            .astimezone()
            .isoformat(timespec="milliseconds")
        )
    except (TypeError, ValueError, OSError):
        return None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read JSON file: {path.name}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"JSON file does not contain an object: {path.name}",
        )

    return payload


def _definition_to_api_dict(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)

    if isinstance(value, list):
        return [_definition_to_api_dict(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _definition_to_api_dict(item)
            for key, item in value.items()
        }

    return value


def _eep_summary_from_payload(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    eep_id = str(payload.get("eep") or path.stem)
    channels = payload.get("channels")
    messages = payload.get("messages")

    return {
        "eep": eep_id,
        "id": eep_id,
        "rorg": payload.get("rorg"),
        "func": payload.get("func"),
        "type": payload.get("type"),
        "title": payload.get("title") or payload.get("description"),
        "description": payload.get("description"),
        "profile_type": payload.get("profile_type"),
        "device_class": payload.get("device_class"),
        "channels_count": len(channels) if isinstance(channels, list) else 0,
        "messages_count": len(messages) if isinstance(messages, list) else 0,
        "url": f"/api/v1/eeps/{eep_id}",
    }


def _eeps_payload() -> dict[str, Any]:
    eeps = [
        _eep_summary_from_payload(path, _read_json_object(path))
        for path in sorted(EEP_REGISTRY_DIRECTORY.glob("*.json"))
    ]

    return {
        "eeps": eeps,
        "count": len(eeps),
    }


def _eep_payload(eep_id: str) -> dict[str, Any]:
    try:
        definition = load_eep_definition(eep_id)
    except EEPRegistryError as exc:
        raise HTTPException(
            status_code=404,
            detail="EEP not found",
        ) from exc

    return {
        "eep": _definition_to_api_dict(definition),
    }


def _eep_section_payload(eep_id: str, section: str) -> dict[str, Any]:
    eep = _eep_payload(eep_id)["eep"]
    items = eep.get(section, [])

    return {
        "eep": eep_id,
        section: items,
        "count": len(items) if isinstance(items, list) else 0,
    }


def _eep_datapoint_template_payload(eep_id: str) -> dict[str, Any]:
    eep = _eep_payload(eep_id)["eep"]
    channels = eep.get("channels", [])
    messages = eep.get("messages", [])
    datapoints = []

    for item in [*channels, *messages]:
        if not isinstance(item, Mapping):
            continue

        name = str(item.get("name") or "unnamed")
        datapoints.append(
            {
                "name": name,
                "semantic_role": item.get("semantic_role"),
                "object_type": item.get("object_type"),
                "data_type": item.get("data_type"),
                "unit": item.get("unit"),
                "readable": item in channels,
                "writable": item in messages,
            }
        )

    return {
        "eep": eep_id,
        "datapoints": datapoints,
        "count": len(datapoints),
    }


def _profile_summary_from_payload(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    profile_id = str(payload.get("profile") or path.stem)

    return {
        "profile": profile_id,
        "id": profile_id,
        "rorg": payload.get("rorg"),
        "func": payload.get("func"),
        "type": payload.get("type"),
        "semantic_class": payload.get("semantic_class"),
        "teach_in_method": payload.get("teach_in_method"),
        "sequence_model": payload.get("sequence_model"),
        "encoder_backend": payload.get("encoder_backend"),
        "supported_commands": payload.get("supported_commands", []),
        "url": f"/api/v1/profiles/{profile_id}",
    }


def _profiles_payload() -> dict[str, Any]:
    profiles = [
        _profile_summary_from_payload(path, _read_json_object(path))
        for path in sorted(TX_PROFILES_DIRECTORY.glob("*.json"))
    ]

    return {
        "profiles": profiles,
        "count": len(profiles),
    }


def _profile_payload(profile_id: str) -> dict[str, Any]:
    path = TX_PROFILES_DIRECTORY / f"{profile_id}.json"

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    return {
        "profile": _read_json_object(path),
    }


def _profile_section_payload(profile_id: str, section: str) -> dict[str, Any]:
    profile = _profile_payload(profile_id)["profile"]
    items = profile.get(section, [])

    return {
        "profile": profile_id,
        section: items,
        "count": len(items) if isinstance(items, list) else 0,
    }


def _profile_datapoint_template_payload(profile_id: str) -> dict[str, Any]:
    profile = _profile_payload(profile_id)["profile"]
    commands = profile.get("supported_commands", [])
    datapoints = [
        {
            "name": str(command),
            "semantic_role": None,
            "object_type": "command",
            "data_type": "string",
            "readable": False,
            "writable": True,
        }
        for command in commands
    ]

    return {
        "profile": profile_id,
        "datapoints": datapoints,
        "count": len(datapoints),
    }


def _telegrams_per_hour_payload() -> dict[str, Any]:
    backend = get_query_backend()
    return backend.get_hourly_direction_counts(
        range_hours=TELEGRAM_ACTIVITY_RANGE_HOURS,
    )


def _query_telegrams_payload(
    *,
    limit: int,
    sender_id: str | None,
    rorg: str | None,
    direction: str | None,
    runtime_mode: str | None,
    known_filter: str | None,
    time_from_expression: str | None,
    time_to_expression: str | None,
    cursor_timestamp: float | None,
    cursor_telegram_id: int | None,
    hide_foreign: bool = False,
    device_types: str | None = None,
    teach_in: bool | None = None,
) -> dict[str, Any]:
    backend = get_query_backend()
    time_from = parse_time_expression(time_from_expression)
    time_to = parse_time_expression(time_to_expression)
    telegrams, next_cursor = backend.query_telegrams(
        limit=limit,
        sender_id=sender_id,
        rorg=rorg,
        direction=direction,
        runtime_mode=runtime_mode,
        known_filter=known_filter,
        hide_foreign=hide_foreign,
        device_types=device_types,
        teach_in=teach_in,
        time_from=time_from,
        time_to=time_to,
        cursor_timestamp=cursor_timestamp,
        cursor_telegram_id=cursor_telegram_id,
    )

    return {
        "telegrams": telegrams,
        "next_cursor": next_cursor,
        "time_range": {
            "from": time_from_expression,
            "to": time_to_expression,
            "from_unix": time_from,
            "to_unix": time_to,
        },
    }


def _telegram_detail_payload(telegram_id: int) -> dict[str, Any]:
    backend = get_query_backend()
    telegram = backend.get_telegram(telegram_id)

    if telegram is None:
        raise HTTPException(
            status_code=404,
            detail="Telegram not found",
        )

    return {
        "telegram": telegram,
        "decoded": telegram.get("decoded"),
        "decode_error": telegram.get("decode_error"),
    }


def _telegram_decode_payload(telegram_id: int) -> dict[str, Any]:
    detail = _telegram_detail_payload(telegram_id)
    telegram = detail["telegram"]

    return {
        "telegram_id": telegram_id,
        "decoded": detail.get("decoded"),
        "decode_error": detail.get("decode_error"),
        "decoded_tooltip": telegram.get("decoded_tooltip"),
    }


def _export_csv_response(
    *,
    limit: int,
    sender_id: str | None,
    rorg: str | None,
    direction: str | None,
    runtime_mode: str | None,
    known_filter: str | None,
    time_from_expression: str | None,
    time_to_expression: str | None,
    hide_foreign: bool = False,
    device_types: str | None = None,
    teach_in: bool | None = None,
) -> PlainTextResponse:
    backend = get_query_backend()
    telegrams, _ = backend.query_telegrams(
        limit=limit,
        sender_id=sender_id,
        rorg=rorg,
        direction=direction,
        runtime_mode=runtime_mode,
        known_filter=known_filter,
        hide_foreign=hide_foreign,
        device_types=device_types,
        teach_in=teach_in,
        time_from=parse_time_expression(time_from_expression),
        time_to=parse_time_expression(time_to_expression),
        cursor_timestamp=None,
        cursor_telegram_id=None,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "telegram_id",
            "timestamp_unix",
            "direction",
            "runtime_mode",
            "sender_id",
            "destination_id",
            "rorg",
            "data",
            "erp1_status",
            "raw_telegram",
            "rssi_dbm",
            "port",
            "known_device",
        ]
    )

    for telegram in telegrams:
        writer.writerow(
            [
                telegram.get("telegram_id"),
                telegram.get("timestamp_unix"),
                telegram.get("direction"),
                telegram.get("runtime_mode"),
                telegram.get("sender_id"),
                telegram.get("destination_id"),
                telegram.get("rorg"),
                telegram.get("data"),
                telegram.get("erp1_status"),
                telegram.get("raw_telegram"),
                telegram.get("rssi_dbm"),
                telegram.get("port"),
                telegram.get("known_device"),
            ]
        )

    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv",
    )


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/busmonitor")


@app.get("/api/v1/openapi.json")
def get_api_v1_openapi() -> dict[str, Any]:
    return app.openapi()


@app.get("/busmonitor")
def busmonitor_ui(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/health")
@app.get("/api/v1/gateway/health")
def health() -> dict[str, str]:
    return _health_payload()


@app.get("/api/v1/gateway")
def get_gateway() -> dict[str, Any]:
    return _gateway_payload()


@app.get("/api/v1/gateway/status")
def get_gateway_status() -> dict[str, Any]:
    return _gateway_status_payload()


@app.get("/api/v1/gateway/config")
def get_gateway_config() -> dict[str, Any]:
    return _gateway_config_payload()


@app.get("/api/v1/runtime/status")
def get_runtime_status() -> dict[str, Any]:
    return _runtime_status_payload()


@app.get("/api/v1/runtime/diagnostics")
def get_runtime_diagnostics() -> dict[str, Any]:
    return _runtime_diagnostics_payload()


@app.get("/api/v1/interfaces")
def get_interfaces() -> dict[str, Any]:
    _require_interface_controls()
    return interface_status()


@app.get("/api/v1/interfaces/{interface_id}")
def get_interface(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_status(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/v1/interfaces/{interface_id}/connect")
def connect_interface(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_connect(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/v1/interfaces/{interface_id}/disconnect")
def disconnect_interface(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_disconnect(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/v1/interfaces/{interface_id}/reconnect")
def reconnect_interface(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_reconnect(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/v1/interfaces/{interface_id}/network-bridge/start")
def start_interface_network_bridge(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_network_bridge_start(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc


@app.post("/api/v1/interfaces/{interface_id}/network-bridge/stop")
def stop_interface_network_bridge(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_network_bridge_stop(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/v1/interfaces/{interface_id}/network-bridge/restart")
def restart_interface_network_bridge(interface_id: str) -> dict[str, Any]:
    _require_interface_controls()

    try:
        return interface_network_bridge_restart(interface_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc


@app.get("/api/v1/runtime/commands")
def get_runtime_commands() -> dict[str, Any]:
    return _runtime_commands_payload()


@app.post("/api/v1/runtime/commands/{command_name}")
def post_runtime_command(
    command_name: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if runtime_command_dispatcher is None:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "message": "Runtime command dispatch is not configured.",
            },
        )

    try:
        return runtime_command_dispatcher(command_name, payload)
    except RuntimeCommandValidationError as exc:
        status_code = 404 if exc.error_type == "unknown_command" else 400
        raise HTTPException(
            status_code=status_code,
            detail={
                "status": "rejected",
                "error_type": exc.error_type,
                "message": exc.message,
                **exc.details,
            },
        ) from exc
    except RuntimeCommandExecutionError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "message": exc.message,
                **exc.details,
            },
        ) from exc


@app.get("/api/v1/project/export")
def get_project_export() -> dict[str, Any]:
    source = _load_project_export_source()
    return build_enocean_project_export(
        get_runtime_service(),
        project_id=source["project_id"] or "enocean-mqtt",
        base_topic=source["base_topic"],
        generator_version=app.version,
    )


@app.get("/events")
@app.get("/api/v1/busmonitor/stream")
def live_events(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _live_event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/devices")
def get_busmonitor_devices() -> dict[str, Any]:
    return _busmonitor_devices_payload()


@app.get("/api/v1/busmonitor/devices")
def get_busmonitor_api_devices(
    hide_foreign: bool = False, device_types: str | None = None,
) -> dict[str, Any]:
    return _busmonitor_devices_payload(hide_foreign=hide_foreign, device_types=device_types)


@app.get("/api/v1/busmonitor/unknown-devices")
def get_busmonitor_unknown_devices(
    lookback_limit: int = Query(
        UNKNOWN_DEVICE_LOOKBACK_LIMIT,
        ge=1,
        le=100000,
    ),
) -> dict[str, Any]:
    return _unknown_devices_payload(lookback_limit=lookback_limit)


@app.get("/statistics/telegrams-per-hour")
@app.get("/api/v1/busmonitor/metrics/telegrams-per-hour")
def get_telegrams_per_hour() -> dict[str, Any]:
    return _telegrams_per_hour_payload()


@app.get("/telegrams")
@app.get("/api/v1/busmonitor/telegrams")
def get_telegrams(
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
    ),
    sender_id: str | None = None,
    rorg: str | None = None,
    direction: str | None = None,
    runtime_mode: str | None = None,
    known_filter: str | None = Query(None),
    time_from_expression: str | None = Query(
        default=None,
        alias="from",
    ),
    time_to_expression: str | None = Query(
        default=None,
        alias="to",
    ),
    cursor_timestamp: float | None = None,
    cursor_telegram_id: int | None = None,
    hide_foreign: bool = False,
    device_types: str | None = None,
    teach_in: bool | None = None,
) -> dict[str, Any]:
    return _query_telegrams_payload(
        limit=limit,
        sender_id=sender_id,
        rorg=rorg,
        direction=direction,
        runtime_mode=runtime_mode,
        known_filter=known_filter,
        hide_foreign=hide_foreign,
        device_types=device_types,
        teach_in=teach_in,
        time_from_expression=time_from_expression,
        time_to_expression=time_to_expression,
        cursor_timestamp=cursor_timestamp,
        cursor_telegram_id=cursor_telegram_id,
    )


@app.get("/telegrams/{telegram_id}")
@app.get("/api/v1/busmonitor/telegrams/{telegram_id}")
def get_telegram_detail(telegram_id: int) -> dict[str, Any]:
    return _telegram_detail_payload(telegram_id)


@app.get("/api/v1/busmonitor/telegrams/{telegram_id}/decode")
def get_telegram_decode(telegram_id: int) -> dict[str, Any]:
    return _telegram_decode_payload(telegram_id)


@app.get("/api/v1/metrics")
def get_metrics() -> dict[str, Any]:
    return {
        "gateway": _gateway_status_payload(),
        "busmonitor": _telegrams_per_hour_payload(),
    }


@app.get("/api/v1/metrics/gateway")
def get_gateway_metrics() -> dict[str, Any]:
    return _gateway_status_payload()


@app.get("/api/v1/metrics/devices")
def get_device_metrics() -> dict[str, Any]:
    devices = get_runtime_service().get_devices()
    states = get_runtime_service().get_device_states()
    return {
        "devices_count": devices.get("count", 0),
        "device_states_count": len(states),
    }


@app.get("/api/v1/metrics/busmonitor")
def get_busmonitor_metrics() -> dict[str, Any]:
    return _telegrams_per_hour_payload()


@app.get("/api/v1/eeps")
def get_eeps() -> dict[str, Any]:
    return _eeps_payload()


@app.get("/api/v1/eeps/{eep_id}")
def get_eep(eep_id: str) -> dict[str, Any]:
    return _eep_payload(eep_id)


@app.get("/api/v1/eeps/{eep_id}/channels")
def get_eep_channels(eep_id: str) -> dict[str, Any]:
    return _eep_section_payload(eep_id, "channels")


@app.get("/api/v1/eeps/{eep_id}/messages")
def get_eep_messages(eep_id: str) -> dict[str, Any]:
    return _eep_section_payload(eep_id, "messages")


@app.get("/api/v1/eeps/{eep_id}/datapoint-template")
def get_eep_datapoint_template(eep_id: str) -> dict[str, Any]:
    return _eep_datapoint_template_payload(eep_id)


@app.get("/api/v1/eeps/{eep_id}/interactions")
def get_eep_interactions(eep_id: str) -> dict[str, Any]:
    eep = _eep_payload(eep_id)["eep"]
    return {
        "eep": eep_id,
        "channel_bindings": eep.get("channel_bindings", []),
        "message_bindings": eep.get("message_bindings", []),
    }


@app.get("/api/v1/profiles")
def get_profiles() -> dict[str, Any]:
    return _profiles_payload()


@app.get("/api/v1/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict[str, Any]:
    return _profile_payload(profile_id)


@app.get("/api/v1/profiles/{profile_id}/channels")
def get_profile_channels(profile_id: str) -> dict[str, Any]:
    return _profile_section_payload(profile_id, "channels")


@app.get("/api/v1/profiles/{profile_id}/messages")
def get_profile_messages(profile_id: str) -> dict[str, Any]:
    return _profile_section_payload(profile_id, "messages")


@app.get("/api/v1/profiles/{profile_id}/datapoint-template")
def get_profile_datapoint_template(profile_id: str) -> dict[str, Any]:
    return _profile_datapoint_template_payload(profile_id)


@app.get("/api/v1/profile-drafts")
def get_profile_drafts() -> dict[str, Any]:
    return {
        "drafts": [],
        "count": 0,
        "issues": [
            _not_implemented_payload(
                "Profile draft persistence is not implemented yet.",
            )
        ],
    }


@app.post("/api/v1/profile-drafts")
def create_profile_draft(payload: dict[str, Any]) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail=_not_implemented_payload(
            "Profile draft creation is not implemented yet.",
        ),
    )


@app.get("/api/v1/profile-drafts/{draft_id}")
def get_profile_draft(draft_id: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail=_not_implemented_payload(
            "Profile draft lookup is not implemented yet.",
        ),
    )


@app.patch("/api/v1/profile-drafts/{draft_id}")
def update_profile_draft(
    draft_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail=_not_implemented_payload(
            "Profile draft updates are not implemented yet.",
        ),
    )


@app.post("/api/v1/profile-drafts/{draft_id}/validate")
def validate_profile_draft(draft_id: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail=_not_implemented_payload(
            "Profile draft validation is not implemented yet.",
        ),
    )


@app.post("/api/v1/profile-drafts/{draft_id}/approve")
def approve_profile_draft(draft_id: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail=_not_implemented_payload(
            "Profile draft approval is not implemented yet.",
        ),
    )


@app.delete("/api/v1/profile-drafts/{draft_id}")
def delete_profile_draft(draft_id: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail=_not_implemented_payload(
            "Profile draft deletion is not implemented yet.",
        ),
    )


@app.get("/export/csv")
@app.get("/api/v1/busmonitor/export/csv")
def export_csv(
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
    ),
    sender_id: str | None = None,
    rorg: str | None = None,
    direction: str | None = None,
    runtime_mode: str | None = None,
    known_filter: str | None = None,
    time_from_expression: str | None = Query(
        default=None,
        alias="from",
    ),
    time_to_expression: str | None = Query(
        default=None,
        alias="to",
    ),
    hide_foreign: bool = False,
    device_types: str | None = None,
    teach_in: bool | None = None,
) -> PlainTextResponse:
    return _export_csv_response(
        limit=limit,
        sender_id=sender_id,
        rorg=rorg,
        direction=direction,
        runtime_mode=runtime_mode,
        known_filter=known_filter,
        hide_foreign=hide_foreign,
        device_types=device_types,
        teach_in=teach_in,
        time_from_expression=time_from_expression,
        time_to_expression=time_to_expression,
    )
