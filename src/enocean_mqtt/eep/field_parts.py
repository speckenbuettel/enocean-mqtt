"""Declarative unsigned raw-value composition shared by runtime and validation."""

from __future__ import annotations

import math

from enocean_mqtt.eep.models import (
    ChannelBindingDefinition,
    FieldDefinition,
    MessageBindingDefinition,
    TelegramDefinition,
)

Binding = ChannelBindingDefinition | MessageBindingDefinition


def composite_fields(binding: Binding, telegram: TelegramDefinition) -> list[FieldDefinition]:
    """Resolve and validate a dense, non-overlapping unsigned raw value."""
    if binding.field_ref is not None or binding.bitfield_ref is not None:
        raise ValueError("field_parts is mutually exclusive with field_ref/bitfield_ref")
    if len(binding.field_parts) < 2:
        raise ValueError("field_parts requires at least two parts")
    fields: list[FieldDefinition] = []
    used_names: set[str] = set()
    intervals: list[tuple[int, int]] = []
    for part in binding.field_parts:
        if type(part.value_offset) is not int or part.value_offset < 0:
            raise ValueError("field_parts value_offset must be a non-negative integer")
        matches = [field for field in telegram.fields if field.name == part.field_ref]
        if len(matches) != 1:
            raise ValueError(f"unknown or ambiguous field_parts field_ref: {part.field_ref!r}")
        field = matches[0]
        if field.name in used_names:
            raise ValueError(f"duplicate field_parts field_ref: {field.name}")
        used_names.add(field.name)
        if (field.source != "payload" or field.signed or field.reserved
                or field.constant is not None):
            raise ValueError(f"field_parts requires unsigned writable payload fields: {field.name}")
        if (type(field.offset) is not int or field.offset < 0
                or type(field.size) is not int or field.size <= 0):
            raise ValueError(f"invalid field_parts field bounds: {field.name}")
        maximum = (1 << field.size) - 1
        low = field.raw_min if field.raw_min is not None else 0
        high = field.raw_max if field.raw_max is not None else maximum
        if (not isinstance(low, (int, float)) or not isinstance(high, (int, float))
                or not 0 <= low <= high <= maximum):
            raise ValueError(f"field_parts raw range exceeds field width: {field.name}")
        for other in [*telegram.fields, *telegram.status_fields]:
            if other is field:
                continue
            if other.name == field.name:
                raise ValueError(f"ambiguous field_parts field name: {field.name}")
            if (other.source == "payload" and field.offset < other.offset + other.size
                    and other.offset < field.offset + field.size):
                raise ValueError(f"overlapping payload field_parts field: {field.name}")
        intervals.append((part.value_offset, part.value_offset + field.size))
        fields.append(field)
    end = 0
    for start, stop in sorted(intervals):
        if start != end:
            raise ValueError("field_parts value bits must be contiguous from zero without overlap")
        end = stop
    if binding.scale is not None:
        scale = binding.scale
        if (not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (
                scale.raw_min, scale.raw_max, scale.scale_min, scale.scale_max))
                or scale.scale_min == scale.scale_max
                or scale.raw_min != int(scale.raw_min) or scale.raw_max != int(scale.raw_max)
                or not 0 <= scale.raw_min < scale.raw_max <= (1 << end) - 1):
            raise ValueError("field_parts scale raw range exceeds composite width or is invalid")
    return fields


def validate_telegram_composites(telegram: TelegramDefinition) -> None:
    """Validate composites; reject shared targets within each binding collection.

    Channel and message bindings are separate directions/snapshot sources. Simple
    bindings retain their existing selector-dependent sharing behavior.
    """
    for bindings in (telegram.channel_bindings, telegram.message_bindings):
        for binding in bindings:
            if not binding.field_parts:
                continue
            fields = composite_fields(binding, telegram)
            names = {field.name for field in fields}
            semantic_ref = getattr(binding, "channel_ref", getattr(binding, "message_ref", None))
            for other in bindings:
                if other is binding:
                    continue
                other_names = {part.field_ref for part in other.field_parts}
                if other.field_ref is not None:
                    other_names.add(other.field_ref)
                other_ref = getattr(other, "channel_ref", getattr(other, "message_ref", None))
                if names & other_names or semantic_ref == other_ref:
                    raise ValueError("duplicate/overlapping composite binding assignment")
