"""Conservative RX screening; suspicion is not proof of radio corruption."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from enocean_mqtt.eep.models import EEPDefinition
from enocean_mqtt.esp3.signal import RORG_NAMES

_HEX = re.compile(r"^[0-9A-Fa-f]+$")
_FIXED_LENGTHS = {"F6": 1, "D5": 1, "A5": 4}


@dataclass(frozen=True)
class TelegramAssessment:
    classification: str
    reason: str
    skip_decode: bool = True
    candidate_sender_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "reason": self.reason,
            "skip_eep_decode": self.skip_decode,
            "corruption_proven": False,
            **({"candidate_sender_ids": list(self.candidate_sender_ids)}
               if self.candidate_sender_ids else {}),
        }


def assess_telegram(
    *, rorg: str | None, data: str | None, sender_id: str | None,
    status: str | None, direction: str = "rx", definition: EEPDefinition | None = None,
    known_sender_ids: Iterable[str] = (),
) -> TelegramAssessment | None:
    """Screen structure, profile compatibility and teach-in before semantic RX.

    No bytes are corrected. A nearby sender ID alone is only a diagnostic hint,
    and never suppresses decoding or changes administrative classification.
    """
    if direction != "rx":
        return None
    org = (rorg or "").upper()
    payload = "".join((data or "").split()).upper()
    sender = (sender_id or "").upper()
    for value, length, reason in (
        (org, 2, "invalid_rorg"), (sender, 8, "invalid_sender_id"),
    ):
        if len(value) != length or not _HEX.fullmatch(value):
            return TelegramAssessment("suspect", reason)
    if org not in RORG_NAMES:
        return TelegramAssessment("suspect", "unrecognized_rorg")
    if not payload or len(payload) % 2 or not _HEX.fullmatch(payload):
        return TelegramAssessment("suspect", "invalid_payload_hex")
    if status is not None and (len(status) != 2 or not _HEX.fullmatch(status)):
        return TelegramAssessment("suspect", "invalid_status")
    if org in _FIXED_LENGTHS and len(payload) != _FIXED_LENGTHS[org] * 2:
        return TelegramAssessment("suspect", "invalid_payload_length")
    # SIGNAL/UTE/security and other RORGs may legitimately share a device ID.
    # Compare against *all* RX telegram identities, not only the EEP's prefix.
    if definition is not None and org != "D0":
        allowed = {
            t.telegram_id.rorg.upper() for t in definition.telegrams
            if t.direction in (None, "rx")
        } or {definition.rorg.upper()}
        if org not in allowed:
            return TelegramAssessment("profile_mismatch", "rorg_not_in_rx_profile")
    if org in {"A5", "D5"} and not (int(payload[-2:], 16) & 0x08):
        return TelegramAssessment("teach_in_candidate", "lrn_bit_clear")
    known = set(known_sender_ids)
    if sender not in known:
        near = tuple(sorted(
            candidate for candidate in known
            if re.fullmatch(r"[0-9A-Fa-f]{8}", candidate)
            and 1 <= (int(sender, 16) ^ int(candidate, 16)).bit_count() <= 2
        ))
        if near:
            return TelegramAssessment(
                "sender_id_candidate", "near_known_sender_id", False, near,
            )
    return None
