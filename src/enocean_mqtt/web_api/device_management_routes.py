"""API routes backing the Device Management Web UI."""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import tempfile
import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from enocean_mqtt.devices.csv_format import export_csv, import_csv
from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.gateway.runtime_commands import RuntimeCommandExecutionError
from enocean_mqtt.gateway.runtime_schema import RuntimeCommandValidationError
from enocean_mqtt.virtual_devices.models import VirtualDevice
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry

RuntimeCommandDispatcher = Callable[
    [str, dict[str, Any] | None],
    dict[str, Any],
]
RuntimeCommandDispatcherProvider = Callable[[], RuntimeCommandDispatcher | None]
UnknownDevicesProvider = Callable[..., dict[str, Any]]

TEACH_IN_RECEIVERS_KEY = "teach_in_receivers"
TX_CAPABLE_COMMUNICATION = {
    "bidirectional_eep",
    "bidirectional_eep_pair",
}
EEP_PATTERN = re.compile(r"^[0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2}$")


def create_device_management_router(
    *,
    devices_file: str | Path,
    virtual_devices_file: str | Path,
    sqlite_database: str | Path,
    config_file: str | Path,
    eep_registry_directory: str | Path,
    runtime_command_dispatcher_provider: RuntimeCommandDispatcherProvider,
    unknown_devices_provider: UnknownDevicesProvider,
) -> APIRouter:
    """Create the API surface used by the Device Management Web UI."""

    router = APIRouter(
        prefix="/api/v1/device-management",
        tags=["Device Management"],
    )
    physical_path = Path(devices_file)
    virtual_path = Path(virtual_devices_file)
    database_path = Path(sqlite_database)
    runtime_config_path = Path(config_file)
    profile_directory = Path(eep_registry_directory)
    controller_mapping_path = runtime_config_path.parent / "device-controller-mappings.json"

    def dispatch(command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        dispatcher = runtime_command_dispatcher_provider()
        if dispatcher is None:
            raise HTTPException(
                status_code=503,
                detail="Runtime command dispatch is not available.",
            )
        try:
            return dispatcher(command, payload)
        except RuntimeCommandValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        except RuntimeCommandExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc

    @router.get("")
    def get_device_management(request: Request) -> dict[str, Any]:
        physical_registry, physical_issues = _physical_registry(physical_path)
        virtual_registry, virtual_issues = _virtual_registry(virtual_path)
        sender_ids = {
            device.device_id.strip().upper()
            for device in physical_registry.devices
        }
        sender_ids.update(
            device.sender_id.strip().upper()
            for device in virtual_registry.devices
        )
        latest = _latest_telegrams(database_path, sender_ids)
        active_window_seconds = _active_window_seconds(runtime_config_path)
        active_sender_ids = _active_sender_ids(
            database_path,
            {
                device.device_id.strip().upper()
                for device in physical_registry.devices
            },
            active_window_seconds,
        )
        unknown_payload = unknown_devices_provider(lookback_limit=None)
        unknown_devices = list(unknown_payload.get("unknown_devices") or [])

        physical_devices = [
            {
                **device.model_dump(mode="json"),
                "registry_profile": device.registry_profile,
                "tx_registry_profile": device.tx_registry_profile,
                "tx_capable": device.communication in TX_CAPABLE_COMMUNICATION,
                "active": device.device_id.strip().upper() in active_sender_ids,
                "last_telegram": latest.get(device.device_id.strip().upper()),
                "teach_in_receivers": _teach_in_receivers(device.metadata),
            }
            for device in physical_registry.devices
        ]
        virtual_devices = [
            {
                **device.model_dump(mode="json"),
                "registry_profile": device.registry_profile,
                "last_telegram": latest.get(device.sender_id.strip().upper()),
                "teach_in_receivers": _teach_in_receivers(device.metadata),
            }
            for device in virtual_registry.devices
        ]

        return {
            "status": "ok" if not physical_issues and not virtual_issues else "warning",
            "can_write": "admin" in getattr(request.state, "web_roles", set()),
            "counts": {
                "devices": len(physical_devices),
                "unknown_devices": len(unknown_devices),
                "virtual_devices": len(virtual_devices),
                "active_devices": len(active_sender_ids),
            },
            "active_window_seconds": active_window_seconds,
            "physical_devices": physical_devices,
            "virtual_devices": virtual_devices,
            "unknown_devices": unknown_devices,
            "unknown_source": unknown_payload.get("source"),
            "issues": [
                *physical_issues,
                *virtual_issues,
                *(unknown_payload.get("issues") or []),
            ],
        }

    @router.get("/profiles")
    def get_profiles() -> dict[str, Any]:
        profiles = sorted(
            path.stem
            for path in profile_directory.glob("*.json")
            if path.is_file()
        )
        return {"profiles": profiles, "count": len(profiles)}

    @router.get("/options")
    def get_device_options() -> dict[str, Any]:
        registry = DeviceRegistry.from_json(physical_path)
        definitions = _registry_definitions(profile_directory)
        mappings = _controller_mappings(controller_mapping_path)
        return {
            "eeps": [item for item in definitions if item["kind"] == "eep"],
            "profiles": [item for item in definitions if item["kind"] == "profile"],
            "controller_mappings": mappings,
            "suggestions": {
                "manufacturers": _distinct(device.manufacturer for device in registry.devices),
                "models": _distinct(device.model for device in registry.devices),
                "floors": _distinct(device.metadata.get("floor") for device in registry.devices),
                "rooms": _distinct(device.metadata.get("room") for device in registry.devices),
            },
        }

    @router.post("/physical")
    def create_physical_device(payload: dict[str, Any]) -> dict[str, Any]:
        registry = DeviceRegistry.from_json(physical_path)
        device = _prepare_physical_device(
            payload,
            registry=registry,
            profile_directory=profile_directory,
            controller_mapping_path=controller_mapping_path,
            existing_device_id=None,
        )
        result = dispatch("device.import", {"device": device.model_dump(mode="json")})
        return {**result, "device": device.model_dump(mode="json")}

    @router.put("/physical/{device_id}")
    def update_physical_device(device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = device_id.strip().upper()
        registry = DeviceRegistry.from_json(physical_path)
        existing = registry.get_by_device_id(normalized)
        if existing is None:
            raise HTTPException(status_code=404, detail="Physical device not found")
        supplied_device_id = str(payload.get("device_id") or normalized).strip().upper()
        if supplied_device_id != normalized:
            raise HTTPException(status_code=422, detail="device_id cannot be changed after registration")
        device = _prepare_physical_device(
            {**payload, "device_id": normalized},
            registry=registry,
            profile_directory=profile_directory,
            controller_mapping_path=controller_mapping_path,
            existing_device_id=normalized,
        )
        result = dispatch("device.import", {"device": device.model_dump(mode="json")})
        return {**result, "device": device.model_dump(mode="json")}

    @router.delete("/physical/{device_id}")
    def delete_physical_device(device_id: str) -> dict[str, Any]:
        return dispatch("device.delete", {"device_id": device_id.strip().upper()})

    @router.post("/physical/{device_id}/teach-in")
    def teach_in_physical_device(
        device_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            "device.teach_in",
            {
                "device_id": device_id.strip().upper(),
                **({"teach_in": payload} if payload else {}),
            },
        )

    @router.post("/physical/{device_id}/teach-in-confirmations")
    def confirm_physical_teach_in(
        device_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        registry = DeviceRegistry.from_json(physical_path)
        device = registry.get_by_device_id(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Physical device not found")
        updated, confirmation = _add_teach_in_confirmation(device, payload)
        dispatch("device.import", {"device": updated.model_dump(mode="json")})
        return {"status": "confirmed", "confirmation": confirmation}

    @router.post("/virtual")
    def create_virtual_device(payload: dict[str, Any]) -> dict[str, Any]:
        virtual_payload = _virtual_payload(payload)
        result = dispatch("virtual_device.create", {"virtual_device": virtual_payload})
        return {**result, "virtual_device": virtual_payload}

    @router.put("/virtual/{virtual_device_id}")
    def update_virtual_device(
        virtual_device_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        virtual_payload = _virtual_payload(
            {**payload, "virtual_device_id": virtual_device_id.strip().lower()}
        )
        result = dispatch("virtual_device.create", {"virtual_device": virtual_payload})
        return {**result, "virtual_device": virtual_payload}

    @router.delete("/virtual/{virtual_device_id}")
    def delete_virtual_device(virtual_device_id: str) -> dict[str, Any]:
        return dispatch(
            "virtual_device.delete",
            {"virtual_device_id": virtual_device_id.strip().lower()},
        )

    @router.post("/virtual/{virtual_device_id}/teach-in")
    def teach_in_virtual_device(virtual_device_id: str) -> dict[str, Any]:
        return dispatch(
            "virtual_device.teach_in",
            {"virtual_device_id": virtual_device_id.strip().lower()},
        )

    @router.post("/virtual/{virtual_device_id}/teach-in-confirmations")
    def confirm_virtual_teach_in(
        virtual_device_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        registry = VirtualDeviceRegistry.from_json(virtual_path)
        device = registry.get_by_id(virtual_device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Virtual device not found")
        updated, confirmation = _add_virtual_teach_in_confirmation(device, payload)
        dispatch(
            "virtual_device.create",
            {"virtual_device": updated.model_dump(mode="json")},
        )
        return {"status": "confirmed", "confirmation": confirmation}

    @router.post("/reload")
    def reload_devices() -> dict[str, Any]:
        return dispatch("devices.reload", {})

    @router.post("/import/preview")
    def preview_devices_import(payload: dict[str, Any]) -> dict[str, Any]:
        return _import_preview(str(payload.get("csv") or ""), physical_path)

    @router.post("/import")
    def import_devices_csv(payload: dict[str, Any]) -> dict[str, Any]:
        csv_content = str(payload.get("csv") or "")
        preview = _import_preview(csv_content, physical_path)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".csv",
                newline="",
                delete=False,
            ) as handle:
                handle.write(csv_content)
                temporary_path = Path(handle.name)
            result = dispatch("devices.import", {"import_file": str(temporary_path)})
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return {**result, "preview": preview}

    @router.get("/export/devices.csv")
    def export_devices_csv() -> Response:
        registry = DeviceRegistry.from_json(physical_path)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as handle:
                temporary_path = Path(handle.name)
            export_csv(registry, temporary_path)
            content = temporary_path.read_bytes()
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="devices.csv"'},
        )

    @router.get("/export/unknown-devices.csv")
    def export_unknown_devices_csv() -> Response:
        unknown = unknown_devices_provider(lookback_limit=None)
        output = io.StringIO(newline="")
        fields = [
            "sender_id",
            "rorg",
            "telegrams",
            "first_seen",
            "last_seen",
            "last_rssi_dbm",
            "last_data",
            "last_raw_telegram",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unknown.get("unknown_devices") or [])
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="unknown-devices.csv"'
            },
        )

    return router


def _prepare_physical_device(
    payload: Mapping[str, Any],
    *,
    registry: DeviceRegistry,
    profile_directory: Path,
    controller_mapping_path: Path,
    existing_device_id: str | None,
) -> Device:
    candidate = dict(payload)
    device_id = str(candidate.get("device_id") or "").strip().upper()
    device_name = str(candidate.get("device_name") or "").strip()
    if not device_id or not device_name:
        raise HTTPException(status_code=422, detail="device_id and device_name are required")

    alias = _alias_from_device_name(device_name)
    if not alias:
        raise HTTPException(status_code=422, detail="device_name does not produce a valid alias")
    candidate["device_id"] = device_id
    candidate["device_name"] = device_name
    candidate["alias"] = alias

    _validate_unique_device_fields(
        registry,
        candidate,
        existing_device_id=existing_device_id,
    )
    _apply_registry_binding(
        candidate,
        profile_directory=profile_directory,
        controller_mapping_path=controller_mapping_path,
    )
    return _validated_device(candidate)


def _validated_device(payload: Mapping[str, Any]) -> Device:
    try:
        return Device.model_validate(dict(payload))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_unique_device_fields(
    registry: DeviceRegistry,
    candidate: Mapping[str, Any],
    *,
    existing_device_id: str | None,
) -> None:
    current_id = (existing_device_id or "").upper()
    candidate_name = str(candidate.get("device_name") or "").strip().casefold()
    candidate_alias = str(candidate.get("alias") or "").strip().casefold()
    candidate_equipment = str(
        (candidate.get("metadata") or {}).get("equipment_id") or ""
    ).strip().casefold()
    candidate_id = str(candidate.get("device_id") or "").strip().upper()

    for device in registry.devices:
        if current_id and device.device_id.strip().upper() == current_id:
            continue
        if device.device_id.strip().upper() == candidate_id:
            raise HTTPException(status_code=409, detail="Device ID is already registered")
        if device.device_name.strip().casefold() == candidate_name:
            raise HTTPException(status_code=409, detail="Device name is already in use")
        if candidate_alias and str(device.alias or "").strip().casefold() == candidate_alias:
            raise HTTPException(status_code=409, detail="Generated alias is already in use")
        existing_equipment = str(device.metadata.get("equipment_id") or "").strip().casefold()
        if candidate_equipment and existing_equipment == candidate_equipment:
            raise HTTPException(status_code=409, detail="Equipment ID is already in use")


def _alias_from_device_name(device_name: str) -> str:
    value = device_name.strip().lower()
    for source, replacement in {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }.items():
        value = value.replace(source, replacement)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[\s-]+", "_", value)
    value = re.sub(r"[^a-z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def _registry_definitions(profile_directory: Path) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    for path in sorted(profile_directory.glob("*.json"), key=lambda item: item.stem.casefold()):
        if not path.is_file():
            continue
        identifier = path.stem.upper() if EEP_PATTERN.fullmatch(path.stem.upper()) else path.stem.lower()
        payload: dict[str, Any] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            pass
        kind = "eep" if EEP_PATTERN.fullmatch(identifier.upper()) else "profile"
        definitions.append(
            {
                "id": identifier,
                "kind": kind,
                "direction": payload.get("direction"),
                "device_class": payload.get("device_class"),
                "description": payload.get("description") or payload.get("type_description"),
            }
        )
    return definitions


def _controller_mappings(mapping_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    mappings = payload.get("mappings", []) if isinstance(payload, dict) else []
    return [dict(item) for item in mappings if isinstance(item, dict)]


def _apply_registry_binding(
    candidate: dict[str, Any],
    *,
    profile_directory: Path,
    controller_mapping_path: Path,
) -> None:
    definitions = {item["id"]: item for item in _registry_definitions(profile_directory)}
    eep = str(candidate.get("eep") or "").strip()
    profile = str(candidate.get("profile") or "").strip()
    if eep:
        eep = eep.upper()
        if eep not in definitions or definitions[eep]["kind"] != "eep":
            raise HTTPException(status_code=422, detail=f"EEP '{eep}' is not available in the EEP registry")
        candidate["eep"] = eep
    else:
        candidate["eep"] = None

    if profile:
        normalized_profile = profile.upper() if EEP_PATTERN.fullmatch(profile.upper()) else profile.lower()
        if normalized_profile not in definitions:
            raise HTTPException(status_code=422, detail=f"Profile '{profile}' is not available in the registry")
        candidate["profile"] = normalized_profile
    elif eep:
        candidate["profile"] = eep
    else:
        raise HTTPException(status_code=422, detail="An EEP or proprietary profile must be selected")

    selected_profile = str(candidate.get("profile") or "")
    selected_definition = definitions.get(selected_profile) or definitions.get(eep)
    mapping = next(
        (
            item
            for item in _controller_mappings(controller_mapping_path)
            if str(item.get("device_eep") or "").strip().casefold()
            in {eep.casefold(), selected_profile.casefold()}
        ),
        None,
    )

    candidate["tx_eep"] = None
    candidate["tx_profile"] = None
    if mapping:
        sender = str(mapping.get("sender_eep") or "").strip()
        if sender:
            normalized_sender = sender.upper() if EEP_PATTERN.fullmatch(sender.upper()) else sender.lower()
            if normalized_sender not in definitions:
                raise HTTPException(
                    status_code=422,
                    detail=f"Mapped TX profile '{normalized_sender}' is not available in the registry",
                )
            if definitions[normalized_sender]["kind"] == "eep":
                candidate["tx_eep"] = normalized_sender
            candidate["tx_profile"] = normalized_sender
        candidate["communication"] = "bidirectional_eep_pair"
    elif selected_definition and str(selected_definition.get("direction") or "").lower() == "bidirectional":
        candidate["communication"] = "bidirectional_eep"
    else:
        candidate["communication"] = "unidirectional"


def _distinct(values: Any) -> list[str]:
    normalized = {
        str(value).strip()
        for value in values
        if value is not None and str(value).strip()
    }
    return sorted(normalized, key=str.casefold)


def _virtual_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(payload)
    candidate.pop("sender_id", None)
    candidate.pop("teach_in_method", None)
    candidate.pop("teach_in_telegram", None)
    try:
        virtual_device_id = str(candidate["virtual_device_id"]).strip().lower()
        eep = str(candidate.get("eep") or candidate.get("profile") or "").strip()
        channels = candidate.get("channels")
        if not virtual_device_id or not eep:
            raise ValueError("virtual_device_id and eep/profile are required")
        if not isinstance(channels, list) or not channels:
            raise ValueError("at least one channel is required")
        candidate["virtual_device_id"] = virtual_device_id
        candidate["eep"] = eep.upper() if "-" in eep else eep
        candidate["channels"] = [str(value).strip() for value in channels if str(value).strip()]
        return candidate
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _physical_registry(path: Path) -> tuple[DeviceRegistry, list[dict[str, Any]]]:
    try:
        return DeviceRegistry.from_json(path), []
    except Exception as exc:
        return DeviceRegistry([]), [{"source": "devices", "message": str(exc)}]


def _virtual_registry(path: Path) -> tuple[VirtualDeviceRegistry, list[dict[str, Any]]]:
    try:
        return VirtualDeviceRegistry.from_json(path), []
    except Exception as exc:
        return VirtualDeviceRegistry([]), [
            {"source": "virtual_devices", "message": str(exc)}
        ]


def _teach_in_receivers(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = metadata.get(TEACH_IN_RECEIVERS_KEY)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _confirmation(payload: Mapping[str, Any]) -> dict[str, Any]:
    receiver = str(payload.get("receiver") or "").strip()
    if not receiver:
        raise HTTPException(status_code=422, detail="Receiver must not be empty")
    return {
        "receiver": receiver,
        "status": "user_confirmed",
        "confirmed_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        **(
            {"notes": str(payload["notes"]).strip()}
            if str(payload.get("notes") or "").strip()
            else {}
        ),
    }


def _add_teach_in_confirmation(
    device: Device,
    payload: Mapping[str, Any],
) -> tuple[Device, dict[str, Any]]:
    confirmation = _confirmation(payload)
    metadata = dict(device.metadata)
    receivers = _teach_in_receivers(metadata)
    receiver_key = str(confirmation["receiver"]).casefold()
    receivers = [
        item
        for item in receivers
        if str(item.get("receiver") or "").casefold() != receiver_key
    ]
    receivers.append(confirmation)
    metadata[TEACH_IN_RECEIVERS_KEY] = receivers
    return device.model_copy(update={"metadata": metadata}), confirmation


def _add_virtual_teach_in_confirmation(
    device: VirtualDevice,
    payload: Mapping[str, Any],
) -> tuple[VirtualDevice, dict[str, Any]]:
    confirmation = _confirmation(payload)
    metadata = dict(device.metadata)
    receivers = _teach_in_receivers(metadata)
    receiver_key = str(confirmation["receiver"]).casefold()
    receivers = [
        item
        for item in receivers
        if str(item.get("receiver") or "").casefold() != receiver_key
    ]
    receivers.append(confirmation)
    metadata[TEACH_IN_RECEIVERS_KEY] = receivers
    return device.model_copy(update={"metadata": metadata}), confirmation


def _active_window_seconds(config_file: Path) -> int:
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
        return max(
            1,
            int(payload.get("metrics", {}).get("active_device_window_seconds", 86400)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 86400


def _active_sender_ids(
    database_path: Path,
    sender_ids: set[str],
    window_seconds: int,
) -> set[str]:
    if not database_path.exists() or not sender_ids:
        return set()
    placeholders = ", ".join("?" for _ in sender_ids)
    threshold = datetime.now(UTC).timestamp() - window_seconds
    try:
        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT sender_id
                FROM telegrams
                WHERE sender_id IN ({placeholders}) AND timestamp_unix >= ?
                """,
                [*sorted(sender_ids), threshold],
            ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]).strip().upper() for row in rows if row[0]}


def _latest_telegrams(
    database_path: Path,
    sender_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if not database_path.exists() or not sender_ids:
        return {}
    placeholders = ", ".join("?" for _ in sender_ids)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        with connection:
            rows = connection.execute(
                f"""
                SELECT sender_id, timestamp_unix, direction, rorg, data,
                       raw_telegram, rssi_dbm
                FROM telegrams
                WHERE sender_id IN ({placeholders})
                ORDER BY timestamp_unix DESC, telegram_id DESC
                """,
                sorted(sender_ids),
            ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        if connection is not None:
            connection.close()

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        sender_id = str(row["sender_id"] or "").strip().upper()
        if not sender_id or sender_id in latest:
            continue
        timestamp = row["timestamp_unix"]
        latest[sender_id] = {
            "timestamp": _timestamp(timestamp),
            "timestamp_unix": timestamp,
            "direction": row["direction"],
            "rorg": _hex(row["rorg"]),
            "data": _hex(row["data"]),
            "raw_telegram": _hex(row["raw_telegram"]),
            "rssi_dbm": row["rssi_dbm"],
        }
    return latest


def _timestamp(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat(timespec="milliseconds")
    except (TypeError, ValueError, OSError):
        return None


def _hex(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return " ".join(f"{byte:02X}" for byte in value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    return " ".join(text[index : index + 2].upper() for index in range(0, len(text), 2))


def _import_preview(csv_content: str, devices_file: Path) -> dict[str, Any]:
    if not csv_content.strip():
        raise HTTPException(status_code=422, detail="CSV content must not be empty")
    existing = DeviceRegistry.from_json(devices_file)
    existing_ids = {device.device_id.strip().upper() for device in existing.devices}
    messages: list[dict[str, str]] = []
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".csv",
            newline="",
            delete=False,
        ) as handle:
            handle.write(csv_content)
            temporary_path = Path(handle.name)
        registry = import_csv(
            temporary_path,
            existing_registry=existing,
            log_callback=lambda level, component, message: messages.append(
                {"level": level, "component": component, "message": message}
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    resulting_ids = {device.device_id.strip().upper() for device in registry.devices}
    imported_ids = {
        device_id
        for device_id in resulting_ids
        if any(device_id in item["message"] for item in messages)
    }
    return {
        "valid": not any(item["level"] == "error" for item in messages),
        "created": len(imported_ids - existing_ids),
        "updated": len(imported_ids & existing_ids),
        "total_after_import": len(registry.devices),
        "messages": messages,
    }
