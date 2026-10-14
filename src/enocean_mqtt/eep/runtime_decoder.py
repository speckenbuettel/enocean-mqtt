"""Registry-driven runtime decoder for Registry v3 EEP definitions.

The decoder treats the Registry v3 object model as the runtime contract:

- telegram ``fields`` / ``status_fields`` are decoded into raw field maps,
- ``channel_bindings`` map raw fields to semantic RX channels,
- binding-level ``depends_on`` conditions decide which semantic value is active,
- ``constraints`` and ``context_updates`` are evaluated per telegram.

The remaining legacy channel path is kept only as a transitional fallback for
older registry files that do not yet provide telegram-local channel bindings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from enocean_mqtt.eep.decoder import (
    EEPDecodeError,
    apply_linear_scale,
    decode_field,
    parse_payload_hex,
)
from enocean_mqtt.eep.field_parts import validate_telegram_composites
from enocean_mqtt.eep.models import (
    ChannelBindingDefinition,
    ChannelDefinition,
    ConstraintDefinition,
    DependencyDefinition,
    EEPDefinition,
    FieldDefinition,
    LinearScale,
    TelegramDefinition,
    ValueMapping,
    ValueRangeMapping,
)

DecodedValue = bool | float | int | str


@dataclass(slots=True)
class RuntimeDecodeContext:
    """Runtime context used for dependency-aware decoding."""

    payload: bytes
    status: bytes | None = None
    telegram_id: str | None = None
    rorg: str | None = None
    fields: dict[str, int] = field(default_factory=dict)
    status_fields: dict[str, int] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeDecodedChannel:
    """Decoded channel including dependency and range resolution metadata."""

    name: str
    value: DecodedValue
    raw_value: int
    data_type: str
    definition: ChannelDefinition
    unit: str | None = None
    semantic_role: str | None = None
    object_type: str | None = None
    range_label: str | None = None
    enum_encoded: bool = False
    meaning: str | None = None

    @property
    def published_value(self) -> DecodedValue:
        """Enum state uses its numeric code; internal semantic decoding is retained."""
        return self.raw_value if self.enum_encoded or self.data_type == "enum" else self.value


@dataclass(slots=True)
class RuntimeDecodedTelegram:
    """Decoded telegram selected from a telegram-centric runtime registry."""

    eep: str
    telegram_type_id: str | None
    values: dict[str, RuntimeDecodedChannel]
    fields: dict[str, int]
    status_fields: dict[str, int]


def build_runtime_context(
    payload_hex: str,
    telegram: TelegramDefinition | None = None,
    status_hex: str | None = None,
    telegram_id: str | None = None,
    rorg: str | None = None,
    external_context: dict[str, Any] | None = None,
) -> RuntimeDecodeContext:
    """Build field maps required for dependency-aware runtime decoding."""

    payload = parse_payload_hex(payload_hex)
    status = parse_payload_hex(status_hex) if status_hex else None
    context = dict(external_context or {})
    runtime_rorg = _normalize_rorg(rorg or context.get("rorg"))

    decode_context = RuntimeDecodeContext(
        payload=payload,
        status=status,
        telegram_id=telegram_id,
        rorg=runtime_rorg,
        context=context,
    )

    if telegram is None:
        return decode_context

    try:
        validate_telegram_composites(telegram)
    except ValueError as exc:
        raise EEPDecodeError(str(exc)) from exc

    for field_definition in telegram.fields:
        _extract_named_field(field_definition, payload, decode_context.fields)

    if status is not None:
        for field_definition in telegram.status_fields:
            _extract_named_field(field_definition, status, decode_context.status_fields)

    # Transitional support for older registry files. Registry v3 stores
    # metadata as normal channels or raw fields, not telegram.metadata_channels.
    for channel in telegram.metadata_channels:
        if channel.bitfield is not None:
            _extract_named_field(channel.bitfield, payload, decode_context.fields)

    _apply_context_updates(telegram, decode_context)

    return decode_context


def dependency_matches(
    dependency: DependencyDefinition | None,
    decode_context: RuntimeDecodeContext,
) -> bool:
    """Evaluate a registry dependency against a runtime decode context."""

    if dependency is None:
        return True

    value = _dependency_value(dependency, decode_context)

    if dependency.equals is not None and value != dependency.equals:
        return False

    if dependency.not_equals is not None and value == dependency.not_equals:
        return False

    if dependency.values and value not in dependency.values:
        return False

    return True


def select_telegram(
    eep_definition: EEPDefinition,
    payload_hex: str,
    status_hex: str | None = None,
    telegram_id: str | None = None,
    rorg: str | None = None,
    external_context: dict[str, Any] | None = None,
) -> tuple[TelegramDefinition | None, RuntimeDecodeContext]:
    """Select the active RX telegram definition for a payload."""

    if not eep_definition.telegrams:
        return None, build_runtime_context(
            payload_hex=payload_hex,
            status_hex=status_hex,
            telegram_id=telegram_id,
            rorg=rorg,
            external_context=external_context,
        )

    candidate_errors: list[str] = []
    incoming_rorg = (
        _normalize_rorg(rorg or (external_context or {}).get("rorg"))
        or eep_definition.rorg.upper()
    )

    for telegram in eep_definition.telegrams:
        if telegram.direction not in (None, "rx"):
            continue

        if telegram_id and telegram.telegram_type_id != telegram_id:
            continue

        # Reject other radio telegram types before reading their payload fields.
        # A short D5/F6 payload cannot be interpreted using A5 field offsets.
        if telegram.telegram_id.rorg.upper() != incoming_rorg:
            candidate_errors.append(f"{telegram.telegram_type_id}: identity mismatch")
            continue

        decode_context = build_runtime_context(
            payload_hex=payload_hex,
            telegram=telegram,
            status_hex=status_hex,
            telegram_id=telegram_id,
            rorg=rorg,
            external_context=external_context,
        )

        if not _telegram_identity_matches(telegram, eep_definition, decode_context):
            candidate_errors.append(f"{telegram.telegram_type_id}: identity mismatch")
            continue

        constraints_ok, reason = _constraints_match(telegram.constraints, decode_context)

        if not constraints_ok:
            candidate_errors.append(f"{telegram.telegram_type_id}: {reason}")
            continue

        return telegram, decode_context

    if telegram_id:
        detail = f" for telegram_id {telegram_id!r}"
    else:
        detail = ""

    if candidate_errors:
        detail = f"{detail}: " + "; ".join(candidate_errors)

    raise EEPDecodeError(
        f"No matching RX telegram definition found for EEP {eep_definition.eep}{detail}"
    )


def decode_runtime_with_definition(
    eep_definition: EEPDefinition,
    payload_hex: str,
    status_hex: str | None = None,
    telegram_id: str | None = None,
    rorg: str | None = None,
    external_context: dict[str, Any] | None = None,
) -> RuntimeDecodedTelegram:
    """Decode an EEP payload using telegram-centric runtime registry data."""

    telegram, decode_context = select_telegram(
        eep_definition=eep_definition,
        payload_hex=payload_hex,
        status_hex=status_hex,
        telegram_id=telegram_id,
        rorg=rorg,
        external_context=external_context,
    )

    decoded_values: dict[str, RuntimeDecodedChannel] = {}

    if telegram is not None and telegram.channel_bindings:
        for binding in telegram.channel_bindings:
            decoded = decode_runtime_binding(eep_definition, binding, decode_context)
            if decoded is not None:
                decoded_values[decoded.name] = decoded
    else:
        for channel in _active_legacy_channels(eep_definition, telegram, decode_context):
            decoded = decode_runtime_channel(channel, decode_context)
            if decoded is not None:
                decoded_values[channel.name] = decoded

    return RuntimeDecodedTelegram(
        eep=eep_definition.eep,
        telegram_type_id=telegram.telegram_type_id if telegram else None,
        values=decoded_values,
        fields=decode_context.fields,
        status_fields=decode_context.status_fields,
    )


def decode_runtime_binding(
    eep_definition: EEPDefinition,
    binding: ChannelBindingDefinition,
    decode_context: RuntimeDecodeContext,
) -> RuntimeDecodedChannel | None:
    """Decode one semantic channel via a telegram-specific binding."""

    if not dependency_matches(binding.depends_on, decode_context):
        return None

    channel = _channel_by_name(eep_definition, binding.channel_ref)
    if channel is None:
        raise EEPDecodeError(f"Unknown channel_ref in binding: {binding.channel_ref}")

    raw_value: int | None
    if binding.field_parts:
        raw_value = 0
        for part in binding.field_parts:
            part_value = decode_context.fields.get(part.field_ref)
            if part_value is None:
                raise EEPDecodeError(f"Unknown field_parts field_ref: {part.field_ref}")
            raw_value |= part_value << part.value_offset
    else:
        raw_value = _field_value(binding.field_ref, decode_context)

    if raw_value is None:
        raise EEPDecodeError(f"Unknown field_ref in binding: {binding.field_ref}")

    value, unit, range_label = _resolve_value(
        raw_value=raw_value,
        data_type=channel.data_type,
        unit=channel.unit,
        scale=binding.scale,
        enum=binding.enum or channel.enum,
        ranges=binding.ranges or channel.ranges,
        decode_context=decode_context,
    )
    value = _apply_precision(value, channel.value_precision)
    output_name = _output_name(channel)

    return RuntimeDecodedChannel(
        name=output_name,
        value=value,
        raw_value=raw_value,
        data_type=channel.data_type,
        definition=channel,
        unit=unit,
        semantic_role=channel.semantic_role,
        object_type=channel.object_type or channel.channel_type,
        range_label=range_label,
        enum_encoded=bool(binding.enum or channel.enum),
        meaning=next((item.label for item in (binding.enum or channel.enum)
                      if item.value == raw_value), None),
    )


def decode_runtime_channel(
    channel: ChannelDefinition,
    decode_context: RuntimeDecodeContext,
) -> RuntimeDecodedChannel | None:
    """Decode one legacy channel if its dependencies are active."""

    if channel.bitfield is None:
        return None

    if not dependency_matches(channel.depends_on, decode_context):
        return None

    source = (
        decode_context.status
        if channel.bitfield.source == "status"
        else decode_context.payload
    )

    if source is None:
        return None

    raw_value = decode_field(channel.bitfield, source)
    value, unit, range_label = _resolve_value(
        raw_value=raw_value,
        data_type=channel.data_type,
        unit=channel.unit,
        scale=channel.scale,
        enum=channel.enum,
        ranges=channel.ranges,
        decode_context=decode_context,
    )
    value = _apply_precision(value, channel.value_precision)

    return RuntimeDecodedChannel(
        name=_output_name(channel),
        value=value,
        raw_value=raw_value,
        data_type=channel.data_type,
        definition=channel,
        unit=unit,
        semantic_role=channel.semantic_role,
        object_type=channel.object_type or channel.channel_type,
        range_label=range_label,
        enum_encoded=bool(channel.enum),
        meaning=next((item.label for item in channel.enum if item.value == raw_value), None),
    )


def _resolve_value(
    *,
    raw_value: int,
    data_type: str,
    unit: str | None,
    scale: LinearScale | None,
    enum: list[ValueMapping],
    ranges: list[ValueRangeMapping],
    decode_context: RuntimeDecodeContext,
) -> tuple[DecodedValue, str | None, str | None]:
    resolved_range = _select_range(ranges, raw_value, decode_context)
    range_label = None

    if resolved_range is not None:
        range_label = resolved_range.label or resolved_range.description
        unit = resolved_range.unit or unit

    if enum:
        mapped = _map_enum_value(enum, raw_value)
        return mapped, unit, range_label

    if scale is not None:
        return apply_linear_scale(raw_value, scale), unit, range_label

    # Transitional support for legacy raw ranges that carried their own scale.
    if resolved_range is not None and resolved_range.scale is not None:
        return apply_linear_scale(raw_value, resolved_range.scale), unit, range_label

    if data_type == "boolean":
        return bool(raw_value), unit, range_label

    return raw_value, unit, range_label


def _map_enum_value(
    enum: list[ValueMapping],
    raw_value: int,
) -> DecodedValue:
    for item in enum:
        if item.value != raw_value:
            continue

        if item.semantic_value is not None:
            return item.semantic_value

        return item.label

    return raw_value


def _apply_precision(
    value: DecodedValue,
    precision: int | None,
) -> DecodedValue:
    if precision is None or not isinstance(value, float):
        return value

    return round(value, precision)


def _output_name(channel: ChannelDefinition) -> str:
    display_name = (channel.display_name or channel.friendly_name or "").strip()
    return display_name or channel.name


def _channel_by_name(eep_definition: EEPDefinition, name: str) -> ChannelDefinition | None:
    for channel in eep_definition.channels:
        if channel.name == name:
            return channel

    # Transitional support for old registry files.
    for channel in eep_definition.metadata_channels:
        if channel.name == name:
            return channel

    return None


def _active_legacy_channels(
    eep_definition: EEPDefinition,
    telegram: TelegramDefinition | None,
    decode_context: RuntimeDecodeContext,
) -> list[ChannelDefinition]:
    if telegram is None:
        return eep_definition.channels

    channels: list[ChannelDefinition] = []
    channels.extend(telegram.channels)

    for message in telegram.messages:
        if dependency_matches(message.depends_on, decode_context):
            channels.extend(message.channels)

    if not channels:
        channels.extend(eep_definition.channels)

    return channels


def _select_range(
    ranges: list[ValueRangeMapping],
    raw_value: int,
    decode_context: RuntimeDecodeContext,
) -> ValueRangeMapping | None:
    for value_range in ranges:
        range_min = value_range.raw_min if value_range.raw_min is not None else value_range.min
        range_max = value_range.raw_max if value_range.raw_max is not None else value_range.max

        if range_min is not None and raw_value < range_min:
            continue

        if range_max is not None and raw_value > range_max:
            continue

        if dependency_matches(value_range.depends_on, decode_context):
            return value_range

    return None


def _extract_named_field(
    field_definition: FieldDefinition,
    source: bytes,
    target: dict[str, int],
) -> None:
    if not field_definition.name:
        return

    target[field_definition.name] = decode_field(field_definition, source)


def _field_value(
    field_ref: str | None,
    decode_context: RuntimeDecodeContext,
) -> int | None:
    if field_ref is None:
        return None
    raw_value = decode_context.fields.get(field_ref)

    if raw_value is None:
        raw_value = decode_context.status_fields.get(field_ref)

    return raw_value


def _dependency_value(
    dependency: DependencyDefinition,
    decode_context: RuntimeDecodeContext,
) -> Any:
    if dependency.source == "field":
        return decode_context.fields.get(dependency.field)

    if dependency.source == "status_field":
        return decode_context.status_fields.get(dependency.field)

    if dependency.source == "context":
        return decode_context.context.get(dependency.field)

    if dependency.source == "telegram_id":
        return decode_context.telegram_id

    raise AssertionError(f"Unsupported dependency source: {dependency.source}")


def _constraints_match(
    constraints: list[ConstraintDefinition],
    decode_context: RuntimeDecodeContext,
) -> tuple[bool, str | None]:
    for constraint in constraints:
        if constraint.if_dependency is not None and not dependency_matches(
            constraint.if_dependency,
            decode_context,
        ):
            continue

        if constraint.requires is not None and not dependency_matches(
            constraint.requires,
            decode_context,
        ):
            name = constraint.name or constraint.field or "constraint"
            return False, f"{name} requires unmet dependency"

        if constraint.field is None:
            continue

        value = _field_value(constraint.field, decode_context)

        if constraint.equals is not None and value != constraint.equals:
            return False, (
                f"constraint {constraint.field!r} expected "
                f"{constraint.equals!r}, got {value!r}"
            )

        if constraint.not_equals is not None and value == constraint.not_equals:
            return False, (
                f"constraint {constraint.field!r} must not equal "
                f"{constraint.not_equals!r}"
            )

        if constraint.values and value not in constraint.values:
            return False, (
                f"constraint {constraint.field!r} expected one of "
                f"{constraint.values!r}, got {value!r}"
            )

    return True, None


def _apply_context_updates(
    telegram: TelegramDefinition,
    decode_context: RuntimeDecodeContext,
) -> None:
    for update in telegram.context_updates:
        value: Any

        if update.from_field is not None:
            value = _field_value(update.from_field, decode_context)
        else:
            value = update.value

        if value is not None:
            decode_context.context[update.context] = value


def _telegram_identity_matches(
    telegram: TelegramDefinition,
    eep_definition: EEPDefinition,
    decode_context: RuntimeDecodeContext,
) -> bool:
    expected_rorg = (
        decode_context.rorg.upper()
        if decode_context.rorg is not None
        else eep_definition.rorg.upper()
    )

    if telegram.telegram_id.rorg.upper() != expected_rorg:
        return False

    if telegram.telegram_id.cmd is not None:
        cmd_value = decode_context.fields.get("CMD") or decode_context.fields.get("cmd")

        if cmd_value is not None and str(cmd_value) != str(telegram.telegram_id.cmd):
            return False

    if telegram.telegram_id.ecid is not None:
        ecid_value = decode_context.fields.get("ECID") or decode_context.fields.get("ecid")

        if ecid_value is not None and str(ecid_value) != str(telegram.telegram_id.ecid):
            return False

    return True


def _normalize_rorg(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().upper()

    return normalized or None
