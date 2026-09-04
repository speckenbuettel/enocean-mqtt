from __future__ import annotations

from typing import Any, cast

from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.gateway.orchestrator import GatewayOrchestrator
from enocean_mqtt.gateway.publisher import DevicePublisher
from enocean_mqtt.replay.models import ReplayTelegram


class RecordingMQTTClient:
    def __init__(self) -> None:
        self.json_messages: dict[str, dict[str, Any]] = {}
        self.value_messages: dict[str, dict[str, Any]] = {}

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        retain: bool = False,
    ) -> None:
        self.json_messages[topic] = {
            "payload": payload,
            "retain": retain,
        }

    def publish_value(
        self,
        topic: str,
        value: Any,
        retain: bool = False,
    ) -> None:
        self.value_messages[topic] = {
            "value": value,
            "retain": retain,
        }

    def clear_retained_topic(self, topic: str) -> None:
        pass


def test_gateway_pipeline_publishes_registry_v3_channel_metadata() -> None:
    device = Device(
        device_id="059AD109",
        device_name="A5-20-06 Test Device",
        alias="a5_20_06_test",
        eep="A5-20-06",
    )

    mqtt = RecordingMQTTClient()
    publisher = DevicePublisher(
        mqtt_client=cast(Any, mqtt),
        base_topic="enocean",
        device_topic_identifier="both",
    )
    orchestrator = GatewayOrchestrator(
        registry=DeviceRegistry([device]),
        publisher=publisher,
    )

    telegram = ReplayTelegram(
        telegram_id=1,
        timestamp="2025-06-13T06:16:29.764+02:00",
        protocol="enocean",
        telegram_type="0",
        direction="rx",
        eno_id="059AD109",
        eno_rorg="A5",
        eno_data="28834BE8",
        eno_rssi="-83",
        raw_frame_data=None,
        raw_apdu_data=None,
        properties={},
        status="00",
    )

    assert orchestrator.process_telegram(telegram) is True

    channel_state = mqtt.json_messages[
        "enocean/device/059AD109/channel/feed_temperature/state"
    ]["payload"]
    channel_value = mqtt.value_messages[
        "enocean/device/059AD109/channel/feed_temperature/value"
    ]["value"]
    aggregate_state = mqtt.json_messages[
        "enocean/device/059AD109/state"
    ]["payload"]

    assert channel_value == 37.5

    assert channel_state["value"] == 37.5
    assert channel_state["unit"] == "°C"
    assert channel_state["semantic_role"] == "climate.supply_temperature"
    assert channel_state["object_type"] == "measurement"
    assert "raw_value" not in channel_state

    feed_temperature = aggregate_state["channels"]["feed_temperature"]
    assert feed_temperature["value"] == 37.5
    assert feed_temperature["unit"] == "°C"
    assert feed_temperature["semantic_role"] == "climate.supply_temperature"
    assert feed_temperature["object_type"] == "measurement"
    assert "raw_value" not in feed_temperature

    local_temperature_setpoint = aggregate_state["channels"][
        "local_temperature_setpoint"
    ]
    assert local_temperature_setpoint["value"] == 1.5
    assert local_temperature_setpoint["unit"] == "°C"
    assert local_temperature_setpoint["semantic_role"] == "climate.temperature"
    assert local_temperature_setpoint["object_type"] == "setpoint"

    assert "local_offset" not in aggregate_state["channels"]
    assert "local_ambient_temperature" not in aggregate_state["channels"]

    assert mqtt.json_messages[
        "enocean/alias/a5_20_06_test/channel/feed_temperature/state"
    ]["payload"]["semantic_role"] == "climate.supply_temperature"
    assert mqtt.value_messages[
        "enocean/alias/a5_20_06_test/channel/feed_temperature/value"
    ]["value"] == 37.5
