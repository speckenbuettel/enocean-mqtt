from __future__ import annotations

from enocean_mqtt.eep.json_registry import load_eep_definition
from enocean_mqtt.eep.models import LinearScale, MessageBindingDefinition
from enocean_mqtt.eep.runtime_decoder import decode_runtime_with_definition, dependency_matches

A5_20_06_REAL_RX_PAYLOAD = "28834BE8"


def test_a5_20_06_real_rx_payload_decodes_selector_dependent_values() -> None:
    definition = load_eep_definition("A5-20-06")

    decoded = decode_runtime_with_definition(
        definition,
        A5_20_06_REAL_RX_PAYLOAD,
    )

    assert decoded.telegram_type_id == "a5-20-06.rx.direction1"

    assert decoded.fields["current_value"] == 40
    assert decoded.fields["local_offset_mode"] == 1
    assert decoded.fields["local_offset"] == 3
    assert decoded.fields["temperature"] == 75
    assert decoded.fields["temperature_selection"] == 1
    assert decoded.fields["telegram_type"] == 1

    values = decoded.values

    assert values["valve_position"].value == 40
    assert values["valve_position"].unit == "%"

    assert values["local_offset_mode"].value == "absolute_temperature"
    assert "local_offset" not in values
    assert values["local_temperature_setpoint"].value == 1.5
    assert values["local_temperature_setpoint"].unit == "°C"

    assert values["temperature_selection"].value == "feed_sensor_temperature"
    assert "local_ambient_temperature" not in values
    assert values["feed_temperature"].value == 37.5
    assert values["feed_temperature"].unit == "°C"

    assert values["energy_input_enabled"].value == "harvesting_active"
    assert values["energy_storage_charged"].value == "sufficiently_charged"
    assert values["window_open_detection"].value == "closed"
    assert values["telegram_type"].value == "data_telegram"
    assert values["radio_error"].value == "radio_communication_stable"
    assert values["radio_signal_strength"].value == "radio_signal_strong"
    assert values["actuator_obstructed"].value == "actuator_working_correctly"


def test_a5_20_06_tx_profile_exposes_message_bindings_for_temperature_mode() -> None:
    definition = load_eep_definition("A5-20-06")
    tx_telegram = next(
        telegram
        for telegram in definition.telegrams
        if telegram.telegram_type_id == "a5-20-06.tx.direction2"
    )

    assert tx_telegram.direction == "tx"

    field_names = {field.name for field in tx_telegram.fields}
    assert {
        "setpoint",
        "room_temperature",
        "reference_run",
        "communication_interval",
        "summer_mode",
        "setpoint_selection",
        "temperature_selection",
        "standby",
        "telegram_type",
    }.issubset(field_names)

    message_names = {binding.message_ref for binding in tx_telegram.message_bindings}
    assert {
        "temperature_setpoint",
        "room_temperature",
        "communication_interval",
        "temperature_selection",
        "telegram_type",
    }.issubset(message_names)

    selector_context = {
        "setpoint_selection": 1,
        "temperature_selection": 1,
    }

    temperature_setpoint_binding = _active_message_binding(
        tx_telegram.message_bindings,
        "temperature_setpoint",
        selector_context,
    )
    room_temperature_binding = _active_message_binding(
        tx_telegram.message_bindings,
        "room_temperature",
        selector_context,
    )
    temperature_selection_binding = _active_message_binding(
        tx_telegram.message_bindings,
        "temperature_selection",
        selector_context,
    )

    assert temperature_setpoint_binding.field_ref == "setpoint"
    assert _semantic_to_raw(21.5, temperature_setpoint_binding.scale) == 43

    assert room_temperature_binding.field_ref == "room_temperature"
    assert _semantic_to_raw(20.0, room_temperature_binding.scale) == 80

    assert temperature_selection_binding.field_ref == "temperature_selection"
    assert _enum_raw_value(temperature_selection_binding, "request_feed_temperature") == 1


def _active_message_binding(
    bindings: list[MessageBindingDefinition],
    message_ref: str,
    fields: dict[str, int],
) -> MessageBindingDefinition:
    context = type(
        "MessageBindingContext",
        (),
        {
            "fields": fields,
            "status_fields": {},
            "context": {},
            "telegram_id": None,
        },
    )()

    active = [
        binding
        for binding in bindings
        if binding.message_ref == message_ref
        and dependency_matches(binding.depends_on, context)
    ]

    assert len(active) == 1
    return active[0]


def _semantic_to_raw(value: float, scale: LinearScale | None) -> int:
    assert scale is not None

    raw_span = scale.raw_max - scale.raw_min
    scaled_span = scale.scale_max - scale.scale_min
    raw = scale.raw_min + ((value - scale.scale_min) * raw_span / scaled_span)

    return int(round(raw))


def _enum_raw_value(binding: MessageBindingDefinition, label: str) -> int | str | bool | float:
    matches = [item.value for item in binding.enum if item.label == label]

    assert len(matches) == 1
    return matches[0]
