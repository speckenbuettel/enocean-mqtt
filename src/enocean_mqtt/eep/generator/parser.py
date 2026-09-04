"""EEP XML parser for normalized telegram-centric registry generation."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any


class EEPGeneratorError(RuntimeError):
    """Raised when EEP XML generation fails."""


SEMANTIC_NAME_MAP = {
    "lrnb": "telegram_type",
    "svc": "supply_voltage",
    "ct": "contact",
    "vib": "vibration",
    "tmp": "temperature",
    "hum": "humidity",
    "cv": "current_value",
}

SEMANTIC_ROLE_MAP = {
    "telegram_type": "enocean.telegram_type",
    "supply_voltage": "device.supply_voltage",
    "contact": "opening.contact",
    "vibration": "security.vibration",
    "temperature": "environment.temperature",
    "humidity": "environment.humidity",
}

METADATA_SHORTCUTS = {"tsl", "sps", "enie"}
DIAGNOSTIC_SHORTCUTS = {"rce", "rss", "lb", "svc"}
STATUS_SHORTCUTS = {"lrnb", "es", "dwo", "aco", "cmd"}
CONFIGURATION_SHORTCUTS = {
    "rfc",
    "dt1",
    "dt2",
    "dt3",
    "minv",
    "maxv",
    "lc",
    "ds",
}
STATE_CHANNELS = {
    "contact",
    "vibration",
    "switch_state",
    "relay_state",
    "occupancy",
    "window_open_detection",
}
DESCRIPTION_KEYWORDS = {
    "sensor",
    "switch",
    "window",
    "door",
    "temperature",
    "humidity",
    "occupancy",
    "light",
    "alarm",
    "detector",
    "meter",
    "contact",
}
RANGE_SELECTOR_SHORTCUTS = {"lo": "lom", "tmp": "tsl", "sp": "sps"}
RANGE_SELECTOR_VALUE_OVERRIDES = {("lo", "lom"): [1]}


@dataclass(slots=True)
class RawConditionNode:
    """Raw condition node as represented in XML."""

    direction: str | None = None
    datafields: list[ET.Element] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class RawCaseNode:
    """Raw recursive XML case node."""

    index: int
    title: str | None
    description: str | None
    direction: str | None
    condition: RawConditionNode | None
    datafields: list[ET.Element] = dataclass_field(default_factory=list)
    statusfields: list[ET.Element] = dataclass_field(default_factory=list)
    cases: list[RawCaseNode] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class RawTypeNode:
    """Raw XML type node."""

    eep: str
    rorg: str
    func: str
    type: str
    func_description: str
    type_description: str
    datafields: list[ET.Element]
    statusfields: list[ET.Element]
    cases: list[RawCaseNode]


def _text(element: ET.Element, name: str) -> str:
    return (element.findtext(name) or "").strip()


def _direct_children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in list(element) if child.tag == tag]


def _normalize_hex(value: str) -> str:
    value = value.strip().upper()
    if value.startswith("0X"):
        value = value[2:]
    return value.zfill(2)


def _parse_int(value: str) -> int:
    normalized = value.strip().lower()
    binary_match = re.match(r"^(0b[01]+)", normalized)
    if binary_match:
        return int(binary_match.group(1)[2:], 2)
    hex_match = re.match(r"^(0x[0-9a-f]+)", normalized)
    if hex_match:
        return int(hex_match.group(1)[2:], 16)
    decimal_match = re.match(r"^([-+]?\d+)", normalized)
    if decimal_match:
        return int(decimal_match.group(1))
    raise ValueError(f"Invalid integer value: {value}")


def _parse_float(value: str) -> float | None:
    normalized = value.strip().replace(",", ".")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
        return None
    return float(normalized)


def _label(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _semantic_name(shortcut: str, fallback: str) -> str:
    key = _label(shortcut)
    if key in SEMANTIC_NAME_MAP:
        return SEMANTIC_NAME_MAP[key]
    return _label(fallback)


def _build_description(func_description: str, type_description: str) -> str:
    func_description = func_description.strip()
    type_description = type_description.strip()
    if not func_description:
        return type_description
    if not type_description:
        return func_description
    if any(keyword in type_description.lower() for keyword in DESCRIPTION_KEYWORDS):
        return type_description
    return f"{func_description}, {type_description}"


def _parse_range(item: ET.Element) -> tuple[int | float, int | float] | None:
    min_text = _text(item, "min")
    max_text = _text(item, "max")
    if not min_text or not max_text:
        return None
    try:
        return _parse_int(min_text), _parse_int(max_text)
    except ValueError:
        min_float = _parse_float(min_text)
        max_float = _parse_float(max_text)
        if min_float is None or max_float is None:
            return None
        return min_float, max_float


def _datafield_raw_range(datafield: ET.Element) -> tuple[int | float, int | float] | None:
    range_element = datafield.find("range")
    if range_element is None:
        return None
    return _parse_range(range_element)


def _semantic_raw_range(datafield: ET.Element) -> tuple[int | float, int | float] | None:
    direct_range = _datafield_raw_range(datafield)
    if direct_range is not None:
        return direct_range
    enum = datafield.find("enum")
    if enum is None:
        return None
    for item in enum.findall("item"):
        if item.find("scale") is None:
            continue
        raw_range = _parse_range(item)
        if raw_range is not None:
            return raw_range
    return None


def _physical_raw_max(datafield: ET.Element) -> int:
    bitsize = int(_text(datafield, "bitsize") or 0)
    if bitsize <= 0:
        return 0
    return int((1 << bitsize) - 1)


def _parse_scale_element(
    scale: ET.Element,
    datafield: ET.Element,
    raw_min: int | float | None = None,
    raw_max: int | float | None = None,
) -> dict[str, float | int]:
    scale_min = _parse_float(_text(scale, "min"))
    scale_max = _parse_float(_text(scale, "max"))
    if scale_min is None or scale_max is None:
        raise EEPGeneratorError("Invalid scale definition")
    if raw_min is None or raw_max is None:
        semantic_range = _semantic_raw_range(datafield)
        if semantic_range is not None:
            raw_min, raw_max = semantic_range
    return {
        "raw_min": 0 if raw_min is None else raw_min,
        "raw_max": _physical_raw_max(datafield) if raw_max is None else raw_max,
        "scale_min": scale_min,
        "scale_max": scale_max,
    }


def _parse_scale(datafield: ET.Element) -> dict[str, float | int] | None:
    scale = datafield.find("scale")
    if scale is None:
        semantic_range = _semantic_raw_range(datafield)
        if semantic_range is None:
            return None
        enum = datafield.find("enum")
        if enum is None:
            return None
        for item in enum.findall("item"):
            item_scale = item.find("scale")
            if item_scale is not None:
                return _parse_scale_element(
                    item_scale,
                    datafield,
                    semantic_range[0],
                    semantic_range[1],
                )
        return None
    return _parse_scale_element(scale, datafield)


def _value_resolution(scale: dict[str, float | int] | None) -> float | None:
    if scale is None:
        return None
    raw_span = abs(float(scale["raw_max"]) - float(scale["raw_min"]))
    if raw_span == 0:
        return None
    return abs(float(scale["scale_max"]) - float(scale["scale_min"])) / raw_span


def _value_precision(resolution: float | None) -> int | None:
    if resolution is None:
        return None
    if resolution >= 1:
        return 0
    if resolution >= 0.1:
        return 1
    if resolution >= 0.01:
        return 2
    if resolution >= 0.001:
        return 3
    return 4


def _parse_enum_values(value: str) -> list[int]:
    normalized = value.strip()
    range_match = re.fullmatch(r"(.+?)\s*(?:\.\.\.|\.\.|-)\s*(.+)", normalized)
    if range_match:
        start = _parse_int(range_match.group(1))
        end = _parse_int(range_match.group(2))
        if end < start:
            raise EEPGeneratorError(f"Invalid enum range: {value}")
        return list(range(start, end + 1))
    return [_parse_int(normalized)]


def _parse_enum_items(datafield: ET.Element) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    enum = datafield.find("enum")
    if enum is None:
        return values
    for item in enum.findall("item"):
        if item.find("min") is not None or item.find("max") is not None:
            continue
        raw_value = _text(item, "value")
        description = _text(item, "description")
        if not raw_value:
            continue
        label = _label(description or raw_value)
        for value in _parse_enum_values(raw_value):
            values.append({"value": value, "label": label})
    return values


def _selector_dependency(
    selector_channel: dict[str, Any] | None,
    value: int,
) -> dict[str, Any] | None:
    if selector_channel is None:
        return None
    return {"source": "field", "field": selector_channel["name"], "equals": value}


def _selector_values(
    datafield: ET.Element,
    selector_channel: dict[str, Any] | None,
) -> list[int]:
    selector_shortcut = ""
    field_shortcut = _label(_text(datafield, "shortcut"))
    if selector_channel is not None:
        selector_shortcut = _label(selector_channel.get("shortcut", ""))
    override = RANGE_SELECTOR_VALUE_OVERRIDES.get((field_shortcut, selector_shortcut))
    if override is not None:
        return override
    if selector_channel is None:
        return []
    return [int(item["value"]) for item in selector_channel.get("enum", [])]


def _parse_range_items(
    datafield: ET.Element,
    selector_channel: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    enum = datafield.find("enum")
    if enum is None:
        return ranges
    selector_values = _selector_values(datafield, selector_channel)
    for range_index, item in enumerate(enum.findall("item")):
        raw_range = _parse_range(item)
        if raw_range is None:
            continue
        range_mapping: dict[str, Any] = {
            "raw_min": raw_range[0],
            "raw_max": raw_range[1],
        }
        description = _text(item, "description")
        if description:
            range_mapping["label"] = _label(description)
        if range_index < len(selector_values):
            dependency = _selector_dependency(
                selector_channel,
                selector_values[range_index],
            )
            if dependency is not None:
                range_mapping["depends_on"] = dependency
        scale = item.find("scale")
        if scale is not None:
            range_mapping["scale"] = _parse_scale_element(
                scale,
                datafield,
                raw_range[0],
                raw_range[1],
            )
        unit = _text(item, "unit")
        if unit:
            range_mapping["unit"] = unit
        ranges.append(range_mapping)
    return ranges


def _bitfield_from_datafield(
    field: ET.Element,
    source: str = "payload",
) -> dict[str, Any]:
    data = _text(field, "data")
    shortcut = _text(field, "shortcut")
    bitoffs = int(_text(field, "bitoffs") or 0)
    bitsize = int(_text(field, "bitsize") or 0)
    if not data and not shortcut:
        generated_name = f"reserved_{bitoffs}_{bitsize}"
        data = f"Reserved field {bitoffs}:{bitsize}"
    else:
        generated_name = _semantic_name(shortcut, data or f"field_{bitoffs}")
    return {
        "name": generated_name,
        "offset": bitoffs,
        "size": bitsize,
        "shortcut": shortcut,
        "description": data,
        "raw_min": 0,
        "raw_max": _physical_raw_max(field),
        "source": source,
    }


def _is_reserved_bitfield(bitfield: dict[str, Any]) -> bool:
    return str(bitfield.get("name", "")).startswith("reserved_")


def _has_scaled_range(ranges: list[dict[str, Any]]) -> bool:
    return any("scale" in item for item in ranges)


def _infer_channel_type(
    *,
    name: str,
    shortcut: str,
    rorg: str,
    direction: str | None,
    has_scale: bool,
    for_message: bool,
) -> str:
    shortcut_key = _label(shortcut)
    if for_message:
        if shortcut_key in CONFIGURATION_SHORTCUTS:
            return "configuration"
        if shortcut_key in METADATA_SHORTCUTS:
            return "metadata"
        if shortcut_key in DIAGNOSTIC_SHORTCUTS:
            return "diagnostic"
        return "command_parameter"
    if rorg.upper() == "F6":
        return "event"
    if shortcut_key in METADATA_SHORTCUTS:
        return "metadata"
    if shortcut_key in DIAGNOSTIC_SHORTCUTS:
        return "diagnostic"
    if shortcut_key in CONFIGURATION_SHORTCUTS:
        return "configuration"
    if shortcut_key in STATUS_SHORTCUTS:
        return "status"
    if has_scale:
        return "measurement"
    if name in STATE_CHANNELS:
        return "state"
    return "status"


def _output_policy(channel_type: str) -> dict[str, bool]:
    mqtt_enabled = channel_type not in {"metadata"}
    return {"mqtt": mqtt_enabled, "api": True, "storage": True}


def _build_channel(
    field: ET.Element,
    selector_channel: dict[str, Any] | None = None,
    *,
    rorg: str = "",
    direction: str | None = None,
    for_message: bool = False,
) -> dict[str, Any] | None:
    bitfield = _bitfield_from_datafield(field)
    if _is_reserved_bitfield(bitfield):
        return None
    generated_name = bitfield["name"]
    scale = _parse_scale(field)
    range_values = _parse_range_items(field, selector_channel)
    enum_values = _parse_enum_items(field)
    has_scale = scale is not None or _has_scaled_range(range_values)
    channel_type = _infer_channel_type(
        name=generated_name,
        shortcut=bitfield.get("shortcut", ""),
        rorg=rorg,
        direction=direction,
        has_scale=has_scale,
        for_message=for_message,
    )
    channel: dict[str, Any] = {
        "name": generated_name,
        "display_name": None,
        "channel_type": channel_type,
        "data_type": "float" if has_scale else "integer",
        "output": _output_policy(channel_type),
    }
    semantic_role = SEMANTIC_ROLE_MAP.get(generated_name)
    if semantic_role:
        channel["semantic_role"] = semantic_role
    unit = _text(field, "unit")
    if unit:
        channel["unit"] = unit
    effective_scale = scale
    if effective_scale is None:
        for item in range_values:
            if "scale" in item:
                effective_scale = item["scale"]
                break
    resolution = _value_resolution(effective_scale)
    precision = _value_precision(resolution)
    if resolution is not None:
        channel["value_resolution"] = resolution
    if precision is not None:
        channel["value_precision"] = precision
    if enum_values:
        channel["data_type"] = "enum"
        channel["enum"] = enum_values
    if range_values:
        channel["ranges"] = range_values
        if not enum_values:
            channel["data_type"] = "float" if has_scale else "integer"
    return channel


def _build_binding(
    field: ET.Element,
    selector_channel: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    bitfield = _bitfield_from_datafield(field)
    if _is_reserved_bitfield(bitfield):
        return None
    name = bitfield["name"]
    binding: dict[str, Any] = {
        "channel_ref": name,
        "field_ref": name,
        "bitfield_ref": name,
    }
    scale = _parse_scale(field)
    range_values = _parse_range_items(field, selector_channel)
    enum_values = _parse_enum_items(field)
    if scale is not None:
        binding["scale"] = scale
    if enum_values:
        binding["enum"] = enum_values
    if range_values:
        binding["ranges"] = range_values
    return binding


def _parse_condition(condition: ET.Element | None) -> RawConditionNode | None:
    if condition is None:
        return None
    return RawConditionNode(
        direction=_text(condition, "direction") or None,
        datafields=_direct_children(condition, "datafield"),
    )


def _parse_case(case: ET.Element, index: int) -> RawCaseNode:
    return RawCaseNode(
        index=index,
        title=_text(case, "title") or None,
        description=_text(case, "description") or None,
        direction=_text(case, "direction") or None,
        condition=_parse_condition(case.find("condition")),
        datafields=_direct_children(case, "datafield"),
        statusfields=_direct_children(case, "statusfield"),
        cases=[
            _parse_case(child_case, child_index)
            for child_index, child_case in enumerate(
                _direct_children(case, "case"),
                start=1,
            )
        ],
    )


def _find_type_node(root: ET.Element, eep_id: str) -> RawTypeNode:
    target_rorg, target_func, target_type = [
        _normalize_hex(part) for part in eep_id.split("-")
    ]
    for rorg in root.findall("./profile/rorg"):
        rorg_number = _normalize_hex(_text(rorg, "number"))
        if rorg_number != target_rorg:
            continue
        for func in _direct_children(rorg, "func"):
            func_number = _normalize_hex(_text(func, "number"))
            if func_number != target_func:
                continue
            func_description = _text(func, "title") or _text(func, "description")
            for eep_type in _direct_children(func, "type"):
                type_number = _normalize_hex(_text(eep_type, "number"))
                if type_number != target_type:
                    continue
                type_description = _text(eep_type, "title") or _text(
                    eep_type,
                    "description",
                )
                return RawTypeNode(
                    eep=f"{target_rorg}-{target_func}-{target_type}",
                    rorg=target_rorg,
                    func=target_func,
                    type=target_type,
                    func_description=func_description,
                    type_description=type_description,
                    datafields=_direct_children(eep_type, "datafield"),
                    statusfields=_direct_children(eep_type, "statusfield"),
                    cases=[
                        _parse_case(case, index)
                        for index, case in enumerate(
                            _direct_children(eep_type, "case"),
                            start=1,
                        )
                    ],
                )
    raise EEPGeneratorError(f"EEP not found in XML: {eep_id}")


def _datafields_to_fields(datafields: list[ET.Element]) -> list[dict[str, Any]]:
    return [_bitfield_from_datafield(field) for field in datafields]


def _statusfields_to_fields(statusfields: list[ET.Element]) -> list[dict[str, Any]]:
    return [
        _bitfield_from_datafield(statusfield, source="status")
        for statusfield in statusfields
    ]


def _condition_dependency(condition: RawConditionNode | None) -> dict[str, Any] | None:
    if condition is None:
        return None
    if condition.direction is not None:
        return {
            "source": "telegram_id",
            "field": "direction",
            "equals": condition.direction,
        }
    if not condition.datafields:
        return None
    condition_field = condition.datafields[0]
    shortcut = _text(condition_field, "shortcut") or _text(condition_field, "data")
    value = _text(condition_field, "value")
    if not shortcut or not value:
        return None
    return {
        "source": "field",
        "field": _semantic_name(shortcut, shortcut),
        "equals": value,
    }


def _condition_command(condition: RawConditionNode | None) -> int | None:
    if condition is None or not condition.datafields:
        return None
    for condition_field in condition.datafields:
        value = _text(condition_field, "value")
        if not value:
            continue
        try:
            return _parse_int(value)
        except ValueError:
            continue
    return None


def _case_command(case: RawCaseNode) -> int | None:
    command = _condition_command(case.condition)
    if command is not None:
        return command
    text = f"{case.title or ''} {case.description or ''}"
    hex_match = re.search(r"\bCMD\s+0x([0-9a-fA-F]+)\b", text)
    if hex_match:
        return int(hex_match.group(1), 16)
    decimal_match = re.search(r"\bCMD\s+(\d+)\b", text)
    if decimal_match:
        return int(decimal_match.group(1))
    return None


def _case_runtime_direction(case: RawCaseNode) -> str | None:
    if case.direction == "1":
        return "rx"
    if case.direction == "2":
        return "tx"
    text = f"{case.title or ''} {case.description or ''}".lower()
    if "direction: to" in text:
        return "tx"
    if "direction: from" in text:
        return "rx"
    return None


def _case_suffix(case: RawCaseNode) -> str:
    command = _case_command(case)
    runtime_direction = _case_runtime_direction(case)
    dependency = _condition_dependency(case.condition)
    suffix_parts: list[str] = []
    if command is not None:
        suffix_parts.append(f"cmd{command:02x}")
    if runtime_direction is not None:
        suffix_parts.append(runtime_direction)
    if dependency is not None:
        field = dependency.get("field")
        equals = dependency.get("equals")
        if field is not None and equals is not None:
            suffix_parts.append(f"{_label(str(field))}{_label(str(equals))}")
    description = case.title or case.description
    if description:
        suffix_parts.append(_label(description))
    if not suffix_parts:
        suffix_parts.append(f"case{case.index}")
    return ".".join(suffix_parts)


def _case_description(case: RawCaseNode) -> str | None:
    return case.title or case.description


def _selector_for_field(
    field: ET.Element,
    channels_by_shortcut: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    field_shortcut = _label(_text(field, "shortcut"))
    selector_shortcut = RANGE_SELECTOR_SHORTCUTS.get(field_shortcut)
    if selector_shortcut is None:
        return None
    return channels_by_shortcut.get(selector_shortcut)


def _build_channels_and_bindings(
    datafields: list[ET.Element],
    *,
    rorg: str = "",
    direction: str | None = None,
    for_message: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    channels: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    channels_by_shortcut: dict[str, dict[str, Any]] = {}
    for datafield in datafields:
        channel = _build_channel(
            datafield,
            rorg=rorg,
            direction=direction,
            for_message=for_message,
        )
        if channel is None:
            continue
        shortcut = _label(_text(datafield, "shortcut"))
        if shortcut:
            channels_by_shortcut[shortcut] = channel
    for datafield in datafields:
        selector_channel = _selector_for_field(datafield, channels_by_shortcut)
        channel = _build_channel(
            datafield,
            selector_channel,
            rorg=rorg,
            direction=direction,
            for_message=for_message,
        )
        binding = _build_binding(datafield, selector_channel)
        if channel is not None:
            channels.append(channel)
        if binding is not None:
            bindings.append(binding)
    return channels, bindings


def _split_channels(
    channels: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload_channels: list[dict[str, Any]] = []
    metadata_channels: list[dict[str, Any]] = []
    for channel in channels:
        if channel.get("channel_type") == "metadata":
            metadata_channels.append(channel)
        else:
            payload_channels.append(channel)
    return payload_channels, metadata_channels


def _case_telegrams(
    eep_id: str,
    rorg: str,
    cases: list[RawCaseNode],
    parent_fields: list[ET.Element] | None = None,
    parent_statusfields: list[ET.Element] | None = None,
) -> list[dict[str, Any]]:
    telegrams: list[dict[str, Any]] = []
    inherited_fields = parent_fields or []
    inherited_statusfields = parent_statusfields or []
    for case in cases:
        field_elements = [*inherited_fields, *case.datafields]
        statusfield_elements = [*inherited_statusfields, *case.statusfields]
        runtime_direction = _case_runtime_direction(case)
        channels, bindings = _build_channels_and_bindings(
            field_elements,
            rorg=rorg,
            direction=runtime_direction,
        )
        message_channels, message_bindings = _build_channels_and_bindings(
            field_elements,
            rorg=rorg,
            direction=runtime_direction,
            for_message=True,
        )
        _payload_channels, metadata_channels = _split_channels(channels)
        command = _case_command(case)
        suffix = _case_suffix(case)
        dependency = _condition_dependency(case.condition)
        telegram: dict[str, Any] = {
            "telegram_type_id": f"{eep_id.lower()}.{suffix}",
            "telegram_id": {"rorg": rorg},
            "fields": _datafields_to_fields(field_elements),
            "status_fields": _statusfields_to_fields(statusfield_elements),
            "channel_bindings": bindings if runtime_direction != "tx" else [],
            "messages": [],
            "metadata_channels": metadata_channels,
            "constraints": [],
            "context_updates": [],
        }
        if runtime_direction is not None:
            telegram["direction"] = runtime_direction
        if command is not None:
            telegram["telegram_id"]["cmd"] = f"0x{command:02X}"
        description = _case_description(case)
        if description:
            telegram["description"] = description
        if dependency is not None:
            telegram["depends_on"] = dependency
        if runtime_direction == "tx":
            telegram["messages"] = [
                {
                    "name": _label(description or suffix),
                    "message_type": "command",
                    "description": description,
                    "channels": message_channels,
                    "channel_bindings": message_bindings,
                }
            ]
        telegrams.append(telegram)
        telegrams.extend(
            _case_telegrams(
                eep_id=eep_id,
                rorg=rorg,
                cases=case.cases,
                parent_fields=field_elements,
                parent_statusfields=statusfield_elements,
            )
        )
    return telegrams


def _default_telegram(
    eep_id: str,
    rorg: str,
    datafields: list[ET.Element],
    statusfields: list[ET.Element],
) -> dict[str, Any] | None:
    if not datafields and not statusfields:
        return None
    channels, bindings = _build_channels_and_bindings(
        datafields,
        rorg=rorg,
        direction="rx",
    )
    _payload_channels, metadata_channels = _split_channels(channels)
    return {
        "telegram_type_id": f"{eep_id.lower()}.default",
        "telegram_id": {"rorg": rorg},
        "direction": "rx",
        "fields": _datafields_to_fields(datafields),
        "status_fields": _statusfields_to_fields(statusfields),
        "channel_bindings": bindings,
        "messages": [],
        "metadata_channels": metadata_channels,
        "constraints": [],
        "context_updates": [],
    }


def _deduplicate_named_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        name = item.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(item)
    return result


def _collect_case_datafields(cases: list[RawCaseNode]) -> list[ET.Element]:
    datafields: list[ET.Element] = []
    for case in cases:
        datafields.extend(case.datafields)
        datafields.extend(_collect_case_datafields(case.cases))
    return datafields


def _profile_channel_unions(
    telegrams: list[dict[str, Any]],
    raw_type_node: RawTypeNode,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    channels: list[dict[str, Any]] = []
    metadata_channels: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    profile_datafields = [
        *raw_type_node.datafields,
        *_collect_case_datafields(raw_type_node.cases),
    ]
    top_channels, _bindings = _build_channels_and_bindings(
        profile_datafields,
        rorg=raw_type_node.rorg,
        direction="rx",
    )
    payload_channels, top_metadata_channels = _split_channels(top_channels)
    channels.extend(payload_channels)
    metadata_channels.extend(top_metadata_channels)
    for telegram in telegrams:
        metadata_channels.extend(telegram.get("metadata_channels", []))
        messages.extend(telegram.get("messages", []))
    return (
        _deduplicate_named_items(channels),
        _deduplicate_named_items(metadata_channels),
        _deduplicate_named_items(messages),
    )


def load_eep_definition(xml_path: str | Path, eep_id: str) -> dict[str, Any]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    type_node = _find_type_node(root, eep_id)
    definition: dict[str, Any] = {
        "profile_type": "standard",
        "eep": type_node.eep,
        "rorg": type_node.rorg,
        "func": type_node.func,
        "type": type_node.type,
        "func_description": type_node.func_description,
        "type_description": type_node.type_description,
        "description": _build_description(
            type_node.func_description,
            type_node.type_description,
        ),
        "source": "EnOcean Equipment Profiles",
        "source_version": "2.6.8",
    }
    telegrams = _case_telegrams(
        eep_id=type_node.eep,
        rorg=type_node.rorg,
        cases=type_node.cases,
    )
    default_telegram = _default_telegram(
        eep_id=type_node.eep,
        rorg=type_node.rorg,
        datafields=type_node.datafields,
        statusfields=type_node.statusfields,
    )
    if default_telegram is not None:
        telegrams.insert(0, default_telegram)
    channels, metadata_channels, messages = _profile_channel_unions(
        telegrams,
        type_node,
    )
    definition["telegrams"] = telegrams
    if channels:
        definition["channels"] = channels
    if metadata_channels:
        definition["metadata_channels"] = metadata_channels
    if messages:
        definition["messages"] = messages
    return definition
