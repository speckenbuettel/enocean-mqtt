from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.devices.tx_runtime import DeviceTxRuntime
from enocean_mqtt.gateway.publisher import DevicePublisher
from enocean_mqtt.virtual_devices.models import VirtualDevice
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry
from enocean_mqtt.virtual_devices.runtime import VirtualDeviceRuntime, VirtualDeviceState


class FakeMQTTClient:
    def __init__(self) -> None:
        self.json_messages: list[tuple[str, dict[str, Any], bool]] = []
        self.value_messages: list[tuple[str, Any, bool]] = []
        self.subscriptions: dict[str, Any] = {}

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        _ = qos
        self.json_messages.append((topic, payload, retain))

    def publish_value(
        self,
        topic: str,
        value: Any,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        _ = qos
        self.value_messages.append((topic, value, retain))

    def clear_retained_topic(self, topic: str) -> None:
        self.value_messages.append((topic, None, True))

    def subscribe(self, topic: str, callback: Any, qos: int = 0) -> None:
        _ = qos
        self.subscriptions[topic] = callback


@dataclass
class FakeChannel:
    value: Any
    unit: str | None = None
    semantic_role: str | None = None
    object_type: str | None = None
    definition: Any = None


@dataclass
class FakeDecoded:
    values: dict[str, FakeChannel]


def test_device_publisher_exposes_current_device_state_copy() -> None:
    mqtt_client = FakeMQTTClient()
    publisher = DevicePublisher(
        mqtt_client=mqtt_client,  # type: ignore[arg-type]
        base_topic="enocean",
    )
    device = Device(
        device_id="0x052523B1",
        device_name="TH Sensor",
        eep="A5-04-02",
        profile="A5-04-02",
    )
    decoded = FakeDecoded(
        values={
            "temperature": FakeChannel(
                value=21.5,
                unit="°C",
                semantic_role="climate.temperature.measurement",
                object_type="measurement",
            )
        }
    )

    publisher.publish_decoded_telegram(
        device=device,
        decoded=decoded,
        timestamp="2026-06-25T12:00:00+00:00",
    )

    state = publisher.get_device_state("052523B1")
    assert state is not None
    assert state["device_id"] == "052523B1"
    assert state["channels"]["temperature"]["value"] == 21.5

    state["channels"]["temperature"]["value"] = 99.0
    state_again = publisher.get_device_state("052523B1")
    assert state_again is not None
    assert state_again["channels"]["temperature"]["value"] == 21.5


def test_device_publisher_exposes_all_device_states_as_copies() -> None:
    mqtt_client = FakeMQTTClient()
    publisher = DevicePublisher(
        mqtt_client=mqtt_client,  # type: ignore[arg-type]
        base_topic="enocean",
    )
    device = Device(device_id="052523B1", device_name="TH Sensor")
    decoded = FakeDecoded(values={"temperature": FakeChannel(value=22.0)})

    publisher.publish_decoded_telegram(
        device=device,
        decoded=decoded,
        timestamp="2026-06-25T12:00:00+00:00",
    )

    states = publisher.get_device_states()
    assert set(states) == {"052523B1"}
    states["052523B1"]["channels"]["temperature"]["value"] = 99.0

    state_again = publisher.get_device_state("052523B1")
    assert state_again is not None
    assert state_again["channels"]["temperature"]["value"] == 22.0


def test_virtual_device_runtime_exposes_current_device_state_projection() -> None:
    virtual_device = VirtualDevice(
        virtual_device_id="virtual_sensor",
        sender_id="FF800001",
        eep="A5-04-02",
        profile="A5-04-02",
        channels=["temperature"],
        description="Virtual Sensor",
    )
    runtime = VirtualDeviceRuntime(
        mqtt_client=FakeMQTTClient(),  # type: ignore[arg-type]
        base_topic="enocean",
        registry=VirtualDeviceRegistry([virtual_device]),
    )
    runtime._states["virtual_sensor"] = VirtualDeviceState(  # noqa: SLF001
        values={"temperature": "21.5"},
        channel_updates={"temperature": "2026-06-25T12:00:00+00:00"},
    )

    state = runtime.get_device_state("virtual_sensor")

    assert state is not None
    assert state["virtual_device_id"] == "virtual_sensor"
    assert state["sender_id"] == "FF800001"
    assert state["last_update"] == "2026-06-25T12:00:00+00:00"
    assert state["channels"]["temperature"]["value"] == 21.5


def test_virtual_device_runtime_returns_only_states_with_values() -> None:
    virtual_device = VirtualDevice(
        virtual_device_id="virtual_sensor",
        sender_id="FF800001",
        eep="A5-04-02",
        profile="A5-04-02",
        channels=["temperature"],
    )
    runtime = VirtualDeviceRuntime(
        mqtt_client=FakeMQTTClient(),  # type: ignore[arg-type]
        base_topic="enocean",
        registry=VirtualDeviceRegistry([virtual_device]),
    )
    runtime._states["virtual_sensor"] = VirtualDeviceState()  # noqa: SLF001

    assert runtime.get_device_state("virtual_sensor") is None
    assert runtime.get_device_states() == {}


def test_virtual_device_command_teach_in_publishes_and_sends_telegram() -> None:
    mqtt_client = FakeMQTTClient()
    sent: list[Any] = []
    virtual_device = VirtualDevice(
        virtual_device_id="virtual_contact",
        sender_id="FF800002",
        eep="D5-00-01",
        profile="D5-00-01",
        channels=["contact"],
        teach_in_telegram={
            "method": "1bs_teach_in",
            "rorg": "D5",
            "eep": "D5-00-01",
            "sender_id": "FF800002",
            "payload": "08",
        },
    )
    runtime = VirtualDeviceRuntime(
        mqtt_client=mqtt_client,  # type: ignore[arg-type]
        base_topic="enocean",
        registry=VirtualDeviceRegistry([virtual_device]),
        radio_sender=sent.append,
    )

    runtime.register()
    mqtt_client.subscriptions["enocean/virtual/virtual_contact/command"](
        "enocean/virtual/virtual_contact/command",
        b'{"command": "teach_in"}',
    )

    assert len(sent) == 1
    assert sent[0].raw_telegram == "D508FF80000200"
    assert mqtt_client.value_messages[-1] == (
        "enocean/busmonitor/tx/raw/telegram",
        "D5 08 FF 80 00 02 00",
        False,
    )
    tx_events = [
        payload
        for topic, payload, _retain in mqtt_client.json_messages
        if topic == "enocean/busmonitor/tx/event"
    ]
    assert tx_events[-1]["sender_id"] == "FF800002"
    assert tx_events[-1]["rorg"] == "D5"
    assert tx_events[-1]["data"] == "08"



def test_physical_device_command_teach_in_publishes_and_sends_telegram() -> None:
    mqtt_client = FakeMQTTClient()
    sent: list[Any] = []
    metric_events: list[Any] = []
    device = Device(
        device_id="05234567",
        device_name="Radiator Thermostat",
        communication="bidirectional_eep",
        eep="A5-20-06",
        profile="A5-20-06",
        sender_id="FF92A703",
    )
    runtime = DeviceTxRuntime(
        mqtt_client=mqtt_client,  # type: ignore[arg-type]
        base_topic="enocean",
        registry_provider=lambda: DeviceRegistry([device]),
        radio_sender=sent.append,
        manufacturer_id="760",
        tx_event_callback=metric_events.append,
    )

    runtime.register()
    mqtt_client.subscriptions["enocean/device/+/command"](
        "enocean/device/05234567/command",
        b'{"command": "teach_in"}',
    )

    assert len(sent) == 1
    assert len(metric_events) == 1
    assert metric_events[0].direction == "tx"
    assert sent[0].raw_telegram == "A580376080FF92A70300"
    assert sent[0].destination_id == "05234567"
    assert mqtt_client.value_messages[-1] == (
        "enocean/busmonitor/tx/raw/telegram",
        "A5 80 37 60 80 FF 92 A7 03 00",
        False,
    )
    tx_events = [
        payload
        for topic, payload, _retain in mqtt_client.json_messages
        if topic == "enocean/busmonitor/tx/event"
    ]
    assert tx_events[-1]["sender_id"] == "FF92A703"
    assert tx_events[-1]["destination_id"] == "05234567"
    assert tx_events[-1]["rorg"] == "A5"
    assert tx_events[-1]["data"] == "80 37 60 80"
