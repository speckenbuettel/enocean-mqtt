from __future__ import annotations

import pytest

from enocean_mqtt.eep.json_registry import load_eep_definition
from enocean_mqtt.eep.models import (
    ChannelBindingDefinition,
    ChannelDefinition,
    EEPDefinition,
    FieldDefinition,
    TelegramDefinition,
    TelegramIdentity,
    ValueMapping,
)
from enocean_mqtt.eep.runtime_encoder import (
    EEPEncodeError,
    encode_semantic_snapshot,
    encode_semantic_snapshot_all,
)


def test_a5_20_06_temperature_setpoint_message_encodes_dependencies() -> None:
    definition = load_eep_definition("A5-20-06")

    encoded = encode_semantic_snapshot(
        eep_definition=definition,
        source="messages",
        snapshot={
            "temperature_setpoint": 21.5,
            "room_temperature": 20.0,
            "temperature_selection": "request_feed_temperature",
        },
    )

    assert encoded.rorg == "A5"
    assert encoded.telegram_type_id == "a5-20-06.tx.direction2"
    assert encoded.status == "00"

    telegram = _tx_telegram(definition)
    fields = _decode_fields(encoded.data, telegram)

    assert fields["setpoint"] == 43
    assert fields["room_temperature"] == 80
    assert fields["setpoint_selection"] == 1
    assert fields["temperature_selection"] == 1
    assert fields["reference_run"] == 0
    assert fields["communication_interval"] == 0
    assert fields["summer_mode"] == 0
    assert fields["standby"] == 0
    assert fields["reserved_24_4"] == 0
    assert fields["telegram_type"] == 1
    assert fields["reserved_29_3"] == 0


def test_a5_20_06_valve_position_message_encodes_dependencies() -> None:
    definition = load_eep_definition("A5-20-06")

    encoded = encode_semantic_snapshot(
        eep_definition=definition,
        source="messages",
        snapshot={
            "valve_position": 55,
            "room_temperature": 19.5,
            "communication_interval": "10_minutes",
        },
    )

    telegram = _tx_telegram(definition)
    fields = _decode_fields(encoded.data, telegram)

    assert fields["setpoint"] == 55
    assert fields["room_temperature"] == 78
    assert fields["setpoint_selection"] == 0
    assert fields["communication_interval"] == 3
    assert fields["telegram_type"] == 1


def test_a5_20_06_encoder_rejects_conflicting_selector_dependencies() -> None:
    definition = load_eep_definition("A5-20-06")

    with pytest.raises(EEPEncodeError, match="conflicting raw value"):
        encode_semantic_snapshot(
            eep_definition=definition,
            source="messages",
            snapshot={
                "valve_position": 55,
                "temperature_setpoint": 21.5,
                "room_temperature": 20.0,
            },
        )


def test_a5_20_06_encoder_requires_active_snapshot_values() -> None:
    definition = load_eep_definition("A5-20-06")

    with pytest.raises(EEPEncodeError, match="room_temperature"):
        encode_semantic_snapshot(
            eep_definition=definition,
            source="messages",
            snapshot={"temperature_setpoint": 21.5},
        )


def test_channel_encoder_uses_semantic_value_for_enum_reverse_mapping() -> None:
    definition = EEPDefinition(
        eep="TEST-SEMANTIC-VALUE",
        rorg="A5",
        func="00",
        type="00",
        channels=[
            ChannelDefinition(
                name="local_offset",
                data_type="float",
                semantic_role="climate.temperature",
                object_type="setpoint",
                unit="°C",
                enum=[
                    ValueMapping(
                        value=0,
                        label="offset_0c",
                        semantic_value=0.0,
                    ),
                    ValueMapping(
                        value=126,
                        label="offset_minus_2c",
                        semantic_value=-2.0,
                    ),
                ],
            )
        ],
        telegrams=[
            TelegramDefinition(
                telegram_type_id="test.tx",
                telegram_id=TelegramIdentity(rorg="A5"),
                direction="tx",
                fields=[FieldDefinition(name="local_offset", offset=0, size=8)],
                channel_bindings=[
                    ChannelBindingDefinition(
                        channel_ref="local_offset",
                        field_ref="local_offset",
                        enum=[
                            ValueMapping(
                                value=0,
                                label="offset_0c",
                                semantic_value=0.0,
                            ),
                            ValueMapping(
                                value=126,
                                label="offset_minus_2c",
                                semantic_value=-2.0,
                            ),
                        ],
                    )
                ],
            )
        ],
    )

    encoded = encode_semantic_snapshot(
        eep_definition=definition,
        source="channels",
        snapshot={"local_offset": -2.0},
    )

    assert encoded.data == "7E 00 00 00"


def test_ftkb_profile_encodes_contact_and_voltage_as_separate_telegrams() -> None:
    definition = load_eep_definition("eltako-ftkb")

    encoded = encode_semantic_snapshot_all(
        eep_definition=definition,
        source="channels",
        snapshot={
            "contact": 1,
            "battery_voltage": 2.94,
            "energy_storage_voltage": 2.73,
        },
    )

    assert [(item.rorg, item.data) for item in encoded] == [
        ("D5", "08"),
        ("A5", "8B 96 00 08"),
    ]


def test_ftkb_profile_trigger_ref_selects_matching_telegram_only() -> None:
    definition = load_eep_definition("eltako-ftkb")
    snapshot = {
        "contact": "closed",
        "battery_voltage": 2.94,
        "energy_storage_voltage": 2.73,
    }

    contact_telegram = encode_semantic_snapshot_all(
        eep_definition=definition,
        source="channels",
        snapshot=snapshot,
        trigger_refs={"contact"},
    )
    voltage_telegram = encode_semantic_snapshot_all(
        eep_definition=definition,
        source="channels",
        snapshot=snapshot,
        trigger_refs={"battery_voltage"},
    )

    assert [(item.rorg, item.data) for item in contact_telegram] == [("D5", "09")]
    assert [(item.rorg, item.data) for item in voltage_telegram] == [
        ("A5", "8B 96 00 08")
    ]


def test_ftkb_profile_encodes_contact_aliases() -> None:
    definition = load_eep_definition("eltako-ftkb")

    assert encode_semantic_snapshot(
        eep_definition=definition,
        source="channels",
        snapshot={"contact": "open"},
    ).data == "08"

    assert encode_semantic_snapshot(
        eep_definition=definition,
        source="channels",
        snapshot={"contact": "closed"},
    ).data == "09"

    assert encode_semantic_snapshot(
        eep_definition=definition,
        source="channels",
        snapshot={"contact": False},
    ).data == "09"


def _tx_telegram(definition: EEPDefinition) -> TelegramDefinition:
    return next(
        telegram
        for telegram in definition.telegrams
        if telegram.telegram_type_id == "a5-20-06.tx.direction2"
    )


def _decode_fields(data: str, telegram: TelegramDefinition) -> dict[str, int]:
    payload = bytes.fromhex(data)

    return {
        field.name: _get_bits(payload, field.offset, field.size)
        for field in telegram.fields
    }


def _get_bits(payload: bytes, bit_offset: int, bit_size: int) -> int:
    value = 0

    for position in range(bit_size):
        target_bit = bit_offset + position
        byte_index = target_bit // 8
        bit_index = 7 - (target_bit % 8)
        bit_value = (payload[byte_index] >> bit_index) & 0x01
        value = (value << 1) | bit_value

    return value
