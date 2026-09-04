"""Validation helpers for generated EEP registry definitions."""

from __future__ import annotations

from typing import Any


def _dependency_signature(dependency: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if not isinstance(dependency, dict):
        return ()

    return tuple(
        sorted(
            (str(key), str(value))
            for key, value in dependency.items()
        )
    )


def _telegram_dependency_signature(
    telegram: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    return _dependency_signature(telegram.get("depends_on"))


def _telegram_identity(
    telegram: dict[str, Any],
) -> tuple[tuple[str, Any], ...]:
    telegram_id = telegram.get("telegram_id")
    if not isinstance(telegram_id, dict):
        telegram_id = {}

    identity = {
        **telegram_id,
        "direction": telegram.get("direction"),
        "depends_on": _telegram_dependency_signature(telegram),
    }
    return tuple(sorted(identity.items()))


def _iter_channels(telegram: dict[str, Any]):
    for group in ("channels", "metadata_channels"):
        for channel in telegram.get(group, []):
            if isinstance(channel, dict):
                yield channel
    for message in telegram.get("messages", []):
        if not isinstance(message, dict):
            continue
        for channel in message.get("channels", []):
            if isinstance(channel, dict):
                yield channel


def _field_names(telegram: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for group in ("fields", "status_fields"):
        for field in telegram.get(group, []):
            if isinstance(field, dict) and field.get("name"):
                names.add(str(field["name"]))
    for channel in _iter_channels(telegram):
        for key in ("name", "field_ref"):
            if channel.get(key):
                names.add(str(channel[key]))
    return names


def _channel_key(
    channel: dict[str, Any],
    parent_dependency: tuple[tuple[str, str], ...],
) -> tuple[Any, Any, Any, tuple[tuple[str, str], ...]]:
    channel_dependency = _dependency_signature(channel.get("depends_on"))
    dependency = channel_dependency or parent_dependency

    return (
        channel.get("name"),
        channel.get("channel_type"),
        channel.get("semantic_role"),
        dependency,
    )


def _range_dependency_signature(
    range_item: dict[str, Any],
    channel: dict[str, Any],
    parent_dependency: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    return (
        _dependency_signature(range_item.get("depends_on"))
        or _dependency_signature(channel.get("depends_on"))
        or parent_dependency
    )


def _depends_on_items(telegram: dict[str, Any]):
    if isinstance(telegram.get("depends_on"), dict):
        yield "telegram", telegram["depends_on"]
    for channel in _iter_channels(telegram):
        name = channel.get("name", "<unknown>")
        if isinstance(channel.get("depends_on"), dict):
            yield f"channel[{name}]", channel["depends_on"]
        for index, range_item in enumerate(channel.get("ranges", [])):
            if isinstance(range_item, dict) and isinstance(range_item.get("depends_on"), dict):
                yield f"channel[{name}].ranges[{index}]", range_item["depends_on"]


def _validate_ranges(
    *,
    issues: list[str],
    telegram_type_id: str,
    channel: dict[str, Any],
    parent_dependency: tuple[tuple[str, str], ...],
) -> None:
    ranges_by_dependency: dict[tuple[tuple[str, str], ...], list[tuple[float, float]]] = {}

    for range_item in channel.get("ranges", []):
        if not isinstance(range_item, dict):
            continue

        raw_min = range_item.get("raw_min")
        raw_max = range_item.get("raw_max")
        if raw_min is None or raw_max is None:
            issues.append(
                f"ERROR invalid range in "
                f"{telegram_type_id}.{channel.get('name')}"
            )
            continue

        if float(raw_min) > float(raw_max):
            issues.append(
                f"ERROR inverted range in "
                f"{telegram_type_id}.{channel.get('name')}"
            )
            continue

        dependency = _range_dependency_signature(
            range_item,
            channel,
            parent_dependency,
        )
        ranges_by_dependency.setdefault(dependency, []).append(
            (float(raw_min), float(raw_max))
        )

    for dependency, ranges in ranges_by_dependency.items():
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:], strict=False):
            if current[0] <= previous[1]:
                issues.append(
                    "WARNING overlapping ranges in "
                    f"{telegram_type_id}.{channel.get('name')} "
                    f"for dependency {dependency}"
                )


def _semantic_types(definition: dict[str, Any], collection: str) -> dict[str, str]:
    result: dict[str, str] = {}
    items = definition.get(collection)
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        data_type = item.get("data_type")
        if isinstance(name, str) and isinstance(data_type, str):
            result[name] = data_type
    return result


def _validate_boolean_binding_enums(
    definition: dict[str, Any],
    issues: list[str],
) -> None:
    channel_types = _semantic_types(definition, "channels")
    message_types = _semantic_types(definition, "messages")

    for telegram in definition.get("telegrams", []):
        if not isinstance(telegram, dict):
            continue
        telegram_type_id = str(telegram.get("telegram_type_id", "<unknown>"))
        for binding_key, ref_key, semantic_types in (
            ("channel_bindings", "channel_ref", channel_types),
            ("message_bindings", "message_ref", message_types),
        ):
            bindings = telegram.get(binding_key)
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                semantic_ref = binding.get(ref_key)
                if (
                    isinstance(semantic_ref, str)
                    and semantic_types.get(semantic_ref) == "boolean"
                    and isinstance(binding.get("enum"), list)
                ):
                    issues.append(
                        "ERROR boolean binding must not define enum: "
                        f"{telegram_type_id}.{semantic_ref}"
                    )


def validate_eep_definition(definition: dict[str, Any]) -> list[str]:
    """Return validation warnings/errors for a generated registry definition."""

    issues: list[str] = []
    telegram_type_ids: set[str] = set()
    telegram_identities: dict[tuple[tuple[str, Any], ...], str] = {}

    _validate_boolean_binding_enums(definition, issues)

    for index, telegram in enumerate(definition.get("telegrams", [])):
        telegram_type_id = str(telegram.get("telegram_type_id", ""))
        if not telegram_type_id:
            issues.append(f"ERROR missing telegram_type_id at telegram[{index}]")
        elif telegram_type_id in telegram_type_ids:
            issues.append(f"ERROR duplicate telegram_type_id: {telegram_type_id}")
        telegram_type_ids.add(telegram_type_id)

        identity = _telegram_identity(telegram)
        if identity in telegram_identities:
            issues.append(
                "WARNING duplicate telegram identity: "
                f"{telegram_identities[identity]} and {telegram_type_id}"
            )
        telegram_identities[identity] = telegram_type_id

        parent_dependency = _telegram_dependency_signature(telegram)
        channel_keys: set[tuple[Any, Any, Any, tuple[tuple[str, str], ...]]] = set()

        for channel in _iter_channels(telegram):
            key = _channel_key(channel, parent_dependency)
            if key in channel_keys:
                issues.append(f"WARNING duplicate channel in {telegram_type_id}: {key}")
            channel_keys.add(key)

            _validate_ranges(
                issues=issues,
                telegram_type_id=telegram_type_id,
                channel=channel,
                parent_dependency=parent_dependency,
            )

        available_fields = _field_names(telegram)
        for location, dependency in _depends_on_items(telegram):
            source = dependency.get("source")
            field = dependency.get("field")
            if source not in {"field", "status_field", "telegram_id", "context"}:
                issues.append(f"ERROR invalid dependency source in {telegram_type_id}.{location}")
            if source in {"field", "status_field"} and field not in available_fields:
                issues.append(
                    f"WARNING unresolved dependency field in {telegram_type_id}.{location}: {field}"
                )
            if "equals" not in dependency:
                issues.append(f"WARNING dependency without equals in {telegram_type_id}.{location}")

    return issues
