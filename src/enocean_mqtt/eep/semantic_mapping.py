"""Semantic value alias support for Registry v3 runtime processing."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_ALIAS_PATH = Path("eep/semantic-aliases.json")


def semantic_value_matches_label(value: Any, canonical_label: str) -> bool:
    """Return whether an input value is an alias for a canonical label."""

    normalized_value = _normalize(value)
    normalized_label = canonical_label.strip().lower()

    if normalized_value == normalized_label:
        return True

    return normalized_value in _load_aliases().get(normalized_label, set())


def semantic_alias_candidates(value: Any, canonical_label: str) -> set[str]:
    """Return normalized input candidates for a canonical semantic label.

    Kept for compatibility with older callers. Runtime enum encoding should use
    ``semantic_value_matches_label`` so aliases are only matched against the
    canonical EEP label and never inserted into the set of raw enum values.
    """

    normalized_value = _normalize(value)
    candidates = {
        str(value),
        _normalized_scalar(value),
        normalized_value,
    }

    if semantic_value_matches_label(value, canonical_label):
        candidates.add(canonical_label)
        candidates.add(canonical_label.strip().lower())

    return candidates


def derived_value(
    *,
    semantic_role: str | None,
    value_name: str,
    value: Any,
) -> Any | None:
    """Return a configured derived value for a semantic role and value name."""

    if semantic_role is None:
        return None

    mappings = _load_derived_values()
    role_mapping = mappings.get(semantic_role)
    if role_mapping is None:
        parts = semantic_role.split(".")
        if len(parts) == 3 and parts[2] in {
            "measurement",
            "state",
            "setpoint",
            "command",
            "configuration",
            "diagnostic",
            "selector",
        }:
            # Keep existing configured base-role derivations during the v3 migration.
            # An explicitly configured final role always takes precedence.
            role_mapping = mappings.get(".".join(parts[:2]))
    if role_mapping is None:
        return None

    values = role_mapping.get(value_name)
    if values is None:
        return None

    for key, derived in values.items():
        if semantic_value_matches_label(value, key):
            return derived

    return None


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, set[str]]:
    data = _load_mapping()
    aliases: dict[str, set[str]] = {}

    for label, values in data.get("aliases", {}).items():
        if not isinstance(values, list):
            continue

        canonical = label.strip().lower()
        aliases[canonical] = {canonical}
        aliases[canonical].update(_normalize(item) for item in values)

    return aliases


@lru_cache(maxsize=1)
def _load_derived_values() -> dict[str, dict[str, dict[str, Any]]]:
    data = _load_mapping()
    derived_values: dict[str, dict[str, dict[str, Any]]] = {}

    raw_derived_values = data.get("derived_values", {})
    if not isinstance(raw_derived_values, dict):
        return derived_values

    for semantic_role, role_mapping in raw_derived_values.items():
        if not isinstance(role_mapping, dict):
            continue

        normalized_role_mapping: dict[str, dict[str, Any]] = {}
        for value_name, values in role_mapping.items():
            if not isinstance(values, dict):
                continue

            normalized_role_mapping[value_name] = {
                key.strip().lower(): value for key, value in values.items()
            }

        derived_values[semantic_role] = normalized_role_mapping

    return derived_values


def _load_mapping() -> dict[str, Any]:
    path = Path(os.getenv("ENOCEAN_MQTT_SEMANTIC_ALIASES", DEFAULT_ALIAS_PATH))

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        return {}

    return data


def _normalize(value: Any) -> str:
    return _normalized_scalar(value).strip().lower()


def _normalized_scalar(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value)
