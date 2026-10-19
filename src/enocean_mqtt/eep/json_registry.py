"""JSON-based normalized EEP runtime registry loader.

This module loads Registry v3 EEP JSON files into the runtime dataclass model.

Registry v3 deliberately separates:

- raw protocol fields (``fields`` / ``status_fields``),
- semantic RX objects (``channels``),
- semantic TX objects (``messages``),
- telegram-specific mappings (``channel_bindings`` /
  ``message_bindings``).

The loader still accepts a small number of transitional fields emitted by older
Compiler 3.0 iterations so that the runtime can be migrated layer by layer
without losing test coverage.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from threading import RLock
from typing import Any

from enocean_mqtt.eep.models import (
    ChannelBindingDefinition,
    ChannelDefinition,
    ConstraintDefinition,
    ContextUpdateDefinition,
    DependencyDefinition,
    DependencyDescription,
    EEPDefinition,
    FieldDefinition,
    FieldPartDefinition,
    FunctionGroupDefinition,
    LinearScale,
    MessageBindingDefinition,
    MessageDefinition,
    OutputDefinition,
    RuntimeHintDefinition,
    TelegramDefinition,
    TelegramIdentity,
    TxDefinition,
    ValueMapping,
    ValueRangeMapping,
)

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path("eep/registry")

STANDARD_EEP_PATTERN = re.compile(
    r"^[A-F0-9]{2}-[A-F0-9]{2}-[A-F0-9]{2}$",
    re.IGNORECASE,
)


class EEPRegistryError(RuntimeError):
    """Raised when EEP registry loading fails."""


_cache_lock = RLock()
_definition_cache: dict[tuple[Path, Path], dict[str, EEPDefinition]] = {}


def _cache_scope() -> tuple[Path, Path]:
    # Do not inspect files or follow changed symlinks on a cache hit.
    return (_registry_path().absolute(), DEFAULT_REGISTRY_PATH.absolute())


def load_eep_definition(eep: str) -> EEPDefinition:
    """Return a shared profile, loading on first use until explicit reload.

    Consumers must treat the returned definition as read-only.
    """
    filename = _resolve_registry_filename(eep)
    with _cache_lock:
        cache = _definition_cache.setdefault(_cache_scope(), {})
        if filename not in cache:
            cache[filename] = _read_eep_definition(eep)
        return cache[filename]


def reload_eep_definitions() -> list[str]:
    """Validate all available and cached profiles, then replace atomically.

    A missing or invalid profile leaves the previous cache unchanged. The lock
    also prevents a concurrent first load from being lost during replacement.
    """
    with _cache_lock:
        scope = _cache_scope()
        filenames = set(_definition_cache.get(scope, {}))
        for directory in set(scope):
            filenames.update(path.name for path in directory.glob("*.json"))
        candidate: dict[str, EEPDefinition] = {}
        for filename in sorted(filenames):
            try:
                candidate[filename] = _read_eep_definition(filename[:-5])
            except Exception as exc:
                raise EEPRegistryError(
                    f"EEP reload rejected for {filename}: {exc}"
                ) from exc
        _definition_cache[scope] = candidate
        return sorted(candidate)


def _registry_path() -> Path:
    """Resolve runtime EEP registry path."""

    configured = os.getenv("ENOCEAN_MQTT_EEP_REGISTRY")

    if configured:
        return Path(configured)

    return DEFAULT_REGISTRY_PATH


def _load_scale(data: dict[str, Any] | None) -> LinearScale | None:
    if not data:
        return None

    return LinearScale(
        raw_min=data["raw_min"],
        raw_max=data["raw_max"],
        scale_min=data["scale_min"],
        scale_max=data["scale_max"],
    )


def _load_enum(data: list[dict[str, Any]] | None) -> list[ValueMapping]:
    return [
        ValueMapping(
            value=item["value"],
            label=item["label"],
            semantic_value=item.get("semantic_value"),
            description=item.get("description"),
        )
        for item in data or []
    ]


def _load_dependency(data: dict[str, Any] | None) -> DependencyDefinition | None:
    if not data:
        return None

    try:
        from enocean_mqtt.eep.numeric_conditions import validate_bounds

        validate_bounds(data.get("gte"), data.get("lte"))
    except ValueError as exc:
        raise EEPRegistryError(f"Invalid dependency bounds: {exc}") from exc

    return DependencyDefinition(
        field=data["field"],
        source=data.get("source", "field"),
        equals=data.get("equals"),
        not_equals=data.get("not_equals"),
        values=data.get("values", []),
        metadata=data.get("metadata", {}),
        gte=data.get("gte"),
        lte=data.get("lte"),
    )


def _load_dependency_description(
    data: dict[str, Any] | None,
) -> DependencyDescription | None:
    if not data:
        return None

    return DependencyDescription(
        target=data.get("target"),
        depends_on=_load_dependency(data.get("depends_on")),
        reason=data.get("reason"),
        description=data.get("description"),
        metadata=data.get("metadata", {}),
    )


def _load_dependency_descriptions(
    data: list[dict[str, Any]] | None,
) -> list[DependencyDescription]:
    return [
        dependency
        for dependency in (
            _load_dependency_description(item)
            for item in data or []
        )
        if dependency is not None
    ]


def _load_ranges(data: list[dict[str, Any]] | None) -> list[ValueRangeMapping]:
    ranges: list[ValueRangeMapping] = []

    for item in data or []:
        ranges.append(
            ValueRangeMapping(
                min=item.get("min"),
                max=item.get("max"),
                step=item.get("step"),
                unit=item.get("unit"),
                description=item.get("description"),
                raw_min=item.get("raw_min"),
                raw_max=item.get("raw_max"),
                label=item.get("label"),
                scale=_load_scale(item.get("scale")),
                depends_on=_load_dependency(item.get("depends_on")),
            )
        )

    return ranges


def _load_field(data: dict[str, Any], *, default_source: str = "payload") -> FieldDefinition:
    return FieldDefinition(
        name=data["name"],
        offset=data["offset"],
        size=data["size"],
        shortcut=data.get("shortcut"),
        description=data.get("description"),
        data_type=data.get("data_type"),
        signed=data.get("signed", False),
        raw_min=data.get("raw_min"),
        raw_max=data.get("raw_max"),
        enum=_load_enum(data.get("enum")),
        default_value=data.get("default_value"),
        reserved=data.get("reserved", False),
        constant=data.get("constant"),
        source=data.get("source", default_source),
        metadata=data.get("metadata", {}),
        bitrange=data.get("bitrange"),
    )


# Backwards-compatible name used by current runtime modules.
_load_bitfield = _load_field


def _load_runtime(data: dict[str, Any] | None) -> RuntimeHintDefinition | None:
    if not data:
        return None

    return RuntimeHintDefinition(
        transmit_on_connect=data.get("transmit_on_connect"),
        transmit_on_event=data.get("transmit_on_event"),
        transmit_on_duplicate=data.get("transmit_on_duplicate"),
        metadata=data.get("metadata", {}),
    )


def _load_output(data: dict[str, Any] | None) -> OutputDefinition:
    if not data:
        return OutputDefinition()

    return OutputDefinition(
        mqtt=data.get("mqtt", True),
        api=data.get("api", True),
        storage=data.get("storage", True),
        metadata=data.get("metadata", {}),
    )


def _load_tx(data: dict[str, Any] | None) -> TxDefinition | None:
    if not data:
        return None

    return TxDefinition(
        managed=data.get("managed", False),
        default_value=data.get("default_value"),
        runtime_default=data.get("runtime_default"),
        runtime_default_channel=data.get("runtime_default_channel"),
        required_for_snapshot=data.get("required_for_snapshot", False),
        aggregation_window_seconds=data.get("aggregation_window_seconds"),
        metadata=data.get("metadata", {}),
    )


def _load_constraint(data: dict[str, Any]) -> ConstraintDefinition:
    return ConstraintDefinition(
        name=data.get("name"),
        field=data.get("field"),
        equals=data.get("equals"),
        not_equals=data.get("not_equals"),
        values=data.get("values", []),
        if_dependency=_load_dependency(data.get("if_dependency")),
        requires=_load_dependency(data.get("requires")),
        description=data.get("description"),
        metadata=data.get("metadata", {}),
    )


def _load_context_update(data: dict[str, Any]) -> ContextUpdateDefinition:
    return ContextUpdateDefinition(
        context=data["context"],
        from_field=data.get("from_field"),
        value=data.get("value"),
        metadata=data.get("metadata", {}),
    )


def _load_function_group(data: dict[str, Any]) -> FunctionGroupDefinition:
    return FunctionGroupDefinition(
        name=data["name"],
        title=data["title"],
        direction=data["direction"],
        description=data.get("description"),
        functions=data.get("functions", []),
        metadata=data.get("metadata", {}),
    )


def _load_channel(data: dict[str, Any]) -> ChannelDefinition:
    object_type = data.get("object_type") or data.get("channel_type")

    return ChannelDefinition(
        name=data["name"],
        data_type=data["data_type"],
        semantic_role=data.get("semantic_role"),
        object_type=object_type,
        display_name=data.get("display_name"),
        description=data.get("description"),
        source_key=data.get("source_key"),
        function_group=data.get("function_group"),
        semantic_confidence=data.get("semantic_confidence"),
        semantic_attributes=data.get("semantic_attributes", {}),
        unit=data.get("unit"),
        enum=_load_enum(data.get("enum")),
        ranges=_load_ranges(data.get("ranges")),
        default_value=data.get("default_value"),
        value_resolution=data.get("value_resolution"),
        value_precision=data.get("value_precision"),
        runtime=_load_runtime(data.get("runtime")),
        output=_load_output(data.get("output")),
        tx=_load_tx(data.get("tx")),
        metadata=data.get("metadata", {}),
        channel_type=data.get("channel_type"),
        writable=data.get("writable", False),
        friendly_name=data.get("friendly_name"),
        field_ref=data.get("field_ref"),
        bitfield=_load_field(data["bitfield"])
        if data.get("bitfield")
        else None,
        scale=_load_scale(data.get("scale")),
        depends_on=_load_dependency(data.get("depends_on")),
    )


def _load_message(data: dict[str, Any]) -> MessageDefinition:
    return MessageDefinition(
        name=data["name"],
        data_type=data.get("data_type"),
        semantic_role=data.get("semantic_role"),
        object_type=data.get("object_type"),
        display_name=data.get("display_name"),
        description=data.get("description"),
        source_key=data.get("source_key"),
        function_group=data.get("function_group"),
        semantic_confidence=data.get("semantic_confidence"),
        semantic_attributes=data.get("semantic_attributes", {}),
        unit=data.get("unit"),
        enum=_load_enum(data.get("enum")),
        ranges=_load_ranges(data.get("ranges")),
        default_value=data.get("default_value"),
        value_resolution=data.get("value_resolution"),
        value_precision=data.get("value_precision"),
        runtime=_load_runtime(data.get("runtime")),
        output=_load_output(data.get("output")),
        tx=_load_tx(data.get("tx")),
        metadata=data.get("metadata", {}),
        message_id=data.get("message_id"),
        message_type=data.get("message_type", "command"),
        command_id=data.get("command_id"),
        extended_command_id=data.get("extended_command_id"),
        response_to=data.get("response_to"),
        response_timeout_ms=data.get("response_timeout_ms"),
        request=data.get("request"),
        response=data.get("response"),
        channels=[
            _load_channel(channel)
            for channel in data.get("channels", [])
        ],
        channel_bindings=[
            _load_channel_binding(binding)
            for binding in data.get("channel_bindings", [])
        ],
        depends_on=_load_dependency(data.get("depends_on")),
    )


def _load_field_parts(data: dict[str, Any]) -> list[FieldPartDefinition]:
    if "field_parts" not in data:
        return []
    parts = data["field_parts"]
    if not isinstance(parts, list) or len(parts) < 2:
        raise EEPRegistryError("field_parts requires a list of at least two parts")
    if data.get("field_ref") is not None or data.get("bitfield_ref") is not None:
        raise EEPRegistryError("field_parts is mutually exclusive with field_ref/bitfield_ref")
    result = []
    for part in parts:
        if (not isinstance(part, dict) or set(part) != {"field_ref", "value_offset"}
                or not isinstance(part["field_ref"], str) or not part["field_ref"]
                or type(part["value_offset"]) is not int or part["value_offset"] < 0):
            raise EEPRegistryError("invalid field_parts entry: expected field_ref and value_offset")
        result.append(FieldPartDefinition(**part))
    return result


def _load_channel_binding(data: dict[str, Any]) -> ChannelBindingDefinition:
    field_ref = data.get("field_ref") or data.get("bitfield_ref")

    parts = _load_field_parts(data)
    if field_ref is None and not parts:
        raise EEPRegistryError("Invalid channel binding: missing field_ref or field_parts")

    return ChannelBindingDefinition(
        channel_ref=data["channel_ref"],
        field_ref=field_ref,
        field_parts=parts,
        scale=_load_scale(data.get("scale")),
        enum=_load_enum(data.get("enum")),
        ranges=_load_ranges(data.get("ranges")),
        depends_on=_load_dependency(data.get("depends_on")),
        metadata=data.get("metadata", {}),
        bitfield_ref=data.get("bitfield_ref"),
    )


def _load_message_binding(data: dict[str, Any]) -> MessageBindingDefinition:
    field_ref = data.get("field_ref") or data.get("bitfield_ref")

    parts = _load_field_parts(data)
    if field_ref is None and not parts:
        raise EEPRegistryError("Invalid message binding: missing field_ref or field_parts")

    return MessageBindingDefinition(
        message_ref=data["message_ref"],
        field_ref=field_ref,
        field_parts=parts,
        scale=_load_scale(data.get("scale")),
        enum=_load_enum(data.get("enum")),
        ranges=_load_ranges(data.get("ranges")),
        depends_on=_load_dependency(data.get("depends_on")),
        metadata=data.get("metadata", {}),
        bitfield_ref=data.get("bitfield_ref"),
    )


def _load_telegram_identity(data: dict[str, Any]) -> TelegramIdentity:
    return TelegramIdentity(
        rorg=data["rorg"],
        cmd=data.get("cmd"),
        ecid=data.get("ecid"),
        metadata=data.get("metadata", {}),
    )


def _load_telegram(data: dict[str, Any]) -> TelegramDefinition:
    return TelegramDefinition(
        telegram_type_id=data["telegram_type_id"],
        telegram_id=_load_telegram_identity(data["telegram_id"]),
        direction=data.get("direction"),
        description=data.get("description"),
        fields=[
            _load_field(field, default_source="payload")
            for field in data.get("fields", [])
        ],
        status_fields=[
            _load_field(field, default_source="status")
            for field in data.get("status_fields", [])
        ],
        channel_bindings=[
            _load_channel_binding(binding)
            for binding in data.get("channel_bindings", [])
        ],
        message_bindings=[
            _load_message_binding(binding)
            for binding in data.get("message_bindings", [])
        ],
        constraints=[
            _load_constraint(item)
            for item in data.get("constraints", [])
        ],
        context_updates=[
            _load_context_update(item)
            for item in data.get("context_updates", [])
        ],
        dependencies=_load_dependency_descriptions(
            data.get("dependencies"),
        ),
        metadata=data.get("metadata", {}),
        channels=[
            _load_channel(channel)
            for channel in data.get("channels", [])
        ],
        messages=[
            _load_message(message)
            for message in data.get("messages", [])
        ],
        metadata_channels=[
            _load_channel(channel)
            for channel in data.get("metadata_channels", [])
        ],
        teach_in=data.get("teach_in"),
        security=data.get("security"),
    )


def _resolve_registry_filename(profile: str) -> str:
    """Resolve registry filename for standard and proprietary profiles."""

    normalized = profile.strip()

    if STANDARD_EEP_PATTERN.fullmatch(normalized):
        return f"{normalized.upper()}.json"

    return f"{normalized}.json"


def _resolve_registry_file(eep: str) -> Path:
    """Resolve runtime registry file with optional fallback lookup."""

    registry_path = _registry_path()
    filename = _resolve_registry_filename(eep)

    primary_path = registry_path / filename

    if primary_path.exists():
        return primary_path

    fallback_path = DEFAULT_REGISTRY_PATH / filename

    if fallback_path.exists():
        logger.warning(
            "EEP %s not found in %s, using fallback registry %s",
            eep,
            registry_path,
            fallback_path,
        )

        return fallback_path

    raise EEPRegistryError(
        f"Missing EEP definition: {eep} ({primary_path})"
    )


def _read_eep_definition(eep: str) -> EEPDefinition:
    """Load normalized EEP definition from runtime registry."""

    path = _resolve_registry_file(eep)

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    try:
        definition = EEPDefinition(
            eep=data["eep"],
            rorg=data["rorg"],
            func=data["func"],
            type=data["type"],
            profile_type=data.get("profile_type", "standard"),
            func_description=data.get("func_description"),
            type_description=data.get("type_description"),
            description=data.get("description"),
            source=data.get("source"),
            source_version=data.get("source_version"),
            sources=data.get("sources", []),
            direction=data.get("direction"),
            device_class=data.get("device_class"),
            function_groups=[
                _load_function_group(group)
                for group in data.get("function_groups", [])
            ],
            channels=[
                _load_channel(channel)
                for channel in data.get("channels", [])
            ],
            messages=[
                _load_message(message)
                for message in data.get("messages", [])
            ],
            telegrams=[
                _load_telegram(telegram)
                for telegram in data.get("telegrams", [])
            ],
            dependencies=_load_dependency_descriptions(
                data.get("dependencies"),
            ),
            tx=_load_tx(data.get("tx")),
            metadata=data.get("metadata", {}),
            addressing=data.get("addressing"),
            teach_in_method=data.get("teach_in_method"),
            metadata_channels=[
                _load_channel(channel)
                for channel in data.get("metadata_channels", [])
            ],
            security=data.get("security"),
        )
    except KeyError as exc:
        raise EEPRegistryError(
            f"Invalid EEP registry schema in {path}: missing key {exc}"
        ) from exc
    except TypeError as exc:
        raise EEPRegistryError(
            f"Invalid EEP registry schema in {path}: {exc}"
        ) from exc

    _validate_profile_references(definition, path)

    return definition


def _validate_profile_references(definition: EEPDefinition, path: Path) -> None:
    """Validate local references required by API and runtime consumers."""

    channel_names = {channel.name for channel in definition.channels}
    message_names = {message.name for message in definition.messages}

    from enocean_mqtt.eep.field_parts import validate_telegram_composites

    for telegram in definition.telegrams:
        try:
            validate_telegram_composites(telegram)
        except ValueError as exc:
            raise EEPRegistryError(f"Invalid EEP registry schema in {path}: {exc}") from exc
        field_names = {field.name for field in telegram.fields}
        field_names.update(field.name for field in telegram.status_fields)

        for binding in telegram.channel_bindings:
            if binding.channel_ref not in channel_names:
                raise EEPRegistryError(
                    "Invalid EEP registry schema in "
                    f"{path}: unknown channel_ref {binding.channel_ref!r} "
                    f"in telegram {telegram.telegram_type_id!r}"
                )

            if not binding.field_parts and binding.field_ref not in field_names:
                raise EEPRegistryError(
                    "Invalid EEP registry schema in "
                    f"{path}: unknown field_ref {binding.field_ref!r} "
                    f"in telegram {telegram.telegram_type_id!r}"
                )

        for message_binding in telegram.message_bindings:
            if message_binding.message_ref not in message_names:
                raise EEPRegistryError(
                    "Invalid EEP registry schema in "
                    f"{path}: unknown message_ref {message_binding.message_ref!r} "
                    f"in telegram {telegram.telegram_type_id!r}"
                )

            if not message_binding.field_parts and message_binding.field_ref not in field_names:
                raise EEPRegistryError(
                    "Invalid EEP registry schema in "
                    f"{path}: unknown field_ref {message_binding.field_ref!r} "
                    f"in telegram {telegram.telegram_type_id!r}"
                )
