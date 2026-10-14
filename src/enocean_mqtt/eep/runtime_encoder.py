"""Registry-driven runtime encoder for Registry v3 EEP definitions.

The encoder translates a semantic snapshot into one or more TX telegrams using
the same Registry v3 binding model that the runtime decoder uses in the
opposite direction.

Input adapters may build the semantic snapshot from virtual-device channels,
physical-device messages, API requests, replay data, or cached TX state. The
encoder itself only knows semantic object names, telegram fields, bindings,
scales, enum mappings and binding dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from enocean_mqtt.eep.field_parts import (
    Binding as _Binding,
    composite_fields,
    validate_telegram_composites,
)
from enocean_mqtt.eep.models import (
    ChannelBindingDefinition,
    ChannelDefinition,
    DependencyDefinition,
    EEPDefinition,
    FieldDefinition,
    LinearScale,
    MessageBindingDefinition,
    MessageDefinition,
    SemanticValue,
    TelegramDefinition,
    ValueMapping,
)
from enocean_mqtt.eep.semantic_mapping import semantic_value_matches_label

SemanticSource = Literal["channels", "messages"]
SemanticSnapshot = dict[str, Any]


class EEPEncodeError(ValueError):
    """Raised when a semantic snapshot cannot be encoded."""


@dataclass(slots=True)
class EncodedRuntimeTelegram:
    """Encoded TX telegram payload produced from a semantic snapshot."""

    rorg: str
    data: str
    status: str
    telegram_type_id: str | None


_MISSING = object()


def encode_semantic_snapshot(
    *,
    eep_definition: EEPDefinition,
    snapshot: SemanticSnapshot,
    source: SemanticSource,
    telegram_type_id: str | None = None,
    trigger_refs: set[str] | None = None,
) -> EncodedRuntimeTelegram:
    """Encode a semantic snapshot into the first matching TX telegram."""

    encoded = encode_semantic_snapshot_all(
        eep_definition=eep_definition,
        snapshot=snapshot,
        source=source,
        telegram_type_id=telegram_type_id,
        trigger_refs=trigger_refs,
    )

    return encoded[0]


def encode_semantic_snapshot_all(
    *,
    eep_definition: EEPDefinition,
    snapshot: SemanticSnapshot,
    source: SemanticSource,
    telegram_type_id: str | None = None,
    trigger_refs: set[str] | None = None,
) -> list[EncodedRuntimeTelegram]:
    """Encode a semantic snapshot into all matching Registry v3 TX telegrams.

    ``source`` selects which semantic object collection is used:

    - ``channels`` for virtual-device snapshots,
    - ``messages`` for physical-device TX messages and commands.

    Every candidate telegram is evaluated independently. A telegram is emitted
    when the snapshot contains at least one explicit binding for that telegram
    and all active required/default values can be resolved.

    ``trigger_refs`` can restrict emission to telegrams whose semantic bindings
    were updated by the current input event. This allows a complete cached
    snapshot to provide required context while only the affected telegram types
    are sent.
    """

    errors: list[str] = []
    encoded_telegrams: list[EncodedRuntimeTelegram] = []

    for telegram in _candidate_tx_telegrams(eep_definition, source, telegram_type_id):
        try:
            encoded_telegrams.append(
                _encode_telegram(
                    eep_definition=eep_definition,
                    telegram=telegram,
                    snapshot=snapshot,
                    source=source,
                    trigger_refs=trigger_refs,
                )
            )
        except EEPEncodeError as exc:
            errors.append(f"{telegram.telegram_type_id}: {exc}")

    if encoded_telegrams:
        return encoded_telegrams

    detail = "; ".join(errors) if errors else "no matching TX telegram"
    raise EEPEncodeError(
        f"Cannot encode {source} snapshot for EEP {eep_definition.eep}: {detail}"
    )


def _candidate_tx_telegrams(
    eep_definition: EEPDefinition,
    source: SemanticSource,
    telegram_type_id: str | None,
) -> list[TelegramDefinition]:
    candidates: list[TelegramDefinition] = []

    for telegram in eep_definition.telegrams:
        if telegram.direction not in (None, "tx"):
            continue

        if telegram_type_id is not None and telegram.telegram_type_id != telegram_type_id:
            continue

        if source == "channels" and telegram.channel_bindings:
            candidates.append(telegram)
        elif source == "messages" and telegram.message_bindings:
            candidates.append(telegram)

    return candidates


def _encode_telegram(
    *,
    eep_definition: EEPDefinition,
    telegram: TelegramDefinition,
    snapshot: SemanticSnapshot,
    source: SemanticSource,
    trigger_refs: set[str] | None,
) -> EncodedRuntimeTelegram:
    try:
        validate_telegram_composites(telegram)
    except ValueError as exc:
        raise EEPEncodeError(str(exc)) from exc
    telegram_rorg = telegram.telegram_id.rorg.upper()
    payload = bytearray(_payload_size_bytes(telegram, telegram_rorg))
    raw_fields: dict[str, int] = {}
    encoded_fields: set[str] = set()

    _apply_field_constants_and_defaults(telegram, raw_fields)

    bindings = _bindings_for_source(telegram, source)
    if trigger_refs is not None and not any(
        _semantic_ref(binding, source) in trigger_refs for binding in bindings
    ):
        raise EEPEncodeError("snapshot did not trigger this TX telegram")

    explicit_bindings = [
        binding for binding in bindings if _semantic_ref(binding, source) in snapshot
    ]

    if not explicit_bindings:
        raise EEPEncodeError("snapshot did not match any TX binding")

    # First encode explicit values. This infers selector dependencies such as
    # SPS=1 for A5-20-06 temperature_setpoint.
    for binding in explicit_bindings:
        _encode_binding(
            eep_definition=eep_definition,
            telegram=telegram,
            binding=binding,
            snapshot=snapshot,
            source=source,
            explicit=True,
            raw_fields=raw_fields,
            encoded_fields=encoded_fields,
        )

    # Then fill active managed/default bindings and check required active values.
    for binding in bindings:
        if _semantic_ref(binding, source) in snapshot:
            continue

        if not _dependency_satisfied(binding.depends_on, raw_fields):
            continue

        _encode_binding(
            eep_definition=eep_definition,
            telegram=telegram,
            binding=binding,
            snapshot=snapshot,
            source=source,
            explicit=False,
            raw_fields=raw_fields,
            encoded_fields=encoded_fields,
        )

    if not encoded_fields:
        raise EEPEncodeError("snapshot did not match any TX binding")

    for field in telegram.fields:
        if field.name in raw_fields:
            _set_bits(payload, field.offset, field.size, raw_fields[field.name])

    return EncodedRuntimeTelegram(
        rorg=telegram_rorg,
        data=payload.hex(" ").upper(),
        status=_encode_status(telegram),
        telegram_type_id=telegram.telegram_type_id,
    )


def _encode_status(telegram: TelegramDefinition) -> str:
    """Encode declared ERP1 status constants without changing payload offsets."""
    status = bytearray(1)
    occupied: set[int] = set()
    for field in telegram.status_fields:
        positions = set(range(field.offset, field.offset + field.size))
        if field.size <= 0 or not positions <= set(range(8)):
            raise EEPEncodeError(f"invalid status field bounds: {field.name}")
        if occupied & positions:
            raise EEPEncodeError(f"overlapping status field: {field.name}")
        occupied.update(positions)
        value = field.constant
        if value is None:
            value = field.default_value
        if value is None and field.reserved:
            value = 0
        if value is not None:
            _set_bits(status, field.offset, field.size, _to_int(value))
    return status.hex().upper()


def _encode_binding(
    *,
    eep_definition: EEPDefinition,
    telegram: TelegramDefinition,
    binding: _Binding,
    snapshot: SemanticSnapshot,
    source: SemanticSource,
    explicit: bool,
    raw_fields: dict[str, int],
    encoded_fields: set[str],
) -> None:
    semantic_ref = _semantic_ref(binding, source)
    semantic_definition = _semantic_definition(eep_definition, semantic_ref, source)

    if semantic_definition is None:
        raise EEPEncodeError(f"unknown semantic object: {semantic_ref}")

    if explicit:
        _apply_dependency_for_explicit_value(binding.depends_on, raw_fields)
    elif not _dependency_satisfied(binding.depends_on, raw_fields):
        return

    value = _snapshot_value(
        semantic_ref=semantic_ref,
        semantic_definition=semantic_definition,
        snapshot=snapshot,
    )

    if value is _MISSING:
        if _is_required_for_snapshot(semantic_definition):
            raise EEPEncodeError(f"missing required value: {semantic_ref}")
        return

    parts = composite_fields(binding, telegram) if binding.field_parts else []
    field = (FieldDefinition(name=semantic_ref, offset=0,
                             size=sum(part.size for part in parts), data_type="integer")
             if parts else _field_for_binding(telegram, binding))
    enum = binding.enum or semantic_definition.enum
    raw_value = _encode_semantic_value(
        value=value,
        binding=binding,
        enum=enum,
        field=field,
        semantic_ref=semantic_ref,
    )
    if parts:
        if not 0 <= raw_value < (1 << field.size):
            raise EEPEncodeError(f"composite value {raw_value} exceeds width {field.size}")
        for part, target in zip(binding.field_parts, parts, strict=True):
            piece = (raw_value >> part.value_offset) & ((1 << target.size) - 1)
            if ((target.raw_min is not None and piece < target.raw_min)
                    or (target.raw_max is not None and piece > target.raw_max)):
                raise EEPEncodeError(f"composite part outside raw range: {target.name}")
            _set_raw_field(raw_fields, target.name, piece)
            encoded_fields.add(target.name)
    else:
        _set_raw_field(raw_fields, field.name, raw_value)
        encoded_fields.add(field.name)


def _bindings_for_source(
    telegram: TelegramDefinition,
    source: SemanticSource,
) -> list[_Binding]:
    if source == "channels":
        return list(telegram.channel_bindings)

    return list(telegram.message_bindings)


def _semantic_ref(binding: _Binding, source: SemanticSource) -> str:
    if source == "channels":
        return _as_channel_binding(binding).channel_ref

    return _as_message_binding(binding).message_ref


def _as_channel_binding(binding: _Binding) -> ChannelBindingDefinition:
    if not isinstance(binding, ChannelBindingDefinition):
        raise EEPEncodeError("expected channel binding")

    return binding


def _as_message_binding(binding: _Binding) -> MessageBindingDefinition:
    if not isinstance(binding, MessageBindingDefinition):
        raise EEPEncodeError("expected message binding")

    return binding


def _semantic_definition(
    eep_definition: EEPDefinition,
    semantic_ref: str,
    source: SemanticSource,
) -> ChannelDefinition | MessageDefinition | None:
    collection = eep_definition.channels if source == "channels" else eep_definition.messages

    for semantic_definition in collection:
        if semantic_definition.name == semantic_ref:
            return semantic_definition

    return None


def _snapshot_value(
    *,
    semantic_ref: str,
    semantic_definition: ChannelDefinition | MessageDefinition,
    snapshot: SemanticSnapshot,
) -> Any:
    if semantic_ref in snapshot:
        return snapshot[semantic_ref]

    if semantic_definition.tx is not None:
        if semantic_definition.tx.default_value is not None:
            return semantic_definition.tx.default_value

    if semantic_definition.default_value is not None:
        return semantic_definition.default_value

    return _MISSING


def _is_required_for_snapshot(
    semantic_definition: ChannelDefinition | MessageDefinition,
) -> bool:
    return (
        semantic_definition.tx is not None
        and semantic_definition.tx.required_for_snapshot
    )


def _apply_dependency_for_explicit_value(
    dependency: DependencyDefinition | None,
    raw_fields: dict[str, int],
) -> None:
    if dependency is None:
        return

    if dependency.source != "field":
        raise EEPEncodeError(
            f"unsupported TX dependency source: {dependency.source}"
        )

    if dependency.equals is not None:
        _set_raw_field(raw_fields, dependency.field, _to_int(dependency.equals))
        return

    if len(dependency.values) == 1:
        _set_raw_field(raw_fields, dependency.field, _to_int(dependency.values[0]))
        return

    if not _dependency_satisfied(dependency, raw_fields):
        raise EEPEncodeError(
            f"cannot infer TX dependency for field {dependency.field!r}"
        )


def _dependency_satisfied(
    dependency: DependencyDefinition | None,
    raw_fields: dict[str, int],
) -> bool:
    if dependency is None:
        return True

    if dependency.source != "field":
        return False

    if dependency.field not in raw_fields:
        return False

    value = raw_fields[dependency.field]

    if dependency.equals is not None and value != _to_int(dependency.equals):
        return False

    if dependency.not_equals is not None and value == _to_int(dependency.not_equals):
        return False

    if dependency.values and value not in {_to_int(item) for item in dependency.values}:
        return False

    return True


def _encode_semantic_value(
    *,
    value: Any,
    binding: _Binding,
    enum: list[ValueMapping],
    field: FieldDefinition,
    semantic_ref: str,
) -> int:
    if enum:
        return _encode_enum_value(enum, value, semantic_ref, strict=bool(binding.field_parts))

    if binding.scale is not None:
        return _encode_linear_scaled_value(binding.scale, value, strict=bool(binding.field_parts))

    if field.data_type == "boolean":
        return int(_to_bool(value))

    if binding.field_parts:
        return _to_composite_int(value)
    return _to_int(value)


def _to_composite_int(value: Any) -> int:
    try:
        raw = int(value)
        if not isinstance(value, (int, str)) and value != raw:
            raise ValueError("fractional value")
    except (ValueError, TypeError, OverflowError) as exc:
        raise EEPEncodeError(f"composite value {value!r} must be an integer") from exc
    return raw


def _encode_enum_value(
    enum: list[ValueMapping],
    value: Any,
    semantic_ref: str,
    *,
    strict: bool = False,
) -> int:
    candidates = {
        str(value),
        _normalized_scalar(value),
        _normalized_scalar(value).strip().lower(),
    }

    for item in enum:
        allowed = {
            str(item.value),
            _normalized_scalar(item.value),
            _normalized_scalar(item.value).strip().lower(),
            item.label,
            item.label.strip().lower(),
        }

        if item.semantic_value is not None:
            allowed.update(
                {
                    str(item.semantic_value),
                    _normalized_scalar(item.semantic_value),
                    _normalized_scalar(item.semantic_value).strip().lower(),
                }
            )

        if candidates & allowed:
            return _to_composite_int(item.value) if strict else _to_int(item.value)

    for item in enum:
        if semantic_value_matches_label(value, item.label):
            return _to_composite_int(item.value) if strict else _to_int(item.value)

    raise EEPEncodeError(f"value {value!r} not allowed for {semantic_ref}")


def _encode_linear_scaled_value(scale: LinearScale, value: Any, *, strict: bool = False) -> int:
    try:
        physical = float(value)
    except (TypeError, ValueError) as exc:
        raise EEPEncodeError(f"value {value!r} cannot be converted to float") from exc

    if strict and (not math.isfinite(physical)
                   or not min(scale.scale_min, scale.scale_max) <= physical
                   <= max(scale.scale_min, scale.scale_max)):
        raise EEPEncodeError(f"composite value {value!r} outside scale range")
    if scale.scale_min == scale.scale_max:
        raise EEPEncodeError("invalid scale: scale_min equals scale_max")

    ratio = (physical - scale.scale_min) / (scale.scale_max - scale.scale_min)
    raw = round(scale.raw_min + ratio * (scale.raw_max - scale.raw_min))
    clamped = max(min(raw, scale.raw_max), scale.raw_min)

    return int(clamped)


def _apply_field_constants_and_defaults(
    telegram: TelegramDefinition,
    raw_fields: dict[str, int],
) -> None:
    for field in telegram.fields:
        if field.constant is not None:
            _set_raw_field(raw_fields, field.name, _to_int(field.constant))
        elif field.default_value is not None:
            _set_raw_field(raw_fields, field.name, _to_int(field.default_value))
        elif field.reserved:
            _set_raw_field(raw_fields, field.name, 0)


def _field_for_binding(telegram: TelegramDefinition, binding: _Binding) -> FieldDefinition:
    for field in telegram.fields:
        if field.name == binding.field_ref:
            return field

    raise EEPEncodeError(f"TX field {binding.field_ref!r} not found")


def _set_raw_field(raw_fields: dict[str, int], field_name: str, value: int) -> None:
    existing = raw_fields.get(field_name)

    if existing is not None and existing != value:
        raise EEPEncodeError(
            f"conflicting raw value for field {field_name!r}: {existing} != {value}"
        )

    raw_fields[field_name] = value


def _payload_size_bytes(telegram: TelegramDefinition, rorg: str) -> int:
    if rorg in {"F6", "D5"}:
        return 1

    if rorg == "A5":
        return 4

    max_bit = 0

    for field in telegram.fields:
        max_bit = max(max_bit, field.offset + field.size)

    return max(1, (max_bit + 7) // 8)


def _set_bits(
    payload: bytearray,
    bit_offset: int,
    bit_size: int,
    value: int,
) -> None:
    if bit_size <= 0:
        raise EEPEncodeError("bit_size must be positive")

    max_value = (1 << bit_size) - 1

    if value < 0 or value > max_value:
        raise EEPEncodeError(f"value {value} exceeds field width {bit_size}")

    total_bits = len(payload) * 8
    lsb_index = bit_offset + bit_size - 1

    if lsb_index >= total_bits:
        raise EEPEncodeError(
            f"field outside payload: offset={bit_offset} size={bit_size}"
        )

    for position in range(bit_size):
        source_bit = bit_size - 1 - position
        target_bit = bit_offset + position
        byte_index = target_bit // 8
        bit_index = 7 - (target_bit % 8)
        bit_value = (value >> source_bit) & 0x01

        if bit_value:
            payload[byte_index] |= 1 << bit_index
        else:
            payload[byte_index] &= ~(1 << bit_index)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()

    if normalized in {"true", "1", "yes", "on"}:
        return True

    if normalized in {"false", "0", "no", "off"}:
        return False

    raise EEPEncodeError(f"value {value!r} cannot be converted to bool")


def _to_int(value: SemanticValue | Any) -> int:
    if isinstance(value, bool):
        return int(value)

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EEPEncodeError(f"value {value!r} cannot be converted to int") from exc


def _normalized_scalar(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value)
