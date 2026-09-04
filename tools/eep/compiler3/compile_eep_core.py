"""Compiler 3.0 prototype for Registry v3 EEP JSON generation.

The compiler intentionally prefers source-derived information over implicit rules.
When information is missing, ambiguous, duplicated, or suspicious, the compiler
emits diagnostics instead of silently inventing semantics.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import enocean_mqtt.eep.generator.parser as parser_module
from enocean_mqtt.eep.generator.parser import load_eep_definition
from enocean_mqtt.eep.generator.semantic_mapping import (
    apply_semantic_shortcut_mapping,
    enrich_definition_tx_metadata,
)
from enocean_mqtt.eep.generator.validator import validate_eep_definition

Json = dict[str, Any]

DEFAULT_EEP_LIST = Path("eep/eep-list.csv")
DEFAULT_SEMANTIC_MAPPING = Path("eep/semantic-role-mapping.json")
DEFAULT_OUTPUT_DIR = Path("eep/registry-compiled")
VALID_DATA_TYPES = {"boolean", "integer", "float", "string", "enum"}
VALID_OBJECT_TYPES = {
    "measurement",
    "state",
    "setpoint",
    "command",
    "configuration",
    "diagnostic",
    "selector",
}

# Keep this list small. Entries are spelling repairs for known source typos,
# not semantic mappings. Every use is reported as a compiler warning.
NAME_OVERRIDES = {
    "cofiguration_mode": "configuration_mode",
    "communication_intervall": "communication_interval",
    "rf_communication_intervall": "rf_communication_interval",
    "tempertature_selection": "temperature_selection",
    "temperature_setpoinz": "temperature_setpoint",
    "set_point_selection": "setpoint_selection",
    "standbye": "standby",
    "stand_by_mode": "standby",
    "enter_standbye": "enter_standby",
}

OBJECT_TYPE_BY_LEGACY = {
    "measurement": "measurement",
    "state": "state",
    "status": "state",
    "setpoint": "setpoint",
    "command": "command",
    "command_parameter": "command",
    "configuration": "configuration",
    "diagnostic": "diagnostic",
    "metadata": "state",
    "event": "state",
}

TOP_LEVEL_ORDER = [
    "profile_type",
    "eep",
    "rorg",
    "func",
    "type",
    "func_description",
    "type_description",
    "description",
    "source",
    "source_version",
    "sources",
    "direction",
    "device_class",
    "function_groups",
    "channels",
    "messages",
    "telegrams",
    "dependencies",
    "tx",
    "metadata",
]
FUNCTION_GROUP_ORDER = ["name", "title", "direction", "description", "functions"]
SEMANTIC_OBJECT_ORDER = [
    "name",
    "display_name",
    "description",
    "source_key",
    "function_group",
    "message_id",
    "message_type",
    "command_id",
    "extended_command_id",
    "response_to",
    "response_timeout_ms",
    "semantic_role",
    "object_type",
    "semantic_confidence",
    "semantic_attributes",
    "data_type",
    "unit",
    "enum",
    "ranges",
    "default_value",
    "value_resolution",
    "value_precision",
    "runtime",
    "output",
    "tx",
]
TELEGRAM_ORDER = [
    "telegram_type_id",
    "telegram_id",
    "direction",
    "description",
    "fields",
    "status_fields",
    "channel_bindings",
    "message_bindings",
    "constraints",
    "context_updates",
    "dependencies",
]
FIELD_ORDER = [
    "name",
    "offset",
    "size",
    "shortcut",
    "description",
    "data_type",
    "signed",
    "raw_min",
    "raw_max",
    "source",
    "enum",
    "default_value",
    "reserved",
    "constant",
]
BINDING_ORDER = [
    "channel_ref",
    "message_ref",
    "field_ref",
    "scale",
    "enum",
    "ranges",
    "depends_on",
]
DEPENDENCY_ORDER = ["target", "depends_on", "reason"]


class CompileDiagnostics:
    """Collect console and machine-readable compiler diagnostics."""

    def __init__(self, eep: str) -> None:
        self.eep = eep
        self.items: list[Json] = []

    def warn(self, code: str, message: str, *, context: str | None = None) -> None:
        self._add("WARNING", code, message, context=context)

    def error(self, code: str, message: str, *, context: str | None = None) -> None:
        self._add("ERROR", code, message, context=context)

    def _add(self, level: str, code: str, message: str, *, context: str | None) -> None:
        item: Json = {"level": level, "code": code, "message": message}
        if context:
            item["context"] = context
        self.items.append(item)

    def lines(self) -> list[str]:
        result: list[str] = []
        for item in self.items:
            context = f" {item['context']}:" if item.get("context") else ""
            result.append(
                f"{item['level']} {self.eep} {item['code']}{context} "
                f"{item['message']}"
            )
        return result

    def to_json(self) -> Json:
        return {"eep": self.eep, "diagnostics": self.items}


def normalize_name(value: str, diagnostics: CompileDiagnostics | None = None) -> str:
    original = value.strip()
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", original)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")
    repaired = NAME_OVERRIDES.get(normalized, normalized)
    if diagnostics is not None and repaired != normalized:
        diagnostics.warn(
            "NAME_NORMALIZED",
            f"normalized source name '{original}' to '{repaired}'",
        )
    return repaired


def snake_case(value: str) -> str:
    return normalize_name(value)


def read_json(path: Path) -> Json:
    return cast(Json, json.loads(path.read_text(encoding="utf-8")))


def optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def normalize_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def read_text_with_fallback_encoding(
    path: Path,
    diagnostics: CompileDiagnostics,
) -> str:
    encodings = ("utf-8-sig", "utf-8", "cp1252")
    last_error: UnicodeDecodeError | None = None

    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

        if encoding != "utf-8":
            diagnostics.warn(
                "TEXT_ENCODING_FALLBACK",
                f"loaded {path} using {encoding} encoding",
            )
        return text

    if last_error is not None:
        raise last_error
    return path.read_text(encoding="utf-8")


def load_eep_list(
    path: Path,
    diagnostics: CompileDiagnostics,
) -> dict[str, dict[str, str]]:
    if not path.exists():
        diagnostics.warn("EEP_LIST_MISSING", f"EEP list does not exist: {path}")
        return {}
    content = read_text_with_fallback_encoding(path, diagnostics)
    with io.StringIO(content, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fieldnames = set(reader.fieldnames or [])
        required = {"eep", "direction", "device_class"}
        missing = sorted(required - fieldnames)
        for column in missing:
            diagnostics.warn(
                "EEP_LIST_COLUMN_MISSING",
                f"EEP list is missing column '{column}'",
            )
        if "eep" not in fieldnames:
            return {}
        result: dict[str, dict[str, str]] = {}
        for row in reader:
            eep = (row.get("eep") or "").strip().upper()
            if not eep:
                diagnostics.warn("EEP_LIST_EMPTY_EEP", "ignored row without EEP id")
                continue
            if eep in result:
                diagnostics.warn(
                    "EEP_LIST_DUPLICATE",
                    f"duplicate EEP list row for {eep}; first row kept",
                )
                continue
            result[eep] = row
        return result


def load_semantic_mapping(path: Path) -> dict[str, Json]:
    if not path.exists():
        return {}
    entries = read_json(path).get("entries", [])
    result: dict[str, Json] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key_name in ("function_key", "normalized_function", "source_key"):
            key = entry.get(key_name)
            if isinstance(key, str) and key.strip():
                result.setdefault(key.strip(), entry)
                result.setdefault(snake_case(key), entry)
    return result


def load_ip_functions(
    path: Path | None,
    diagnostics: CompileDiagnostics,
) -> tuple[list[Json], dict[str, Json]]:
    if path is None:
        diagnostics.warn("IP_JSON_NOT_PROVIDED", "no IP Representation JSON provided")
        return [], {}
    if not path.exists():
        diagnostics.warn("IP_JSON_MISSING", f"IP Representation JSON does not exist: {path}")
        return [], {}

    profile = read_json(path).get("profile", {})
    groups: list[Json] = []
    functions: dict[str, Json] = {}

    for raw_group in profile.get("functionGroups", []):
        if not isinstance(raw_group, dict):
            continue
        title = str(raw_group.get("title") or "").strip()
        direction = str(raw_group.get("direction") or "").strip()
        group_name = normalize_name(title or direction or "function_group", diagnostics)
        group_functions: list[str] = []
        for raw_function in raw_group.get("functions", []):
            if not isinstance(raw_function, dict):
                continue
            source_key = str(raw_function.get("key") or "").strip()
            if not source_key:
                diagnostics.warn(
                    "IP_FUNCTION_WITHOUT_KEY",
                    f"function in group '{group_name}' has no key",
                )
                continue
            name = normalize_name(source_key, diagnostics)
            group_functions.append(name)
            entry = {
                "name": name,
                "source_key": source_key,
                "description": optional_string(raw_function.get("description")),
                "function_group": group_name,
                "function_group_direction": direction,
                "values": raw_function.get("values", []),
                "default_value": normalize_scalar(raw_function.get("defaultValue")),
                "runtime": {
                    "transmit_on_connect": bool(raw_function.get("transmitOnConnect")),
                    "transmit_on_event": bool(raw_function.get("transmitOnEvent")),
                    "transmit_on_duplicate": bool(raw_function.get("transmitOnDuplicate")),
                },
            }
            for key in {name, source_key, snake_case(source_key)}:
                functions.setdefault(key, entry)
        groups.append(
            {
                "name": group_name,
                "title": title,
                "direction": direction,
                "functions": group_functions,
            }
        )
    return deduplicate_groups(groups, diagnostics), functions


def deduplicate_groups(groups: list[Json], diagnostics: CompileDiagnostics) -> list[Json]:
    merged: dict[str, Json] = {}
    order: list[str] = []
    for group in groups:
        name = str(group.get("name") or "")
        if not name:
            continue
        if name not in merged:
            merged[name] = dict(group)
            order.append(name)
            continue
        diagnostics.warn("DUPLICATE_FUNCTION_GROUP", f"merged duplicate group '{name}'")
        functions = merged[name].setdefault("functions", [])
        for function in group.get("functions", []):
            if function not in functions:
                functions.append(function)
    return [merged[name] for name in order]


def values_to_enum(values: list[Any]) -> list[Json]:
    result: list[Json] = []
    for item in values:
        if not isinstance(item, dict) or "value" not in item:
            continue
        raw_value = normalize_scalar(item.get("value"))
        meaning = optional_string(item.get("meaning"))
        label_source = (
            meaning
            if isinstance(raw_value, bool) and meaning
            else str(item.get("value"))
        )
        result.append(
            {
                "value": raw_value,
                "label": snake_case(label_source),
                "description": meaning,
            }
        )
    return result


def values_to_ranges(values: list[Any]) -> list[Json]:
    result: list[Json] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        raw_range = item.get("range")
        if not isinstance(raw_range, dict):
            continue
        result.append(
            {
                "min": raw_range.get("min"),
                "max": raw_range.get("max"),
                "step": raw_range.get("step"),
                "unit": raw_range.get("unit"),
                "description": optional_string(item.get("meaning")),
            }
        )
    return result


def data_type_from_ip(function: Json) -> str | None:
    values = function.get("values")
    if not isinstance(values, list):
        return None
    enum = values_to_enum(values)
    ranges = values_to_ranges(values)
    if enum:
        if all(isinstance(item.get("value"), bool) for item in enum):
            return "boolean" if function.get("function_group_direction") == "to" else "enum"
        return "enum"
    if ranges:
        if any(isinstance(item.get("step"), float) for item in ranges):
            return "float"
        return "integer"
    return None


def semantic_metadata(name: str, source_key: str | None, mapping: dict[str, Json]) -> Json:
    entry = mapping.get(source_key or "") or mapping.get(name)
    if entry is None:
        return {}
    metadata: Json = {}
    semantic_role = normalize_semantic_role(optional_string(entry.get("semantic_role")))
    object_type = object_type_from_mapping(entry)
    confidence = optional_string(entry.get("confidence"))
    attributes = entry.get("attributes")
    if semantic_role:
        metadata["semantic_role"] = semantic_role
    if object_type:
        metadata["object_type"] = object_type
    if confidence:
        metadata["semantic_confidence"] = confidence
    if isinstance(attributes, dict) and attributes:
        metadata["semantic_attributes"] = attributes
    return metadata


def normalize_semantic_role(role: str | None) -> str | None:
    if not role:
        return None
    if role == "device.tbd":
        return role
    parts = [snake_case(part) for part in role.split(".") if part.strip()]
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    if len(parts) == 1:
        return f"device.{parts[0]}"
    return None


def object_type_from_mapping(entry: Json) -> str | None:
    for key in ("object_type", "capability", "channel_type"):
        value = optional_string(entry.get(key))
        if value is None:
            continue
        normalized = OBJECT_TYPE_BY_LEGACY.get(snake_case(value), snake_case(value))
        if normalized in VALID_OBJECT_TYPES:
            return normalized
    return None


def enrich_object(item: Json, ip_functions: dict[str, Json], mapping: dict[str, Json]) -> Json:
    original_name = snake_case(str(item.get("name") or ""))
    source_key = item.get("source_key") if isinstance(item.get("source_key"), str) else None
    function = ip_functions.get(source_key or "") or ip_functions.get(original_name)
    enriched = strip_legacy_semantic_fields(dict(item))
    enriched["name"] = original_name
    if function is not None:
        enriched["name"] = function["name"]
        enriched["source_key"] = function["source_key"]
        enriched["description"] = function.get("description") or enriched.get("description")
        enriched["function_group"] = function["function_group"]
        enriched["runtime"] = function["runtime"]
        if function.get("default_value") is not None:
            enriched["default_value"] = function["default_value"]
        apply_ip_values(enriched, function)
    enriched.update(
        semantic_metadata(
            str(enriched.get("name") or ""),
            str(enriched.get("source_key") or ""),
            mapping,
        )
    )
    normalize_registry_object(enriched)
    return enriched


def strip_legacy_semantic_fields(item: Json) -> Json:
    legacy_type = item.pop("channel_type", None)
    legacy_capability = item.pop("capability", None)
    item.pop("channel_class", None)
    if "object_type" not in item:
        for candidate in (legacy_capability, legacy_type):
            if isinstance(candidate, str):
                object_type = OBJECT_TYPE_BY_LEGACY.get(snake_case(candidate))
                if object_type:
                    item["object_type"] = object_type
                    break
    return item


def apply_ip_values(target: Json, function: Json) -> None:
    enum = values_to_enum(function.get("values", []))
    ranges = values_to_ranges(function.get("values", []))
    inferred_type = data_type_from_ip(function)
    if enum:
        if inferred_type == "boolean":
            target["data_type"] = "boolean"
            target.pop("enum", None)
        else:
            target["data_type"] = "enum"
            target["enum"] = enum
    if ranges:
        target["ranges"] = ranges
        first_unit = next((item.get("unit") for item in ranges if item.get("unit")), None)
        if first_unit:
            target["unit"] = first_unit
        if inferred_type in VALID_DATA_TYPES:
            target["data_type"] = inferred_type


def normalize_registry_object(item: Json) -> None:
    if item.get("name"):
        item["name"] = snake_case(str(item["name"]))
    item.setdefault("display_name", None)
    role = normalize_semantic_role(optional_string(item.get("semantic_role")))
    if role:
        item["semantic_role"] = role
    object_type = optional_string(item.get("object_type"))
    if object_type:
        object_type = OBJECT_TYPE_BY_LEGACY.get(snake_case(object_type), snake_case(object_type))
    if not object_type or object_type not in VALID_OBJECT_TYPES:
        object_type = infer_object_type(item)
    item["object_type"] = object_type
    if item.get("data_type") == "int":
        item["data_type"] = "integer"
    if item.get("data_type") == "bool":
        item["data_type"] = "boolean"
    if item.get("data_type") not in VALID_DATA_TYPES:
        item["data_type"] = "integer"
    item.pop("channel_class", None)
    item.pop("channel_type", None)
    item.pop("capability", None)


def infer_object_type(item: Json) -> str:
    if item.get("ranges") or item.get("scale"):
        return "measurement"
    return "state"


def skeleton_from_ip_function(function: Json, mapping: dict[str, Json], is_message: bool) -> Json:
    item: Json = {
        "name": function["name"],
        "display_name": None,
        "source_key": function["source_key"],
        "description": function.get("description"),
        "function_group": function["function_group"],
        "runtime": function["runtime"],
        "data_type": data_type_from_ip(function) or "integer",
        "output": {"mqtt": True, "api": True, "storage": True},
    }
    if function.get("default_value") is not None:
        item["default_value"] = function["default_value"]
    apply_ip_values(item, function)
    if is_message:
        item["tx"] = tx_metadata_from_sources(item)
    return enrich_object(item, {function["name"]: function}, mapping)


def tx_metadata_from_sources(item: Json) -> Json | None:
    probe_channel = dict(item)
    if "channel_type" not in probe_channel:
        probe_channel["channel_type"] = object_type_to_legacy_channel_type(item)
    probe = {"channels": [probe_channel]}
    enrich_definition_tx_metadata(probe)
    channels = probe.get("channels")
    if isinstance(channels, list) and channels and isinstance(channels[0], dict):
        tx = channels[0].get("tx")
        if isinstance(tx, dict):
            return tx
    if item.get("default_value") is not None:
        return {
            "managed": True,
            "default_value": normalize_tx_default(item["default_value"]),
            "required_for_snapshot": False,
        }
    return {"managed": False, "required_for_snapshot": True}


def object_type_to_legacy_channel_type(item: Json) -> str:
    object_type = str(item.get("object_type") or "")
    if object_type in {"measurement", "state", "configuration", "diagnostic"}:
        return object_type
    if object_type == "setpoint":
        return "measurement"
    return "state"


def normalize_tx_default(value: Any) -> Any:
    if isinstance(value, str):
        return snake_case(value)
    return value


def merge_ip_layer(
    definition: Json,
    ip_groups: list[Json],
    ip_functions: dict[str, Json],
    mapping: dict[str, Json],
) -> None:
    definition["function_groups"] = ip_groups
    for collection_name in ("channels", "messages"):
        collection = definition.get(collection_name)
        if isinstance(collection, list):
            definition[collection_name] = enrich_collection(collection, ip_functions, mapping)
    add_missing_ip_objects(definition, ip_functions, mapping)


def enrich_collection(
    collection: list[Any],
    ip_functions: dict[str, Json],
    mapping: dict[str, Json],
) -> list[Any]:
    result: list[Any] = []
    for item in collection:
        result.append(
            enrich_object(item, ip_functions, mapping)
            if isinstance(item, dict)
            else item
        )
    return result


def add_missing_ip_objects(
    definition: Json,
    ip_functions: dict[str, Json],
    mapping: dict[str, Json],
) -> None:
    existing_channels = names_in_collection(definition.get("channels"))
    existing_messages = names_in_collection(definition.get("messages"))
    for function in unique_ip_functions(ip_functions):
        name = str(function["name"])
        direction = function.get("function_group_direction")
        if direction == "from" and name not in existing_channels:
            definition.setdefault("channels", []).append(
                skeleton_from_ip_function(function, mapping, False)
            )
            existing_channels.add(name)
        elif direction == "to" and name not in existing_messages:
            definition.setdefault("messages", []).append(
                skeleton_from_ip_function(function, mapping, True)
            )
            existing_messages.add(name)


def names_in_collection(collection: Any) -> set[str]:
    if not isinstance(collection, list):
        return set()
    return {
        str(item.get("name"))
        for item in collection
        if isinstance(item, dict) and item.get("name")
    }


def unique_ip_functions(ip_functions: dict[str, Json]) -> list[Json]:
    result: list[Json] = []
    seen: set[str] = set()
    for function in ip_functions.values():
        name = str(function["name"])
        if name in seen:
            continue
        seen.add(name)
        result.append(function)
    return result


def apply_eep_list_metadata(
    definition: Json,
    eep_list: dict[str, dict[str, str]],
    diagnostics: CompileDiagnostics,
) -> None:
    eep = str(definition.get("eep", "")).upper()
    row = eep_list.get(eep)
    if row is None:
        diagnostics.warn("EEP_LIST_ENTRY_MISSING", f"no eep-list row for {eep}")
        return
    direction = (row.get("direction") or "").strip()
    device_class = (row.get("device_class") or "").strip()
    if direction:
        definition["direction"] = direction
    else:
        diagnostics.warn("EEP_DIRECTION_MISSING", "eep-list row has no direction")
    if device_class:
        definition["device_class"] = device_class
    else:
        diagnostics.warn("EEP_DEVICE_CLASS_MISSING", "eep-list row has no device_class")


def apply_sources(
    definition: Json,
    xml_path: Path,
    ip_json_path: Path | None,
    semantic_mapping_path: Path,
    eep_list_path: Path,
) -> None:
    sources: dict[str, list[str]] = {
        "xml": [str(xml_path)],
        "semantic_mapping": [str(semantic_mapping_path)],
        "eep_list": [str(eep_list_path)],
    }
    if ip_json_path is not None and ip_json_path.exists():
        sources["json"] = [str(ip_json_path)]
    definition["sources"] = sources
    if xml_path.name != "eep268.xml":
        definition.pop("source_version", None)
        definition["source"] = "EnOcean Equipment Profiles / IP Representation"


def migrate_telegrams(definition: Json) -> None:
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        migrate_embedded_messages(telegram)
        normalize_telegram_references(telegram)
        telegram.pop("metadata_channels", None)
    definition.pop("metadata_channels", None)


def migrate_embedded_messages(telegram: Json) -> None:
    if "messages" not in telegram or "message_bindings" in telegram:
        telegram.pop("messages", None)
        return
    message_bindings: list[Json] = []
    for message in telegram.get("messages", []):
        if not isinstance(message, dict):
            continue
        for binding in message.get("channel_bindings", []):
            if not isinstance(binding, dict):
                continue
            migrated = dict(binding)
            migrated["message_ref"] = snake_case(
                str(migrated.pop("channel_ref", message.get("name")))
            )
            message_bindings.append(migrated)
    if message_bindings:
        telegram["message_bindings"] = message_bindings
    telegram.pop("messages", None)


def normalize_telegram_references(telegram: Json) -> None:
    for key in ("fields", "status_fields"):
        for field in telegram.get(key, []):
            if isinstance(field, dict):
                normalize_field(field)
    for binding_key in ("channel_bindings", "message_bindings"):
        for binding in iter_bindings(telegram.get(binding_key)):
            normalize_binding(binding)


def normalize_field(field: Json) -> None:
    if field.get("name"):
        field["name"] = snake_case(str(field["name"]))
    if field.get("data_type") == "int":
        field["data_type"] = "integer"
    if field.get("data_type") == "bool":
        field["data_type"] = "boolean"


def normalize_binding(binding: Json) -> None:
    if "bitfield_ref" in binding and "field_ref" not in binding:
        binding["field_ref"] = binding["bitfield_ref"]
    binding.pop("bitfield_ref", None)
    if binding.get("channel_ref"):
        binding["channel_ref"] = snake_case(str(binding["channel_ref"]))
    if binding.get("message_ref"):
        binding["message_ref"] = snake_case(str(binding["message_ref"]))
    if binding.get("field_ref"):
        binding["field_ref"] = snake_case(str(binding["field_ref"]))
    normalize_dependency(binding.get("depends_on"))
    normalize_ranges(binding.get("ranges"))


def normalize_ranges(ranges: Any) -> None:
    if not isinstance(ranges, list):
        return
    for range_item in ranges:
        if isinstance(range_item, dict):
            if range_item.get("label"):
                range_item["label"] = snake_case(str(range_item["label"]))
            normalize_dependency(range_item.get("depends_on"))


def normalize_dependency(depends_on: Any) -> None:
    if not isinstance(depends_on, dict):
        return
    depends_on.pop("source", None)
    if depends_on.get("field"):
        depends_on["field"] = snake_case(str(depends_on["field"]))
    for key in ("all", "any"):
        conditions = depends_on.get(key)
        if isinstance(conditions, list):
            for condition in conditions:
                normalize_dependency(condition)


def post_process_registry(definition: Json, diagnostics: CompileDiagnostics) -> None:
    remove_legacy_tx_messages(definition, diagnostics)
    expand_dependency_bindings(definition)
    ensure_channels_for_rx_bindings(definition)
    ensure_messages_for_tx_bindings(definition)
    remove_tx_only_channels(definition, diagnostics)
    derive_selectors_from_dependencies(definition)
    add_dependencies_from_bindings(definition)
    normalize_all_semantic_objects(definition)
    deduplicate_top_level_named_items(definition, diagnostics)
    apply_tx_metadata_from_sources(definition)
    add_profile_tx_metadata(definition)
    strip_legacy_registry_fields(definition)
    collect_registry_diagnostics(definition, diagnostics)


def remove_legacy_tx_messages(definition: Json, diagnostics: CompileDiagnostics) -> None:
    messages = definition.get("messages")
    if not isinstance(messages, list):
        return
    kept: list[Any] = []
    for message in messages:
        if isinstance(message, dict) and str(message.get("name", "")).startswith("tx_"):
            diagnostics.warn(
                "LEGACY_TX_MESSAGE_REMOVED",
                f"removed legacy message '{message.get('name')}'",
            )
            continue
        kept.append(message)
    definition["messages"] = kept


def expand_dependency_bindings(definition: Json) -> None:
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        if telegram.get("direction") == "rx":
            expand_binding_collection(telegram, "channel_bindings", "channel_ref")
        elif telegram.get("direction") == "tx":
            expand_binding_collection(telegram, "message_bindings", "message_ref")


def expand_binding_collection(telegram: Json, key: str, ref_key: str) -> None:
    bindings = telegram.get(key)
    if not isinstance(bindings, list):
        return
    expanded: list[Json] = []
    for binding in bindings:
        if isinstance(binding, dict):
            expanded.extend(expand_binding(binding, ref_key))
    telegram[key] = deduplicate_bindings(expanded, ref_key)


def expand_binding(binding: Json, ref_key: str) -> list[Json]:
    ranges = binding.get("ranges")
    if not isinstance(ranges, list) or not any(range_has_dependency(item) for item in ranges):
        return [binding]
    result: list[Json] = []
    for range_item in ranges:
        if isinstance(range_item, dict) and range_has_dependency(range_item):
            result.append(
                binding_from_range(
                    binding,
                    range_item,
                    ref_key,
                    cast(Json, range_item["depends_on"]),
                )
            )
    return result or [binding]


def range_has_dependency(range_item: Any) -> bool:
    return isinstance(range_item, dict) and isinstance(range_item.get("depends_on"), dict)


def binding_from_range(binding: Json, range_item: Json, ref_key: str, dependency: Json) -> Json:
    result = dict(binding)
    label = snake_case(str(range_item.get("label") or ""))
    if label:
        result[ref_key] = label
    result["depends_on"] = dict(dependency)
    result.pop("ranges", None)
    if isinstance(range_item.get("scale"), dict):
        result["scale"] = range_item["scale"]
    normalize_binding(result)
    return result


def deduplicate_bindings(bindings: list[Json], ref_key: str) -> list[Json]:
    result: list[Json] = []
    seen: set[tuple[str, str, str]] = set()
    for binding in bindings:
        dependency = binding.get("depends_on")
        dependency_key = json.dumps(dependency, sort_keys=True) if dependency else ""
        identity = (
            str(binding.get(ref_key) or ""),
            str(binding.get("field_ref") or ""),
            dependency_key,
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(binding)
    return result


def ensure_channels_for_rx_bindings(definition: Json) -> None:
    channels = definition.setdefault("channels", [])
    if not isinstance(channels, list):
        return
    existing = names_in_collection(channels)
    for binding in iter_rx_channel_bindings(definition):
        channel_ref = binding.get("channel_ref")
        if isinstance(channel_ref, str) and channel_ref not in existing:
            channels.append(synthetic_object_from_binding(channel_ref, binding, is_message=False))
            existing.add(channel_ref)


def ensure_messages_for_tx_bindings(definition: Json) -> None:
    messages = definition.setdefault("messages", [])
    if not isinstance(messages, list):
        return
    existing = names_in_collection(messages)
    for binding in iter_tx_message_bindings(definition):
        message_ref = binding.get("message_ref")
        if isinstance(message_ref, str) and message_ref not in existing:
            messages.append(synthetic_object_from_binding(message_ref, binding, is_message=True))
            existing.add(message_ref)


def synthetic_object_from_binding(name: str, binding: Json, *, is_message: bool) -> Json:
    item: Json = {
        "name": name,
        "display_name": None,
        "object_type": (
            "command"
            if is_message
            else "measurement"
            if binding.get("scale")
            else "state"
        ),
        "data_type": infer_data_type_from_binding(binding),
        "output": {"mqtt": True, "api": True, "storage": True},
    }
    if binding.get("enum"):
        item["enum"] = binding["enum"]
    if binding.get("ranges"):
        item["ranges"] = binding["ranges"]
    if is_message:
        item["tx"] = tx_metadata_from_sources(item)
    normalize_registry_object(item)
    return item


def infer_data_type_from_binding(binding: Json) -> str:
    if binding.get("enum"):
        return "enum"
    if binding.get("scale") or binding.get("ranges"):
        return "float"
    return "integer"


def iter_rx_channel_bindings(definition: Json) -> Iterator[Json]:
    for telegram in definition.get("telegrams", []):
        if isinstance(telegram, dict) and telegram.get("direction") == "rx":
            yield from iter_bindings(telegram.get("channel_bindings"))


def iter_tx_message_bindings(definition: Json) -> Iterator[Json]:
    for telegram in definition.get("telegrams", []):
        if isinstance(telegram, dict) and telegram.get("direction") == "tx":
            yield from iter_bindings(telegram.get("message_bindings"))


def iter_bindings(bindings: Any) -> Iterator[Json]:
    if not isinstance(bindings, list):
        return
    for binding in bindings:
        if isinstance(binding, dict):
            yield binding


def remove_tx_only_channels(definition: Json, diagnostics: CompileDiagnostics) -> None:
    channels = definition.get("channels")
    if not isinstance(channels, list):
        return
    rx_refs = {str(binding.get("channel_ref")) for binding in iter_rx_channel_bindings(definition)}
    tx_refs = {str(binding.get("message_ref")) for binding in iter_tx_message_bindings(definition)}
    kept: list[Any] = []
    for item in channels:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        name = str(item.get("name"))
        if name not in rx_refs and name in tx_refs:
            diagnostics.warn("TX_ONLY_CHANNEL_REMOVED", f"removed channel '{name}'")
            continue
        kept.append(item)
    definition["channels"] = kept


def derive_selectors_from_dependencies(definition: Json) -> None:
    selector_fields = dependency_field_names(definition)
    if not selector_fields:
        return
    for collection_name in ("channels", "messages"):
        collection = definition.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict) or item.get("name") not in selector_fields:
                continue
            item["object_type"] = "selector"
            if not item.get("semantic_role") or item.get("semantic_role") == "device.tbd":
                item["semantic_role"] = "enocean.selector"


def dependency_field_names(definition: Json) -> set[str]:
    result: set[str] = set()
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        for binding_key in ("channel_bindings", "message_bindings"):
            for binding in iter_bindings(telegram.get(binding_key)):
                collect_dependency_fields(binding.get("depends_on"), result)
    return result


def collect_dependency_fields(depends_on: Any, result: set[str]) -> None:
    if not isinstance(depends_on, dict):
        return
    field = depends_on.get("field")
    if isinstance(field, str):
        result.add(field)
    for key in ("all", "any"):
        conditions = depends_on.get(key)
        if isinstance(conditions, list):
            for condition in conditions:
                collect_dependency_fields(condition, result)


def add_dependencies_from_bindings(definition: Json) -> None:
    dependencies = definition.setdefault("dependencies", [])
    if not isinstance(dependencies, list):
        return
    seen = dependency_keys(dependencies)
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        for binding_key, ref_key in (
            ("channel_bindings", "channel_ref"),
            ("message_bindings", "message_ref"),
        ):
            for binding in iter_bindings(telegram.get(binding_key)):
                if not isinstance(binding.get("depends_on"), dict):
                    continue
                target = binding.get(ref_key)
                dependency = binding.get("depends_on")
                key = json.dumps({"target": target, "depends_on": dependency}, sort_keys=True)
                if key in seen:
                    continue
                dependencies.append(
                    {
                        "target": target,
                        "depends_on": dependency,
                        "reason": "Generated from binding dependency",
                    }
                )
                seen.add(key)


def dependency_keys(dependencies: list[Any]) -> set[str]:
    result: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        result.add(
            json.dumps(
                {
                    "target": dependency.get("target"),
                    "depends_on": dependency.get("depends_on"),
                },
                sort_keys=True,
            )
        )
    return result


def normalize_all_semantic_objects(definition: Json) -> None:
    for key in ("channels", "messages"):
        collection = definition.get(key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if isinstance(item, dict):
                normalize_registry_object(item)


def deduplicate_top_level_named_items(definition: Json, diagnostics: CompileDiagnostics) -> None:
    for key in ("channels", "messages"):
        collection = definition.get(key)
        if isinstance(collection, list):
            definition[key] = deduplicate_named_items(collection, key, diagnostics)


def deduplicate_named_items(
    items: list[Any],
    collection_name: str,
    diagnostics: CompileDiagnostics,
) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            result.append(item)
            continue
        name = item.get("name")
        if isinstance(name, str) and name in seen:
            diagnostics.warn(
                "DUPLICATE_OBJECT",
                f"removed duplicate {collection_name} object '{name}'",
            )
            continue
        if isinstance(name, str):
            seen.add(name)
        result.append(item)
    return result


def apply_tx_metadata_from_sources(definition: Json) -> None:
    legacy_projection = {
        "channels": [
            dict(item)
            for item in definition.get("channels", [])
            if isinstance(item, dict)
        ]
    }
    for item in legacy_projection["channels"]:
        item.setdefault("channel_type", object_type_to_legacy_channel_type(item))
    enrich_definition_tx_metadata(legacy_projection)
    tx_by_name = {
        item.get("name"): item.get("tx")
        for item in legacy_projection.get("channels", [])
        if isinstance(item, dict) and isinstance(item.get("tx"), dict)
    }
    for collection_name in ("channels", "messages"):
        collection = definition.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name in tx_by_name and "tx" not in item:
                item["tx"] = tx_by_name[name]
            if collection_name == "messages" and "tx" not in item:
                item["tx"] = tx_metadata_from_sources(item)


def add_profile_tx_metadata(definition: Json) -> None:
    if any_tx_metadata(definition):
        definition.setdefault("tx", {})["aggregation_window_seconds"] = 10


def any_tx_metadata(definition: Json) -> bool:
    for key in ("channels", "messages"):
        for item in definition.get(key, []):
            if isinstance(item, dict) and isinstance(item.get("tx"), dict):
                return True
    return False


def strip_legacy_registry_fields(definition: Json) -> None:
    definition.pop("metadata_channels", None)
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        telegram.pop("metadata_channels", None)
        telegram.pop("depends_on", None)
        for binding in list(iter_bindings(telegram.get("channel_bindings"))) + list(
            iter_bindings(telegram.get("message_bindings"))
        ):
            normalize_binding(binding)
    for key in ("channels", "messages"):
        for item in definition.get(key, []):
            if isinstance(item, dict):
                strip_legacy_semantic_fields(item)


def collect_registry_diagnostics(definition: Json, diagnostics: CompileDiagnostics) -> None:
    if not definition.get("direction"):
        diagnostics.warn("ROOT_DIRECTION_MISSING", "root direction is missing")
    if not definition.get("device_class"):
        diagnostics.warn("ROOT_DEVICE_CLASS_MISSING", "root device_class is missing")
    warn_object_gaps(definition, diagnostics)
    warn_binding_integrity(definition, diagnostics)
    warn_field_overlaps(definition, diagnostics)
    warn_semantic_duplicates(definition, diagnostics)


def warn_object_gaps(definition: Json, diagnostics: CompileDiagnostics) -> None:
    for collection_name in ("channels", "messages"):
        collection = definition.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "<unnamed>")
            if item.get("semantic_role") in {None, "device.tbd"}:
                diagnostics.warn(
                    "SEMANTIC_ROLE_MISSING",
                    f"{collection_name} object '{name}' has no semantic role",
                )
            if item.get("object_type") not in VALID_OBJECT_TYPES:
                diagnostics.warn(
                    "OBJECT_TYPE_INVALID",
                    f"{collection_name} object '{name}' has invalid object_type",
                )


def warn_binding_integrity(definition: Json, diagnostics: CompileDiagnostics) -> None:
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        telegram_id = str(telegram.get("telegram_type_id") or "<unknown>")
        fields = field_names(telegram)
        channel_refs = names_in_collection(definition.get("channels"))
        message_refs = names_in_collection(definition.get("messages"))
        for binding in iter_bindings(telegram.get("channel_bindings")):
            warn_binding(binding, fields, channel_refs, "channel_ref", telegram_id, diagnostics)
        for binding in iter_bindings(telegram.get("message_bindings")):
            warn_binding(binding, fields, message_refs, "message_ref", telegram_id, diagnostics)


def warn_binding(
    binding: Json,
    fields: set[str],
    refs: set[str],
    ref_key: str,
    telegram_id: str,
    diagnostics: CompileDiagnostics,
) -> None:
    field_ref = binding.get("field_ref")
    object_ref = binding.get(ref_key)
    if isinstance(field_ref, str) and field_ref not in fields:
        diagnostics.warn(
            "BINDING_FIELD_MISSING",
            f"binding references missing field '{field_ref}'",
            context=telegram_id,
        )
    if isinstance(object_ref, str) and object_ref not in refs:
        diagnostics.warn(
            "BINDING_OBJECT_MISSING",
            f"binding references missing object '{object_ref}'",
            context=telegram_id,
        )
    depends_on = binding.get("depends_on")
    if isinstance(depends_on, dict):
        dep_field = depends_on.get("field")
        if isinstance(dep_field, str) and dep_field not in fields:
            diagnostics.warn(
                "DEPENDENCY_FIELD_MISSING",
                f"dependency references missing field '{dep_field}'",
                context=telegram_id,
            )


def field_names(telegram: Json) -> set[str]:
    result: set[str] = set()
    for key in ("fields", "status_fields"):
        for field in telegram.get(key, []):
            if isinstance(field, dict) and field.get("name"):
                result.add(str(field["name"]))
    return result


def warn_field_overlaps(definition: Json, diagnostics: CompileDiagnostics) -> None:
    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        telegram_id = str(telegram.get("telegram_type_id") or "<unknown>")
        ranges: list[tuple[int, int, str]] = []
        for field in telegram.get("fields", []):
            if not isinstance(field, dict):
                continue
            offset = field.get("offset")
            size = field.get("size")
            name = field.get("name")
            if not isinstance(offset, int) or not isinstance(size, int) or not name:
                continue
            ranges.append((offset, offset + size - 1, str(name)))
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:], strict=False):
            if current[0] <= previous[1]:
                diagnostics.warn(
                    "FIELD_OVERLAP",
                    f"field '{previous[2]}' overlaps '{current[2]}'",
                    context=telegram_id,
                )


def warn_semantic_duplicates(definition: Json, diagnostics: CompileDiagnostics) -> None:
    for collection_name in ("channels", "messages"):
        collection = definition.get(collection_name)
        if not isinstance(collection, list):
            continue
        seen: dict[tuple[str, str], str] = {}
        for item in collection:
            if not isinstance(item, dict):
                continue
            role = item.get("semantic_role")
            object_type = item.get("object_type")
            name = str(item.get("name") or "")
            if not isinstance(role, str) or not isinstance(object_type, str):
                continue
            key = (role, object_type)
            if key in seen:
                diagnostics.warn(
                    "POSSIBLE_SEMANTIC_DUPLICATE",
                    f"{collection_name} objects '{seen[key]}' and '{name}' share {key}",
                )
            else:
                seen[key] = name


def compile_eep(
    xml_path: Path,
    eep_id: str,
    output_dir: Path,
    ip_json_path: Path | None,
    semantic_mapping_path: Path,
    eep_list_path: Path,
) -> tuple[Path, list[str]]:
    diagnostics = CompileDiagnostics(eep_id.upper())
    apply_semantic_shortcut_mapping(parser_module)
    definition = load_eep_definition(xml_path, eep_id)
    enrich_definition_tx_metadata(definition)
    ip_groups, ip_functions = load_ip_functions(ip_json_path, diagnostics)
    semantic_mapping = load_semantic_mapping(semantic_mapping_path)
    eep_list = load_eep_list(eep_list_path, diagnostics)
    apply_eep_list_metadata(definition, eep_list, diagnostics)
    apply_sources(definition, xml_path, ip_json_path, semantic_mapping_path, eep_list_path)
    merge_ip_layer(definition, ip_groups, ip_functions, semantic_mapping)
    migrate_telegrams(definition)
    post_process_registry(definition, diagnostics)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{definition['eep']}.json"
    output_file.write_text(
        json.dumps(ordered_dict(definition, TOP_LEVEL_ORDER), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return output_file, [*validate_eep_definition(definition), *diagnostics.lines()]


def ordered_dict(data: Json, order: list[str]) -> Json:
    result: Json = {}
    for key in order:
        if key in data and keep_value(data[key], key):
            result[key] = ordered_value(key, data[key])
    for key in sorted(data):
        if key not in result and keep_value(data[key], key):
            result[key] = ordered_value(key, data[key])
    return result


def ordered_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        if {"offset", "size"}.issubset(value.keys()):
            return ordered_dict(value, FIELD_ORDER)
        if {"target", "depends_on"}.issubset(value.keys()):
            return ordered_dict(value, DEPENDENCY_ORDER)
        return {
            item_key: ordered_value(item_key, item_value)
            for item_key, item_value in value.items()
            if keep_value(item_value, item_key)
        }
    if isinstance(value, list):
        order = order_for_list_key(key)
        return [ordered_list_item(item, order) for item in value if keep_value(item, key)]
    return value


def ordered_list_item(item: Any, order: list[str] | None) -> Any:
    if isinstance(item, dict) and order:
        return ordered_dict(item, order)
    return item


def order_for_list_key(key: str) -> list[str] | None:
    if key in {"channels", "messages"}:
        return SEMANTIC_OBJECT_ORDER
    if key == "function_groups":
        return FUNCTION_GROUP_ORDER
    if key == "telegrams":
        return TELEGRAM_ORDER
    if key in {"fields", "status_fields"}:
        return FIELD_ORDER
    if key in {"channel_bindings", "message_bindings"}:
        return BINDING_ORDER
    if key == "dependencies":
        return DEPENDENCY_ORDER
    return None


def keep_value(value: Any, key: str) -> bool:
    if key == "display_name" and value is None:
        return True
    return value not in (None, [], {})


def write_report(report_file: Path, eep_id: str, issues: list[str]) -> None:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"eep": eep_id.upper(), "issues": issues}
    report_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    cli = argparse.ArgumentParser(description="Compile one EEP into Registry v3 JSON")
    cli.add_argument("--xml", required=True, type=Path, help="EEP XML source")
    cli.add_argument("--eep", required=True, help="EEP ID, e.g. A5-20-06")
    cli.add_argument("--ip-json", type=Path, help="Optional IP Representation JSON source")
    cli.add_argument(
        "--semantic-mapping",
        type=Path,
        default=DEFAULT_SEMANTIC_MAPPING,
        help="semantic-role-mapping.json",
    )
    cli.add_argument(
        "--eep-list",
        type=Path,
        default=DEFAULT_EEP_LIST,
        help="EEP list CSV with direction/device_class metadata",
    )
    cli.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for generated Registry v3 JSON",
    )
    cli.add_argument(
        "--report-file",
        type=Path,
        help="Optional JSON report file for compiler diagnostics",
    )
    args = cli.parse_args()
    output_file, issues = compile_eep(
        args.xml,
        args.eep,
        args.output_dir,
        args.ip_json,
        args.semantic_mapping,
        args.eep_list,
    )
    print(f"OK {args.eep} -> {output_file}")
    for issue in issues:
        print(f"   {issue}")
    if args.report_file is not None:
        write_report(args.report_file, args.eep, issues)


if __name__ == "__main__":
    main()
