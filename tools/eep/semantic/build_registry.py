"""Build the aggregated semantic role registry from the mapping JSON.

The mapping JSON is a near-lossless export of the human-maintained Excel
workbook. This module derives an aggregated semantic role registry from it.
The generated registry is intended for validation, documentation and later
compiler integration.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = Path("eep/semantic-role-mapping.json")
DEFAULT_TARGET = Path("eep/semantic-role-registry.json")

_SKIPPED_VALUES = {"", "TBD", "tbd"}


def _as_string(value: object) -> str:
    return str(value or "").strip()


def _normalise_list(values: set[str]) -> list[str]:
    return sorted(value for value in values if value and value not in _SKIPPED_VALUES)


def _merge_attributes(target: dict[str, set[str]], attributes: object) -> None:
    """Collect attribute names and observed values from a mapping entry."""

    if not isinstance(attributes, dict):
        return

    for key, value in attributes.items():
        key_text = _as_string(key)
        if not key_text:
            continue

        if isinstance(value, list):
            for item in value:
                item_text = _as_string(item)
                if item_text:
                    target[key_text].add(item_text)
        elif isinstance(value, dict):
            # Nested attribute objects are uncommon in the current mapping, but
            # preserving their JSON form keeps this aggregation deterministic.
            target[key_text].add(json.dumps(value, ensure_ascii=False, sort_keys=True))
        else:
            value_text = _as_string(value)
            if value_text:
                target[key_text].add(value_text)


def _load_entries(source: Path) -> list[dict[str, Any]]:
    payload = json.loads(source.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        # Compatibility with early prototype exports.
        return [entry for entry in payload if isinstance(entry, dict)]

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise SystemExit(f"Invalid semantic role mapping JSON: {source}")

    return [entry for entry in entries if isinstance(entry, dict)]


def build_registry(
    source: Path = DEFAULT_SOURCE,
    target: Path = DEFAULT_TARGET,
) -> dict[str, Any]:
    """Build the aggregated semantic role registry."""

    entries = _load_entries(source)

    registry: dict[str, dict[str, Any]] = {}
    attribute_values: dict[str, defaultdict[str, set[str]]] = {}

    for entry in entries:
        semantic_role = _as_string(entry.get("semantic_role"))
        if semantic_role in _SKIPPED_VALUES:
            continue

        role_entry = registry.setdefault(
            semantic_role,
            {
                "semantic_role": semantic_role,
                "channel_types": set(),
                "capabilities": set(),
                "function_keys": set(),
                "normalized_functions": set(),
                "confidences": set(),
                "review_statuses": set(),
                "notes": set(),
            },
        )
        role_attributes = attribute_values.setdefault(semantic_role, defaultdict(set))

        role_entry["channel_types"].add(_as_string(entry.get("channel_type")))
        role_entry["capabilities"].add(_as_string(entry.get("capability")))
        role_entry["function_keys"].add(_as_string(entry.get("function_key")))
        role_entry["normalized_functions"].add(_as_string(entry.get("normalized_function")))
        role_entry["confidences"].add(_as_string(entry.get("confidence")))
        role_entry["review_statuses"].add(_as_string(entry.get("review_status")))

        note = _as_string(entry.get("notes"))
        if note:
            role_entry["notes"].add(note)

        _merge_attributes(role_attributes, entry.get("attributes"))

    roles: list[dict[str, Any]] = []
    for semantic_role in sorted(registry):
        role_entry = registry[semantic_role]
        attributes = {
            key: _normalise_list(values)
            for key, values in sorted(attribute_values.get(semantic_role, {}).items())
        }

        roles.append(
            {
                "semantic_role": semantic_role,
                "channel_types": _normalise_list(role_entry["channel_types"]),
                "capabilities": _normalise_list(role_entry["capabilities"]),
                "function_keys": _normalise_list(role_entry["function_keys"]),
                "normalized_functions": _normalise_list(role_entry["normalized_functions"]),
                "attributes": attributes,
                "confidences": _normalise_list(role_entry["confidences"]),
                "review_statuses": _normalise_list(role_entry["review_statuses"]),
                "notes": _normalise_list(role_entry["notes"]),
            }
        )

    payload: dict[str, Any] = {
        "schema_version": "0.1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": str(source),
        "role_count": len(roles),
        "roles": roles,
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()

    payload = build_registry(args.source, args.target)
    print(f"Wrote {args.target} ({payload['role_count']} semantic roles)")


if __name__ == "__main__":
    main()
