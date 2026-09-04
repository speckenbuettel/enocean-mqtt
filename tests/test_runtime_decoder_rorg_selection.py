from __future__ import annotations

from enocean_mqtt.eep.models import (
    ChannelBindingDefinition,
    ChannelDefinition,
    EEPDefinition,
    FieldDefinition,
    TelegramDefinition,
    TelegramIdentity,
    ValueMapping,
)
from enocean_mqtt.eep.runtime_decoder import decode_runtime_with_definition


def test_runtime_decoder_selects_telegram_by_incoming_rorg() -> None:
    definition = EEPDefinition(
        eep="TEST-MULTI-RORG",
        rorg="D5",
        func="00",
        type="01",
        channels=[
            ChannelDefinition(
                name="contact",
                data_type="enum",
                enum=[
                    ValueMapping(value=0, label="open"),
                    ValueMapping(value=1, label="closed"),
                ],
            ),
            ChannelDefinition(
                name="battery_voltage",
                data_type="float",
                unit="V",
            ),
        ],
        telegrams=[
            TelegramDefinition(
                telegram_type_id="test.contact",
                telegram_id=TelegramIdentity(rorg="D5"),
                direction="rx",
                fields=[FieldDefinition(name="contact", offset=0, size=1)],
                channel_bindings=[
                    ChannelBindingDefinition(
                        channel_ref="contact",
                        field_ref="contact",
                    )
                ],
            ),
            TelegramDefinition(
                telegram_type_id="test.voltage",
                telegram_id=TelegramIdentity(rorg="A5"),
                direction="rx",
                fields=[FieldDefinition(name="battery_voltage", offset=0, size=8)],
                channel_bindings=[
                    ChannelBindingDefinition(
                        channel_ref="battery_voltage",
                        field_ref="battery_voltage",
                    )
                ],
            ),
        ],
    )

    decoded = decode_runtime_with_definition(
        eep_definition=definition,
        payload_hex="8B960008",
        rorg="A5",
    )

    assert decoded.telegram_type_id == "test.voltage"
    assert "contact" not in decoded.values
    assert decoded.values["battery_voltage"].raw_value == 0x8B
