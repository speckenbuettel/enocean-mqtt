"""Write normalized EEP registry JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    "direction",
    "addressing",
    "teach_in_method",
    "security",
    "channels",
    "messages",
    "metadata_channels",
    "telegrams",
    "metadata",
]

TELEGRAM_ORDER = [
    "telegram_type_id",
    "telegram_id",
    "direction",
    "description",
    "teach_in",
    "fields",
    "status_fields",
    "channel_bindings",
    "messages",
    "metadata_channels",
    "channels",
    "constraints",
    "context_updates",
    "security",
    "metadata",
]

CHANNEL_ORDER = [
    "name",
    "display_name",
    "channel_type",
    "data_type",
    "unit",
    "writable",
    "semantic_role",
    "value_precision",
    "value_resolution",
    "output",
    "enum",
    "ranges",
    "depends_on",
    "metadata",
    # Legacy fields retained for transitional compatibility.
    "friendly_name",
    "field_ref",
    "bitfield",
    "scale",
]

CHANNEL_BINDING_ORDER = [
    "channel_ref",
    "field_ref",
    "bitfield_ref",
    "scale",
    "enum",
    "ranges",
    "depends_on",
    "metadata",
]

BITFIELD_ORDER = [
    "name",
    "offset",
    "size",
    "bitrange",
    "shortcut",
    "description",
    "raw_min",
    "raw_max",
    "source",
    "metadata",
]

PRESERVE_NULL_KEYS = {
    "display_name",
}


def _should_keep(key: str, value: Any) -> bool:
    if key in PRESERVE_NULL_KEYS and value is None:
        return True
    return value not in (None, [], {})


def _ordered_dict(data: dict[str, Any], order: list[str]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}

    for key in order:
        if key in data and _should_keep(key, data[key]):
            ordered[key] = _normalize_value(key, data[key])

    for key in sorted(data):
        if key not in ordered and _should_keep(key, data[key]):
            ordered[key] = _normalize_value(key, data[key])

    return ordered


def _normalize_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        if key == "bitfield" or {"offset", "size"}.issubset(value.keys()):
            return _ordered_dict(value, BITFIELD_ORDER)

        return {
            item_key: _normalize_value(item_key, item_value)
            for item_key, item_value in value.items()
            if _should_keep(item_key, item_value)
        }

    if isinstance(value, list):
        return [_normalize_value(key, item) for item in value]

    return value


def _normalize_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return _ordered_dict(channel, CHANNEL_ORDER)


def _normalize_channel_binding(binding: dict[str, Any]) -> dict[str, Any]:
    return _ordered_dict(binding, CHANNEL_BINDING_ORDER)


def _normalize_telegram(telegram: dict[str, Any]) -> dict[str, Any]:
    normalized = _ordered_dict(telegram, TELEGRAM_ORDER)

    if "channel_bindings" in normalized:
        normalized["channel_bindings"] = [
            _normalize_channel_binding(binding)
            for binding in normalized["channel_bindings"]
        ]

    if "channels" in normalized:
        normalized["channels"] = [
            _normalize_channel(channel)
            for channel in normalized["channels"]
        ]

    if "metadata_channels" in normalized:
        normalized["metadata_channels"] = [
            _normalize_channel(channel)
            for channel in normalized["metadata_channels"]
        ]

    if "messages" in normalized:
        normalized["messages"] = [
            {
                item_key: _normalize_value(item_key, item_value)
                for item_key, item_value in message.items()
                if _should_keep(item_key, item_value)
            }
            for message in normalized["messages"]
        ]

    return normalized


def normalize_registry_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Return a stable JSON-ready registry representation."""

    normalized = _ordered_dict(definition, TOP_LEVEL_ORDER)

    if "channels" in normalized:
        normalized["channels"] = [
            _normalize_channel(channel)
            for channel in normalized["channels"]
        ]

    if "metadata_channels" in normalized:
        normalized["metadata_channels"] = [
            _normalize_channel(channel)
            for channel in normalized["metadata_channels"]
        ]

    if "telegrams" in normalized:
        normalized["telegrams"] = [
            _normalize_telegram(telegram)
            for telegram in normalized["telegrams"]
        ]

    return normalized


def write_eep_json(definition: dict[str, Any], output_dir: str | Path) -> Path:
    """Write normalized EEP JSON file."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    target_file = output_path / f"{definition['eep']}.json"
    normalized_definition = normalize_registry_definition(definition)

    with target_file.open("w", encoding="utf-8") as handle:
        json.dump(normalized_definition, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    return target_file
