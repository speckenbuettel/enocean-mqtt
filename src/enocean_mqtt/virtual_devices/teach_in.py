"""Teach-in method and telegram generation for virtual devices."""

from __future__ import annotations

from enocean_mqtt.eep.models import EEPDefinition

TEACH_IN_METHOD_A5 = "4bs_unidirectional_with_profile"
TEACH_IN_METHOD_D5 = "1bs_teach_in"
TEACH_IN_METHOD_F6 = "rps_data_telegram"


class TeachInGenerationError(ValueError):
    """Raised when teach-in generation fails."""


def determine_teach_in_method(eep_definition: EEPDefinition) -> str:
    """Return canonical teach-in method for one EEP."""

    rorg = eep_definition.rorg.upper()

    if rorg == "A5":
        return TEACH_IN_METHOD_A5

    if rorg == "D5":
        return TEACH_IN_METHOD_D5

    if rorg == "F6":
        return TEACH_IN_METHOD_F6

    raise TeachInGenerationError(
        f"Unsupported teach-in RORG for virtual devices: {rorg}"
    )


def generate_teach_in_telegram(
    *,
    sender_id: str,
    eep_definition: EEPDefinition,
    manufacturer_id: str,
) -> dict:
    """Generate persistent teach-in metadata for one virtual device."""

    method = determine_teach_in_method(eep_definition)
    rorg = eep_definition.rorg.upper()

    if rorg == "A5":
        payload = _build_a5_payload(
            func=eep_definition.func,
            type_value=eep_definition.type,
            manufacturer_id=manufacturer_id,
        )

        return {
            "method": method,
            "rorg": rorg,
            "eep": eep_definition.eep,
            "sender_id": sender_id,
            "manufacturer_id": manufacturer_id,
            "payload": payload,
        }

    if rorg == "D5":
        return {
            "method": method,
            "rorg": rorg,
            "eep": eep_definition.eep,
            "sender_id": sender_id,
            "payload": "08",
        }

    if rorg == "F6":
        return {
            "method": method,
            "rorg": rorg,
            "eep": eep_definition.eep,
            "sender_id": sender_id,
            "payload": "30",
        }

    raise TeachInGenerationError(
        f"Unsupported teach-in RORG for virtual devices: {rorg}"
    )


def _build_a5_payload(
    *,
    func: str,
    type_value: str,
    manufacturer_id: str,
) -> str:
    func_int = int(func, 16)
    type_int = int(type_value, 16)
    manufacturer_int = int(manufacturer_id, 16)

    if func_int > 0x3F:
        raise TeachInGenerationError(
            "FUNC values above 0x3F require UTE and are not yet supported"
        )

    if type_int > 0x7F:
        raise TeachInGenerationError(
            "TYPE values above 0x7F require UTE and are not yet supported"
        )

    if manufacturer_int > 0x7FF:
        raise TeachInGenerationError(
            "Manufacturer IDs above 0x7FF are not valid for 4BS teach-in"
        )

    payload = (
        ((func_int & 0x3F) << 26)
        | ((type_int & 0x7F) << 19)
        | ((manufacturer_int & 0x7FF) << 8)
        | 0x80
    )

    return f"{payload:08X}"
