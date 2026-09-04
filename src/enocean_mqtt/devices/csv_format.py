"""CSV import/export helpers for device registry."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry

TRUE_VALUES = {"1", "true", "yes", "on"}

DEVICE_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{8}$")
EEP_PATTERN = re.compile(r"^[A-F0-9]{2}-[A-F0-9]{2}-[A-F0-9]{2}$")
PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9\-]+$")
ALIAS_INVALID_PATTERN = re.compile(r"[^a-z0-9_]+")
ALIAS_SEPARATOR_PATTERN = re.compile(r"_+")

GERMAN_ALIAS_REPLACEMENTS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "Ä": "ae",
    "Ö": "oe",
    "Ü": "ue",
    "ß": "ss",
}


CSV_FIELDS = [
    "device_id",
    "device_name",
    "alias",
    "eep",
    "profile",
    "description",
    "manufacturer",
    "model",
    "communication",
    "tx_eep",
    "tx_profile",
    "sender_id",
    "enocean_secure",
    "enabled",
    "floor",
    "room",
    "equipment_id",
]


SUPPORTED_ENCODINGS = [
    "utf-8",
    "utf-8-sig",
    "cp1252",
    "iso-8859-1",
]


LogCallback = Callable[[str, str, str], None]


def parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse relaxed boolean string."""

    if value is None:
        return default

    return value.strip().lower() in TRUE_VALUES


def _normalize_optional(value: str | None) -> str | None:
    """Normalize optional CSV values."""

    normalized = (value or "").strip()

    if not normalized:
        return None

    if normalized.lower() == "null":
        return None

    return normalized


def _replace_german_umlauts(value: str) -> str:
    """Replace German umlauts with MQTT-friendly transliterations."""

    normalized = value

    for source, replacement in GERMAN_ALIAS_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)

    return normalized


def _generate_alias(value: str) -> str:
    """Generate a stable MQTT-friendly alias from a human-readable name."""

    normalized = _replace_german_umlauts(value)
    normalized = unicodedata.normalize("NFKD", normalized)

    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")

    alias = (
        ascii_value.lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    alias = ALIAS_INVALID_PATTERN.sub("_", alias)
    alias = ALIAS_SEPARATOR_PATTERN.sub("_", alias).strip("_")

    return alias or "device"


def _generate_profile(value: str) -> str:
    """Generate stable registry profile ID from a proprietary profile value."""

    return value.strip().lower()


def _normalize_alias(
    alias: str | None,
    device_name: str,
) -> str:
    """Return configured alias or generate one from device_name."""

    configured_alias = _normalize_optional(alias)

    if configured_alias:
        return _generate_alias(configured_alias)

    return _generate_alias(device_name)


def _normalize_profile(
    eep: str | None,
    profile: str | None,
) -> tuple[str | None, str | None]:
    """Resolve EEP/profile with proprietary profile fallback."""

    if profile:
        return eep, _generate_profile(profile)

    if eep is None:
        return None, None

    if EEP_PATTERN.match(eep):
        return eep.upper(), eep.upper()

    return None, _generate_profile(eep)


def _open_csv_reader(path: str | Path) -> tuple[TextIO, csv.DictReader[str]]:
    """Open CSV reader with encoding and delimiter auto detection."""

    csv_path = Path(path)
    last_error: Exception | None = None

    for encoding in SUPPORTED_ENCODINGS:
        try:
            handle = csv_path.open("r", encoding=encoding, newline="")
            sample = handle.read(4096)
            handle.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            reader = csv.DictReader(handle, dialect=dialect)

            return handle, reader

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"Unable to read CSV file '{csv_path}'. Last error: {last_error}"
    )


def _validate_device_id(device_id: str) -> None:
    """Validate device ID format."""

    if not DEVICE_ID_PATTERN.match(device_id):
        raise ValueError(
            f"Invalid device_id format: {device_id}"
        )


def _validate_eep(eep: str | None) -> None:
    """Validate EEP format."""

    if eep is None:
        return

    if not EEP_PATTERN.match(eep):
        raise ValueError(f"Invalid EEP format: {eep}")


def _validate_profile(profile: str | None) -> None:
    """Validate profile format."""

    if profile is None:
        return

    if not PROFILE_PATTERN.match(profile):
        raise ValueError(f"Invalid profile format: {profile}")


def import_csv(
    path: str | Path,
    existing_registry: DeviceRegistry | None = None,
    log_callback: LogCallback | None = None,
) -> DeviceRegistry:
    """Import device registry from CSV with validation and upsert support."""

    existing_devices: dict[str, Device] = {}

    if existing_registry is not None:
        existing_devices = {
            device.device_id.upper(): device
            for device in existing_registry.devices
        }

    imported_device_ids: set[str] = set()
    handle, reader = _open_csv_reader(path)

    with handle:
        for line_number, row in enumerate(reader, start=2):
            device_id = (row.get("device_id") or "").strip().upper()

            if not device_id:
                if log_callback:
                    log_callback(
                        "warning",
                        "device-import",
                        f"Line {line_number}: missing device_id ignored",
                    )

                continue

            try:
                _validate_device_id(device_id)
            except ValueError as exc:
                if log_callback:
                    log_callback(
                        "error",
                        "device-import",
                        str(exc),
                    )

                continue

            if device_id in imported_device_ids:
                if log_callback:
                    log_callback(
                        "warning",
                        "device-import",
                        (
                            f"Duplicate device_id in CSV ignored: "
                            f"{device_id}"
                        ),
                    )

                continue

            imported_device_ids.add(device_id)

            raw_eep = _normalize_optional(row.get("eep"))
            raw_profile = _normalize_optional(row.get("profile"))
            eep, profile = _normalize_profile(raw_eep, raw_profile)

            if not eep and not profile:
                if log_callback:
                    log_callback(
                        "error",
                        "device-import",
                        (
                            f"Missing eep/profile for device_id "
                            f"{device_id}"
                        ),
                    )

                continue

            try:
                _validate_eep(eep)
                _validate_profile(profile)
            except ValueError as exc:
                if log_callback:
                    log_callback(
                        "error",
                        "device-import",
                        str(exc),
                    )

                continue

            existing_device = existing_devices.get(device_id)
            metadata = (
                dict(existing_device.metadata)
                if existing_device is not None
                else {}
            )
            floor = (row.get("floor") or "").strip()
            room = (row.get("room") or "").strip()
            equipment_id = (
                (row.get("equipment_id") or row.get("bmk") or "")
                .strip()
            )

            if floor:
                metadata["floor"] = floor

            if room:
                metadata["room"] = room

            if equipment_id:
                metadata["equipment_id"] = equipment_id

            device_name = (row.get("device_name") or device_id).strip()
            communication = _normalize_optional(row.get("communication"))
            if communication is None and existing_device is not None:
                communication = existing_device.communication
            communication = communication or "unidirectional"

            device_kwargs = {
                "device_id": device_id,
                "device_name": device_name,
                "alias": _normalize_alias(row.get("alias"), device_name),
                "eep": eep,
                "profile": profile,
                "description": _normalize_optional(row.get("description")),
                "manufacturer": _normalize_optional(row.get("manufacturer")),
                "model": _normalize_optional(row.get("model")),
                "communication": communication,
                "tx_eep": _normalize_optional(row.get("tx_eep")),
                "tx_profile": _normalize_optional(row.get("tx_profile")),
                "sender_id": _normalize_optional(row.get("sender_id")),
                "enocean_secure": parse_bool(
                    row.get("enocean_secure"),
                    default=(
                        existing_device.enocean_secure
                        if existing_device is not None
                        else False
                    ),
                ),
                "enabled": parse_bool(
                    row.get("enabled"),
                    default=(
                        existing_device.enabled
                        if existing_device is not None
                        else True
                    ),
                ),
                "metadata": metadata,
            }

            if existing_device is not None:
                device_kwargs.update(
                    {
                        "communication": communication,
                        "tx_eep": (
                            device_kwargs["tx_eep"] or existing_device.tx_eep
                        ),
                        "tx_profile": (
                            device_kwargs["tx_profile"] or existing_device.tx_profile
                        ),
                        "sender_id": (
                            device_kwargs["sender_id"] or existing_device.sender_id
                        ),
                    }
                )

            device = Device.model_validate(device_kwargs)

            if existing_device is not None:
                if log_callback:
                    log_callback(
                        "info",
                        "device-import",
                        (
                            f"Existing device updated from CSV import: "
                            f"{device_id}"
                        ),
                    )
            else:
                if log_callback:
                    log_callback(
                        "info",
                        "device-import",
                        f"New device imported: {device_id}",
                    )

            existing_devices[device_id] = device

    if log_callback:
        log_callback(
            "info",
            "device-import",
            (
                f"CSV import completed: {len(existing_devices)} "
                f"devices in registry"
            ),
        )

    devices = sorted(
        existing_devices.values(),
        key=lambda device: device.device_id,
    )

    return DeviceRegistry(devices)


def export_csv(registry: DeviceRegistry, path: str | Path) -> None:
    """Export registry as CSV."""

    csv_path = Path(path)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)

        writer.writeheader()

        for device in registry.devices:
            exported_profile = device.profile

            if exported_profile == device.eep:
                exported_profile = ""

            writer.writerow(
                {
                    "device_id": device.device_id,
                    "device_name": device.device_name,
                    "alias": device.alias or "",
                    "eep": device.eep or "",
                    "profile": exported_profile or "",
                    "description": device.description or "",
                    "manufacturer": device.manufacturer or "",
                    "model": device.model or "",
                    "communication": device.communication,
                    "tx_eep": device.tx_eep or "",
                    "tx_profile": device.tx_profile or "",
                    "sender_id": device.sender_id or "",
                    "enocean_secure": str(device.enocean_secure).lower(),
                    "enabled": str(device.enabled).lower(),
                    "floor": device.metadata.get("floor", ""),
                    "room": device.metadata.get("room", ""),
                    "equipment_id": device.metadata.get("equipment_id", ""),
                }
            )
