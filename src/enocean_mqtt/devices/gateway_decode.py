"""Shared passive decoding of external gateway command observations."""

from __future__ import annotations

from enocean_mqtt.eep.decoder import EEPDecodeError
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.runtime_decoder import RuntimeDecodedTelegram, decode_runtime_with_definition
from enocean_mqtt.esp3.signal import RORG_NAMES


def decode_gateway_payload(
    profile: str | None, payload: str | None, rorg: str | None, status: str | None = None,
) -> tuple[str, RuntimeDecodedTelegram | None, str | None]:
    """Return an exclusive outcome, decoded command and optional real error."""
    rorg = (rorg or "").upper()
    if rorg not in RORG_NAMES or rorg == "D0":
        return "not_applicable", None, None
    try:
        data = bytes.fromhex(payload or "")
    except ValueError:
        return ("malformed_payload", None, "Invalid hexadecimal payload") if profile else (
            "no_profile", None, None,
        )
    if ((rorg == "A5" and len(data) == 4) or (rorg == "D5" and len(data) == 1)):
        if not data[-1] & 8:
            return "teach_in", None, None
    if not profile:
        return "no_profile", None, None
    try:
        definition = load_eep_definition(profile)
    except (EEPRegistryError, ValueError, OSError, KeyError, TypeError) as exc:
        return "invalid_profile", None, str(exc)
    if not data:
        return "malformed_payload", None, "Telegram has no payload data"
    if rorg == "D2":
        command = data[0] & 15
        command_definitions = [
            telegram for telegram in definition.telegrams
            if telegram.direction == "tx" and any(
                field.name.lower() == "cmd" and field.constant == command
                for field in telegram.fields
            )
        ]
        if not command_definitions:
            return "unsupported_variant", None, None
        if all(any(field.offset + field.size > len(data) * 8 for field in telegram.fields)
               for telegram in command_definitions):
            return "malformed_payload", None, "Command payload too short"
    try:
        decoded = decode_runtime_with_definition(
            definition, data.hex(), status_hex=status, rorg=rorg, profile_direction="tx",
        )
        return "decoded", decoded, None
    except (EEPDecodeError, ValueError) as exc:
        message = str(exc)
        if "No matching TX" in message and rorg == "D2" and "payload too short" not in message:
            return "unsupported_variant", None, None
        return "malformed_payload", None, message
