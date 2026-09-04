from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.runtime.event import RuntimeTelegramEvent, tx_event_to_mqtt_payload
from enocean_mqtt.time import build_timestamp_fields


def test_mqtt_timestamps_use_millisecond_precision() -> None:
    timestamps = build_timestamp_fields(
        datetime(2026, 8, 27, 12, 34, 56, 123789, tzinfo=UTC)
    )

    local_timestamp = str(timestamps["timestamp_local"])
    assert local_timestamp[local_timestamp.rfind(".") + 1 :][:3] == "123"
    assert len(local_timestamp[local_timestamp.rfind(".") + 1 :].split("+")[0]) == 3
    assert timestamps["timestamp_unix"] == 1787834096.124


def test_tx_event_payload_matches_canonical_mqtt_model() -> None:
    event = RuntimeTelegramEvent(
        timestamp_local="2025-06-13T06:16:29.764+02:00",
        timestamp_unix=1749788189.764,
        direction="tx",
        runtime_mode="live",
        rorg="A5",
        sender_id="059AD109",
        destination_id="FFFFFFFF",
        data="00 C8 FA 0A",
        erp1_status="00",
        raw_telegram="A5 00 C8 FA 0A 05 9A D1 09 00",
        subtelegram_count=1,
        rssi_dbm=-83,
        interface_id="usb300",
        port="virtual-device",
        transmission="accepted",
    )

    assert tx_event_to_mqtt_payload(event) == {
        "timestamp_local": "2025-06-13T06:16:29.764+02:00",
        "timestamp_unix": 1749788189.764,
        "direction": "tx",
        "rorg": "A5",
        "sender_id": "059AD109",
        "destination_id": "FFFFFFFF",
        "data": "00 C8 FA 0A",
        "teach_in": False,
        "erp1_status": "00",
        "raw_telegram": "A5 00 C8 FA 0A 05 9A D1 09 00",
        "subtelegram_count": 1,
        "interface_id": "usb300",
        "port": "virtual-device",
        "transmission": "accepted",
    }


def test_gateway_health_uses_nested_enocean_model() -> None:
    mqtt = FakeMQTTClient()
    publisher = GatewayStatusPublisher(
        mqtt_client=mqtt,  # type: ignore[arg-type]
        base_topic="enocean",
        source="runtime",
        runtime_mode="live",
        default_interface="usb300",
        enocean_tx_enabled=True,
    )
    publisher.set_enocean_interface_status(
        interface_id="usb300",
        connected=True,
        port="/dev/ttyUSB0",
        base_id="FF92A700",
        tx_enabled=True,
        transport_status="connected",
        metrics={"accepted_radio_erp1_telegrams": 4},
    )
    publisher.set_web_status(
        web_api={"enabled": True, "operational": True, "host": "0.0.0.0", "port": 8001},
        web_ui={"enabled": True, "operational": True, "route": "/", "static_assets": True},
    )

    publisher.publish_health(mqtt_connected=True)

    health = next(
        payload
        for topic, payload, _retain in mqtt.json_messages
        if topic.endswith("/health")
    )
    assert health["enocean"] == {
        "connected": True,
        "tx_enabled": True,
        "default_interface": "usb300",
        "interfaces": [
            {
                "interface_id": "usb300",
                "connected": True,
                "tx_enabled": True,
                "port": "/dev/ttyUSB0",
                "base_id": "FF92A700",
                "metrics": {"accepted_radio_erp1_telegrams": 4},
            }
        ],
    }
    assert "enocean_interface" not in health
    assert "enocean_interfaces" not in health
    assert health["mqtt"]["message_load_15mins"] == {"published": 401, "received": 10}
    assert health["web_api"] == {
        "enabled": True,
        "operational": True,
        "host": "0.0.0.0",
        "port": 8001,
    }
    assert health["web_ui"] == {
        "enabled": True,
        "operational": True,
        "route": "/",
        "static_assets": True,
    }


class FakeMQTTClient:
    host = "localhost"
    port = 1883
    client_id = "test"
    reconnects = 0

    def __init__(self) -> None:
        self.json_messages: list[tuple[str, dict[str, Any], bool]] = []

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        retain: bool = False,
        qos: int = 0,
    ) -> None:
        del qos
        self.json_messages.append((topic, payload, retain))

    def publish_value(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def message_load(self, window_seconds: int) -> dict[str, int]:
        assert window_seconds == 15 * 60
        return {"window_seconds": window_seconds, "published": 401, "received": 10}
