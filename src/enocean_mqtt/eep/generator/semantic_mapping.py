"""Semantic shortcut mapping support for the EEP compiler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MAPPING_PATH = Path("eep/mappings/semantic-shortcut-mapping.json")
DEFAULT_AGGREGATION_WINDOW_SECONDS = 10
_BOOLEAN_ENUM_LABELS = (
    frozenset({"false", "true"}),
    frozenset({"no", "yes"}),
)


class SemanticMappingError(RuntimeError):
    """Raised when the semantic shortcut mapping cannot be loaded."""


def load_semantic_shortcut_mapping(
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load semantic name and role maps from JSON mapping file."""

    path = Path(mapping_path)

    if not path.exists():
        raise SemanticMappingError(
            f"Semantic shortcut mapping not found: {path}"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SemanticMappingError(
            f"Invalid semantic shortcut mapping JSON: {path}"
        ) from exc

    shortcuts = payload.get("shortcuts")

    if not isinstance(shortcuts, dict):
        raise SemanticMappingError(
            "Semantic shortcut mapping must contain a 'shortcuts' object"
        )

    semantic_name_map: dict[str, str] = {}
    semantic_role_map: dict[str, str] = {}

    for shortcut, raw_entry in shortcuts.items():
        if not isinstance(shortcut, str) or not isinstance(raw_entry, dict):
            continue

        key = shortcut.strip().lower()

        semantic_name = _optional_string(raw_entry.get("semantic_name"))
        semantic_role = _optional_string(raw_entry.get("semantic_role"))

        if semantic_name is not None:
            semantic_name_map[key] = semantic_name

            if semantic_role is not None:
                semantic_role_map[semantic_name] = semantic_role

    return semantic_name_map, semantic_role_map


def apply_semantic_shortcut_mapping(
    parser_module: Any,
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
) -> None:
    """Apply declarative semantic shortcut mapping to parser module."""

    semantic_name_map, semantic_role_map = load_semantic_shortcut_mapping(
        mapping_path
    )

    parser_module.SEMANTIC_NAME_MAP = semantic_name_map
    parser_module.SEMANTIC_ROLE_MAP = semantic_role_map


def enrich_definition_tx_metadata(definition: dict[str, Any]) -> dict[str, Any]:
    """Add declarative TX metadata and normalize boolean bindings."""

    normalize_boolean_bindings(definition)
    channels = definition.get("channels")

    if not isinstance(channels, list):
        return definition

    has_tx_relevant_channel = False

    for channel in channels:
        if not isinstance(channel, dict):
            continue

        tx_metadata = _channel_tx_metadata(channel)

        if tx_metadata is None:
            continue

        channel["tx"] = tx_metadata
        has_tx_relevant_channel = True

    if has_tx_relevant_channel:
        definition.setdefault("tx", {})["aggregation_window_seconds"] = (
            DEFAULT_AGGREGATION_WINDOW_SECONDS
        )

    return definition


def normalize_boolean_bindings(definition: dict[str, Any]) -> dict[str, Any]:
    """Remove enum maps from all canonical boolean Registry bindings.

    Boolean semantic objects are encoded directly as ``False -> 0`` and
    ``True -> 1``. Canonical two-value binding enums using ``no/yes`` or
    ``false/true`` are therefore sufficient to identify a boolean binding even
    before later compiler stages have completed semantic-object enrichment.
    """

    semantic_objects = {
        name: semantic_object
        for semantic_object in _iter_semantic_objects(definition)
        if isinstance((name := semantic_object.get("name")), str) and name
    }
    boolean_refs: set[str] = set()

    for name, semantic_object in semantic_objects.items():
        if semantic_object.get("data_type") == "boolean" or _is_boolean_enum(
            semantic_object.get("enum")
        ):
            semantic_object["data_type"] = "boolean"
            semantic_object.pop("enum", None)
            boolean_refs.add(name)

    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue

        for binding_key, ref_key in (
            ("channel_bindings", "channel_ref"),
            ("message_bindings", "message_ref"),
        ):
            bindings = telegram.get(binding_key)
            if not isinstance(bindings, list):
                continue

            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                object_ref = binding.get(ref_key)
                binding_is_boolean = _is_boolean_enum(binding.get("enum"))
                if object_ref in boolean_refs or binding_is_boolean:
                    binding.pop("enum", None)
                if binding_is_boolean and isinstance(object_ref, str):
                    boolean_refs.add(object_ref)
                    semantic_object = semantic_objects.get(object_ref)
                    if semantic_object is not None:
                        semantic_object["data_type"] = "boolean"
                        semantic_object.pop("enum", None)

    return definition


def _iter_semantic_objects(definition: dict[str, Any]):
    for collection_name in ("channels", "messages"):
        collection = definition.get(collection_name)
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict):
                    yield item

    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        for collection_name in ("channels", "metadata_channels"):
            collection = telegram.get(collection_name)
            if isinstance(collection, list):
                for item in collection:
                    if isinstance(item, dict):
                        yield item
        for message in telegram.get("messages", []):
            if not isinstance(message, dict):
                continue
            yield message
            channels = message.get("channels")
            if isinstance(channels, list):
                for item in channels:
                    if isinstance(item, dict):
                        yield item


def _is_boolean_enum(enum_items: Any) -> bool:
    if not isinstance(enum_items, list) or len(enum_items) != 2:
        return False

    values: set[int] = set()
    labels: set[str] = set()

    for item in enum_items:
        if not isinstance(item, dict):
            return False
        value = item.get("value")
        if isinstance(value, bool):
            values.add(int(value))
        elif isinstance(value, int):
            values.add(value)
        else:
            return False
        labels.add(str(item.get("label", "")).strip().lower())

    return values == {0, 1} and frozenset(labels) in _BOOLEAN_ENUM_LABELS


def _channel_tx_metadata(channel: dict[str, Any]) -> dict[str, Any] | None:
    semantic_role = channel.get("semantic_role")
    channel_type = channel.get("channel_type")
    name = channel.get("name")

    if semantic_role == "enocean.telegram_type":
        return {
            "managed": True,
            "default_value": "data_telegram",
            "required_for_snapshot": False,
        }

    if _is_availability_channel(channel):
        tx_metadata: dict[str, Any] = {
            "managed": True,
            "runtime_default": "channel_enabled",
            "required_for_snapshot": False,
        }
        reference_channel = _availability_reference_channel(channel)

        if reference_channel is not None:
            tx_metadata["runtime_default_channel"] = reference_channel

        return tx_metadata

    if channel_type in {"measurement", "state"}:
        return {
            "managed": False,
            "required_for_snapshot": True,
        }

    if name in {"telegram_type"}:
        return {
            "managed": True,
            "default_value": "data_telegram",
            "required_for_snapshot": False,
        }

    return None


def _is_availability_channel(channel: dict[str, Any]) -> bool:
    name = str(channel.get("name", "")).lower()
    semantic_role = str(channel.get("semantic_role", "")).lower()

    if "sensor_available" in semantic_role:
        return True

    if name.endswith("_available") or name in {"t_sensor", "temp_sensor"}:
        return True

    enum_items = channel.get("enum")

    if not isinstance(enum_items, list):
        return False

    labels = {
        str(item.get("label", "")).lower()
        for item in enum_items
        if isinstance(item, dict)
    }

    return {"available", "not_available"}.issubset(labels)


def _availability_reference_channel(channel: dict[str, Any]) -> str | None:
    name = str(channel.get("name", "")).strip().lower()

    if name in {"t_sensor", "temp_sensor"}:
        return "temperature"

    if name.endswith("_available"):
        reference = name.removesuffix("_available")
        return reference or None

    return None


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()

    if not normalized:
        return None

    return normalized
