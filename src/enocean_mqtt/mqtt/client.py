"""MQTT client wrapper."""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Any, cast

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

MQTTClientType = mqtt.Client
MQTTMessageInfoType = mqtt.MQTTMessageInfo
ReasonCode = Any
MessageCallback = Callable[[str, bytes], None]
MQTT_LOAD_WINDOW_SECONDS = 15 * 60


class MQTTClient:
    """Small MQTT wrapper for enocean-mqtt."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        username: str | None = None,
        password_file: str | None = None,
        keepalive_seconds: int = 30,
        clean_session: bool = True,
        reconnect_initial_delay_seconds: int = 5,
        reconnect_max_delay_seconds: int = 60,
    ) -> None:
        self._client = mqtt.Client(
            callback_api_version=cast(Any, mqtt.CallbackAPIVersion.VERSION2),
            client_id=client_id,
            clean_session=clean_session,
        )

        self.host = host
        self.port = port
        self.client_id = client_id

        self._keepalive_seconds = keepalive_seconds
        self._connected = threading.Event()
        self._on_connect_callback: Callable[[], None] | None = None
        self._subscriptions: dict[str, MessageCallback] = {}
        self._message_load_lock = threading.Lock()
        self._published_message_times: deque[float] = deque()
        self._received_message_times: deque[float] = deque()

        self.reconnects = 0
        self.dropped_publish_attempts = 0
        self._has_connected_once = False
        self._connection_was_interrupted = False

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._client.reconnect_delay_set(
            min_delay=reconnect_initial_delay_seconds,
            max_delay=reconnect_max_delay_seconds,
        )

        if username:
            password = self._read_secret_file(password_file) if password_file else None
            self._client.username_pw_set(username=username, password=password)

    @staticmethod
    def _read_secret_file(path: str | None) -> str | None:
        """Read a secret value from a file."""

        if not path:
            return None

        secret_path = Path(path)
        return secret_path.read_text(encoding="utf-8").strip()

    def _validate_publish_result(
        self,
        result: MQTTMessageInfoType,
        topic: str,
    ) -> bool:
        """Validate MQTT publish result without breaking runtime on transport loss."""

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self._record_message(self._published_message_times)
            return True

        self.dropped_publish_attempts += 1
        self._connection_was_interrupted = True

        logger.warning(
            "MQTT publish dropped for topic %s: rc=%s",
            topic,
            result.rc,
        )
        return False

    def _record_message(self, timestamps: deque[float]) -> None:
        now = monotonic()
        with self._message_load_lock:
            timestamps.append(now)
            self._purge_message_times(now, MQTT_LOAD_WINDOW_SECONDS)

    def _purge_message_times(self, now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        for timestamps in (
            self._published_message_times,
            self._received_message_times,
        ):
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

    def message_load(
        self,
        window_seconds: int = MQTT_LOAD_WINDOW_SECONDS,
    ) -> dict[str, int]:
        """Return MQTT messages observed in a rolling time window."""

        now = monotonic()
        with self._message_load_lock:
            self._purge_message_times(now, window_seconds)
            return {
                "window_seconds": window_seconds,
                "published": len(self._published_message_times),
                "received": len(self._received_message_times),
            }

    def _on_connect(
        self,
        _client: MQTTClientType,
        _userdata: object,
        _flags: object,
        reason_code: ReasonCode,
        _properties: object,
    ) -> None:
        """Handle MQTT connect and reconnect events."""

        if reason_code != mqtt.CONNACK_ACCEPTED:
            self._connected.clear()
            logger.error("MQTT connection failed with reason_code=%s", reason_code)
            return

        if self._has_connected_once:
            self.reconnects += 1

        self._has_connected_once = True

        self._connected.set()

        logger.info("MQTT connection established")

        for topic in list(self._subscriptions.keys()):
            self._client.subscribe(topic, qos=1)

        if self._on_connect_callback:
            self._on_connect_callback()

    def _on_disconnect(
        self,
        _client: MQTTClientType,
        _userdata: object,
        _disconnect_flags: object,
        reason_code: ReasonCode,
        _properties: object,
    ) -> None:
        """Handle MQTT disconnect events."""

        self._connected.clear()

        if reason_code == mqtt.MQTT_ERR_SUCCESS:
            logger.info("MQTT connection closed cleanly")
        else:
            self._connection_was_interrupted = True
            logger.warning(
                "MQTT connection lost with reason_code=%s; waiting for reconnect",
                reason_code,
            )

    def _on_message(
        self,
        _client: MQTTClientType,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        """Dispatch subscribed MQTT messages."""

        self._record_message(self._received_message_times)
        payload = bytes(message.payload)

        callback = self._subscriptions.get(message.topic)

        if callback is not None:
            callback(message.topic, payload)
            return

        for subscription, wildcard_callback in self._subscriptions.items():
            if mqtt.topic_matches_sub(subscription, message.topic):
                wildcard_callback(message.topic, payload)
                return

        logger.debug("No callback registered for topic %s", message.topic)

    def set_on_connect_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked after every successful MQTT connect."""

        self._on_connect_callback = callback

    def consume_connection_interruption(self) -> bool:
        """Return and clear pending MQTT interruption state."""

        if not self._connection_was_interrupted:
            return False

        self._connection_was_interrupted = False
        return True

    def consume_dropped_publish_attempts(self) -> int:
        """Return and reset dropped MQTT publish attempts."""

        dropped_publish_attempts = self.dropped_publish_attempts
        self.dropped_publish_attempts = 0

        return dropped_publish_attempts

    def subscribe(self, topic: str, callback: MessageCallback, qos: int = 1) -> None:
        """Subscribe to a topic and register a message callback."""

        self._subscriptions[topic] = callback

        if self.is_connected():
            self._client.subscribe(topic, qos=qos)

    def is_connected(self) -> bool:
        """Return whether the MQTT client is currently connected."""

        return self._connected.is_set()

    def wait_for_connection(self, timeout_seconds: float = 10.0) -> bool:
        """Wait until the MQTT client is connected."""

        return self._connected.wait(timeout=timeout_seconds)

    def configure_last_will(
        self,
        topic: str,
        payload: str,
        retain: bool = True,
        qos: int = 1,
    ) -> None:
        """Configure MQTT Last Will and Testament."""

        self._client.will_set(topic, payload=payload, qos=qos, retain=retain)

    def configure_last_will_json(
        self,
        topic: str,
        payload: dict[str, Any],
        retain: bool = True,
        qos: int = 1,
    ) -> None:
        """Configure MQTT Last Will and Testament with JSON payload."""

        self._client.will_set(
            topic,
            payload=json.dumps(payload, separators=(",", ":")),
            qos=qos,
            retain=retain,
        )

    def connect(self) -> None:
        """Connect to the MQTT broker."""

        logger.info("Connecting to MQTT broker %s:%s", self.host, self.port)

        self._client.connect(self.host, self.port, keepalive=self._keepalive_seconds)
        self._client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""

        self._client.loop_stop()
        self._client.disconnect()
        self._connected.clear()

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        retain: bool = False,
        qos: int = 0,
    ) -> None:
        """Publish JSON payload."""

        result = self._client.publish(
            topic,
            json.dumps(payload, separators=(",", ":")),
            qos=qos,
            retain=retain,
        )

        self._validate_publish_result(result, topic)

    def publish_value(
        self,
        topic: str,
        value: str | int | float | bool,
        retain: bool = False,
        qos: int = 0,
    ) -> None:
        """Publish plain value payload."""

        result = self._client.publish(
            topic,
            str(value).lower() if isinstance(value, bool) else value,
            qos=qos,
            retain=retain,
        )

        self._validate_publish_result(result, topic)

    def clear_retained_topic(
        self,
        topic: str,
        qos: int = 1,
    ) -> None:
        """Delete retained MQTT topic by publishing empty retained payload."""

        result = self._client.publish(
            topic,
            payload="",
            qos=qos,
            retain=True,
        )

        self._validate_publish_result(result, topic)
