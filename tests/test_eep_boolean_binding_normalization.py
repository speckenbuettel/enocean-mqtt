from typing import Any

from enocean_mqtt.eep.generator.semantic_mapping import normalize_boolean_bindings
from enocean_mqtt.eep.generator.validator import validate_eep_definition

Json = dict[str, Any]


def test_boolean_binding_enum_is_removed() -> None:
    definition: Json = {
        "messages": [
            {
                "name": "store_final_value",
                "data_type": "boolean",
                "enum": [
                    {"value": 0, "label": "no"},
                    {"value": 1, "label": "yes"},
                ],
            }
        ],
        "telegrams": [
            {
                "telegram_type_id": "example.tx",
                "telegram_id": {"rorg": "A5"},
                "direction": "tx",
                "fields": [
                    {
                        "name": "store_final_value",
                        "offset": 0,
                        "size": 1,
                    }
                ],
                "message_bindings": [
                    {
                        "message_ref": "store_final_value",
                        "field_ref": "store_final_value",
                        "enum": [
                            {"value": 0, "label": "no"},
                            {"value": 1, "label": "yes"},
                        ],
                    }
                ],
            }
        ],
    }

    normalize_boolean_bindings(definition)

    messages = definition["messages"]
    telegrams = definition["telegrams"]
    assert isinstance(messages, list)
    assert isinstance(telegrams, list)

    message = messages[0]
    telegram = telegrams[0]
    assert isinstance(message, dict)
    assert isinstance(telegram, dict)

    bindings = telegram["message_bindings"]
    assert isinstance(bindings, list)
    binding = bindings[0]
    assert isinstance(binding, dict)

    assert message["data_type"] == "boolean"
    assert "enum" not in message
    assert "enum" not in binding
    assert validate_eep_definition(definition) == []


def test_enum_switch_binding_is_preserved() -> None:
    definition: Json = {
        "messages": [
            {
                "name": "switch",
                "data_type": "enum",
                "enum": [
                    {"value": 0, "label": "off"},
                    {"value": 1, "label": "on"},
                ],
            }
        ],
        "telegrams": [
            {
                "telegram_type_id": "example.tx",
                "telegram_id": {"rorg": "A5"},
                "direction": "tx",
                "fields": [
                    {
                        "name": "switching_command",
                        "offset": 0,
                        "size": 1,
                    }
                ],
                "message_bindings": [
                    {
                        "message_ref": "switch",
                        "field_ref": "switching_command",
                        "enum": [
                            {"value": 0, "label": "off"},
                            {"value": 1, "label": "on"},
                        ],
                    }
                ],
            }
        ],
    }

    normalize_boolean_bindings(definition)

    messages = definition["messages"]
    telegrams = definition["telegrams"]
    assert isinstance(messages, list)
    assert isinstance(telegrams, list)

    message = messages[0]
    telegram = telegrams[0]
    assert isinstance(message, dict)
    assert isinstance(telegram, dict)

    bindings = telegram["message_bindings"]
    assert isinstance(bindings, list)
    binding = bindings[0]
    assert isinstance(binding, dict)

    assert message["data_type"] == "enum"
    assert "enum" in binding


def test_validator_rejects_boolean_binding_enum() -> None:
    definition: Json = {
        "messages": [
            {
                "name": "flag",
                "data_type": "boolean",
            }
        ],
        "telegrams": [
            {
                "telegram_type_id": "example.tx",
                "telegram_id": {"rorg": "A5"},
                "direction": "tx",
                "fields": [
                    {
                        "name": "flag",
                        "offset": 0,
                        "size": 1,
                    }
                ],
                "message_bindings": [
                    {
                        "message_ref": "flag",
                        "field_ref": "flag",
                        "enum": [
                            {"value": 0, "label": "no"},
                            {"value": 1, "label": "yes"},
                        ],
                    }
                ],
            }
        ],
    }

    issues = validate_eep_definition(definition)

    assert "ERROR boolean binding must not define enum: example.tx.flag" in issues


def test_binding_enum_is_normalized_before_semantic_enrichment() -> None:
    definition: Json = {
        "telegrams": [
            {
                "telegram_type_id": "a5-38-08.cmd05.control_variable",
                "telegram_id": {"rorg": "A5", "cmd": "0x05"},
                "direction": "tx",
                "fields": [
                    {
                        "name": "energy_hold_off",
                        "offset": 0,
                        "size": 1,
                    }
                ],
                "message_bindings": [
                    {
                        "message_ref": "energy_hold_off",
                        "field_ref": "energy_hold_off",
                        "enum": [
                            {"value": 0, "label": "no"},
                            {"value": 1, "label": "yes"},
                        ],
                    }
                ],
            }
        ]
    }

    normalize_boolean_bindings(definition)

    telegrams = definition["telegrams"]
    assert isinstance(telegrams, list)
    telegram = telegrams[0]
    assert isinstance(telegram, dict)
    bindings = telegram["message_bindings"]
    assert isinstance(bindings, list)
    binding = bindings[0]
    assert isinstance(binding, dict)

    assert "enum" not in binding
