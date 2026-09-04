"""Generic EEP decoder engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.models import (
    BitFieldDefinition,
    ChannelDefinition,
    EEPDefinition,
    LinearScale,
)


class EEPDecodeError(ValueError):
    """Raised when an EEP telegram cannot be decoded."""


INTERNAL_CHANNEL_PREFIXES = (
    "reserved",
)

INTERNAL_CHANNEL_NAMES = {
    "telegram_type",
}


@dataclass(slots=True)
class DecodedChannelValue:
    """Decoded semantic channel value."""

    name: str
    value: bool | float | int | str
    raw_value: int
    data_type: str
    definition: ChannelDefinition
    unit: str | None = None
    semantic_role: str | None = None


@dataclass(slots=True)
class DecodedTelegram:
    """Decoded telegram with semantic channel values."""

    eep: str
    values: dict[str, DecodedChannelValue]



def parse_payload_hex(payload_hex: str) -> bytes:
    """Parse a space-separated or compact hexadecimal payload string."""

    normalized = payload_hex.replace(" ", "").replace("-", "").replace(":", "")

    if len(normalized) % 2 != 0:
        raise EEPDecodeError("Payload hex string must contain an even number of characters")

    try:
        return bytes.fromhex(normalized)
    except ValueError as exc:
        raise EEPDecodeError("Payload contains non-hexadecimal characters") from exc



def extract_bits(payload: bytes, offset: int, size: int) -> int:
    """Extract a big-endian bit field using EEP offset semantics."""

    if size <= 0:
        raise EEPDecodeError("Bit field size must be positive")

    total_bits = len(payload) * 8

    if offset < 0 or offset + size > total_bits:
        raise EEPDecodeError(
            f"Bit field offset={offset}, size={size} exceeds payload size {total_bits} bits"
        )

    value = int.from_bytes(payload, byteorder="big")
    shift = total_bits - offset - size
    mask = (1 << size) - 1

    return (value >> shift) & mask



def apply_linear_scale(raw_value: int, scale: LinearScale) -> float:
    """Convert raw value using a linear scale definition."""

    raw_span = scale.raw_max - scale.raw_min

    if raw_span == 0:
        raise EEPDecodeError("Linear scale raw range must not be zero")

    scaled_span = scale.scale_max - scale.scale_min

    return scale.scale_min + ((raw_value - scale.raw_min) * scaled_span / raw_span)



def decode_field(field: BitFieldDefinition, payload: bytes) -> int:
    """Decode a raw field value from payload bytes."""

    return extract_bits(payload, field.offset, field.size)



def _is_internal_channel(channel_name: str) -> bool:
    """Return whether channel is protocol-internal and should not be published."""

    normalized_name = channel_name.strip().lower()

    if normalized_name in INTERNAL_CHANNEL_NAMES:
        return True

    return normalized_name.startswith(INTERNAL_CHANNEL_PREFIXES)



def decode_channel(channel: ChannelDefinition, payload: bytes) -> DecodedChannelValue | None:
    """Decode one semantic channel from payload bytes."""

    if channel.bitfield is None:
        return None

    if _is_internal_channel(channel.name):
        return None

    raw_value = decode_field(channel.bitfield, payload)

    value: bool | float | int | str

    if channel.scale:
        value = apply_linear_scale(raw_value, channel.scale)
    elif channel.enum:
        mapped = next(
            (item.label for item in channel.enum if item.value == raw_value),
            None,
        )
        value = mapped if mapped is not None else raw_value
    elif channel.data_type == "boolean":
        value = bool(raw_value)
    else:
        value = raw_value

    return DecodedChannelValue(
        name=channel.name,
        value=value,
        raw_value=raw_value,
        data_type=channel.data_type,
        definition=channel,
        unit=channel.unit,
        semantic_role=channel.semantic_role,
    )



def decode_with_definition(
    eep_definition: EEPDefinition,
    payload_hex: str,
) -> DecodedTelegram:
    """Decode payload using an explicit EEP definition."""

    payload = parse_payload_hex(payload_hex)

    values: dict[str, DecodedChannelValue] = {}

    for channel in eep_definition.channels:
        decoded = decode_channel(channel, payload)

        if decoded is not None:
            values[channel.name] = decoded

    return DecodedTelegram(
        eep=eep_definition.eep,
        values=values,
    )



def decode_eep(eep: str, payload_hex: str) -> DecodedTelegram:
    """Decode payload using a registered EEP definition."""

    try:
        eep_definition = load_eep_definition(eep)
    except EEPRegistryError as exc:
        raise EEPDecodeError(f"Unsupported EEP: {eep}") from exc

    return decode_with_definition(eep_definition, payload_hex)



def decoded_values_to_plain_dict(decoded: DecodedTelegram) -> dict[str, Any]:
    """Convert decoded telegram to a plain serializable dictionary."""

    return {
        name: {
            "value": channel.value,
            "raw_value": channel.raw_value,
            "data_type": channel.data_type,
            "unit": channel.unit,
            "semantic_role": channel.semantic_role,
            "friendly_name": (
                channel.definition.friendly_name or channel.name
            ),
        }
        for name, channel in decoded.values.items()
    }
