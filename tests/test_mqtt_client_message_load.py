from types import SimpleNamespace

import enocean_mqtt.mqtt.client as mqtt_client_module
from enocean_mqtt.mqtt.client import MQTTClient


def test_clean_session_is_passed_to_paho(monkeypatch) -> None:
    captured = {}

    class FakePahoClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def reconnect_delay_set(self, **_kwargs):
            return None

    monkeypatch.setattr(mqtt_client_module.mqtt, "Client", FakePahoClient)

    MQTTClient("broker", 1883, "test-client", clean_session=False)

    assert captured["clean_session"] is False


def test_message_load_counts_successful_publishes_and_received_messages() -> None:
    client = MQTTClient("broker", 1883, "test-client")
    client._client.publish = lambda *args, **kwargs: SimpleNamespace(rc=0)  # type: ignore[assignment]

    client.publish_value("test/out", "value")
    message = SimpleNamespace(topic="test/in", payload=b"value")
    client._on_message(client._client, None, message)  # type: ignore[arg-type]

    assert client.message_load() == {
        "window_seconds": 900,
        "published": 1,
        "received": 1,
    }


def test_message_load_expires_messages_outside_requested_window(
    monkeypatch,
) -> None:
    now = 1000.0
    monkeypatch.setattr(mqtt_client_module, "monotonic", lambda: now)
    client = MQTTClient("broker", 1883, "test-client")
    client._record_message(client._published_message_times)

    now = 1016.0

    assert client.message_load(window_seconds=15)["published"] == 0
