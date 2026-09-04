"""Shared runtime decode helper for registry-driven EEP telegrams."""

from __future__ import annotations

from typing import Any

from enocean_mqtt.eep.models import EEPDefinition
from enocean_mqtt.eep.runtime_decoder import (
    RuntimeDecodedTelegram,
    decode_runtime_with_definition,
)


def decode_runtime_telegram(
    *,
    eep_definition: EEPDefinition,
    payload_hex: str,
    status_hex: str | None = None,
    rorg: str | None = None,
    direction: str | None = None,
    sender_id: str | None = None,
    telegram_id: str | None = None,
    external_context: dict[str, Any] | None = None,
) -> RuntimeDecodedTelegram:
    """Decode one runtime telegram with a canonical decoder context.

    All runtime entry points should use this helper instead of calling
    ``decode_runtime_with_definition`` directly. This keeps telegram identity
    selection consistent for multi-message and multi-RORG profiles.
    """

    context = dict(external_context or {})

    if direction is not None:
        context["direction"] = direction

    if sender_id is not None:
        context["sender_id"] = sender_id

    if rorg is not None:
        context["rorg"] = rorg

    return decode_runtime_with_definition(
        eep_definition=eep_definition,
        payload_hex=payload_hex,
        status_hex=status_hex,
        telegram_id=telegram_id,
        rorg=rorg,
        external_context=context,
    )
