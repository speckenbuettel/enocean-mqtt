"""MQTT listener and Registry-v3 TX pipeline for physical devices."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from enocean_mqtt.devices.models import Device
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.devices.tx_profiles import (
    TX_CAPABLE_COMMUNICATION,
    load_tx_definition,
    resolve_device_tx_profile,
)
from enocean_mqtt.eep.models import EEPDefinition
from enocean_mqtt.esp3.radio import RadioERP1Telegram
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.gateway.topics import (
    DeviceTopicIdentifier,
    normalize_alias,
    normalize_base_topic,
    normalize_device_id,
)
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.runtime.event import (
    RadioSendResult,
    RuntimeTelegramEvent,
    tx_event_to_mqtt_payload,
)
from enocean_mqtt.time import build_timestamp_fields
from enocean_mqtt.tx.semantic_aggregator import (
    EncodedTxTelegram,
    SemanticTxAggregator,
)
from enocean_mqtt.virtual_devices.sender_id_registry import DEFAULT_MANUFACTURER_ID
from enocean_mqtt.virtual_devices.teach_in import generate_teach_in_telegram

LOGGER = logging.getLogger(__name__)
TopicNamespace = Literal["device", "alias"]


class DeviceTxRuntimeError(ValueError):
    """Raised when a physical-device TX MQTT message is invalid."""


class DeviceTxRuntime:
    """Resolve, aggregate and encode physical-device MQTT messages."""

    def __init__(
        self,
        *,
        mqtt_client: MQTTClient,
        base_topic: str,
        registry_provider: Callable[[], DeviceRegistry],
        device_topic_identifier: DeviceTopicIdentifier = "device_id",
        status_publisher: GatewayStatusPublisher | None = None,
        controller_mapping_path: str | Path = "config/device-controller-mappings.json",
        radio_sender: Callable[[RadioERP1Telegram], RadioSendResult | None] | None = None,
        manufacturer_id: str = DEFAULT_MANUFACTURER_ID,
        tx_event_callback: Callable[[RuntimeTelegramEvent], None] | None = None,
    ) -> None:
        self._mqtt_client = mqtt_client
        self._base_topic = normalize_base_topic(base_topic)
        self._registry_provider = registry_provider
        self._device_topic_identifier = device_topic_identifier
        self._status_publisher = status_publisher
        self._controller_mapping_path = Path(controller_mapping_path)
        self._radio_sender = radio_sender
        self._manufacturer_id = manufacturer_id.strip().upper()
        self._tx_event_callback = tx_event_callback
        self._subscriptions: set[str] = set()
        self._aggregator = SemanticTxAggregator(
            on_encoded=self._handle_encoded,
            on_error=self._handle_aggregation_error,
        )

    def register(self) -> None:
        """Subscribe to physical-device message/set and command topics."""

        topics = [
            f"{self._base_topic}/device/+/message/+/set",
            f"{self._base_topic}/device/+/command",
        ]
        if self._device_topic_identifier in {"alias", "both"}:
            topics.append(f"{self._base_topic}/alias/+/message/+/set")
            topics.append(f"{self._base_topic}/alias/+/command")

        for topic in topics:
            if topic in self._subscriptions:
                continue
            callback = (
                self._handle_command_message
                if topic.endswith("/command")
                else self._handle_message_set
            )
            self._mqtt_client.subscribe(topic, callback, qos=1)
            self._subscriptions.add(topic)
            LOGGER.debug("Registered physical device TX topic: %s", topic)

    def teach_in(
        self,
        device_id: str,
        command_payload: dict[str, Any] | None = None,
    ) -> None:
        """Transmit the teach-in telegram for one TX-capable physical device."""

        device = self._resolve_device(namespace="device", identifier=device_id)
        self._validate_device_tx_capable(device)
        tx_profile = resolve_device_tx_profile(
            device,
            controller_mapping_path=self._controller_mapping_path,
        )
        tx_definition = load_tx_definition(tx_profile)
        sender_id = _required_sender_id(device)
        normalized_device_id = normalize_device_id(device.device_id)
        encoded = _teach_in_telegram(
            tx_definition=tx_definition,
            payload=dict(command_payload or {}),
            sender_id=sender_id,
            destination_id=normalized_device_id,
            manufacturer_id=self._manufacturer_id,
        )
        self._handle_encoded(normalized_device_id, [encoded])

        if self._status_publisher is not None:
            self._status_publisher.publish_log(
                level="info",
                component="device-tx",
                message="Physical device teach-in command sent",
                device_id=normalized_device_id,
                alias=device.alias,
                communication=device.communication,
                sender_id=sender_id,
                rx_profile=device.registry_profile,
                tx_profile=tx_profile,
            )

    def set_value(self, device_id: str, message: str, value: Any) -> None:
        """Submit one physical-device message value for TX aggregation."""

        device = self._resolve_device(namespace="device", identifier=device_id)
        self._submit_message(device=device, message=message, value=value)

    def _handle_message_set(self, topic: str, payload: bytes) -> None:
        try:
            namespace, identifier, message = self._parse_message_set_topic(topic)
            payload_text = payload.decode("utf-8", errors="replace").strip()
            if not payload_text:
                LOGGER.debug("Ignoring empty physical device TX payload on %s", topic)
                return

            device = self._resolve_device(namespace=namespace, identifier=identifier)
            value = _message_value(_parse_payload(payload_text))
            tx_profile = self._submit_message(
                device=device,
                message=message,
                value=value,
            )
            device_id = normalize_device_id(device.device_id)
            sender_id = _required_sender_id(device)

            LOGGER.debug(
                "Accepted physical device TX message: device_id=%s tx_profile=%s message=%s",
                device_id,
                tx_profile,
                message,
            )
            if self._status_publisher is not None:
                self._status_publisher.publish_log(
                    level="info",
                    component="device-tx",
                    message="Physical device TX message accepted for aggregation",
                    device_id=device_id,
                    alias=device.alias,
                    communication=device.communication,
                    sender_id=sender_id,
                    rx_profile=device.registry_profile,
                    tx_profile=tx_profile,
                    message_name=message,
                    payload=value,
                    raw_payload=payload_text,
                    topic=topic,
                )
        except Exception as exc:
            self._publish_invalid(topic=topic, exc=exc)

    def _handle_command_message(self, topic: str, payload: bytes) -> None:
        try:
            namespace, identifier = self._parse_command_topic(topic)
            command, command_payload = _parse_command_payload(payload)

            if command != "teach_in":
                raise DeviceTxRuntimeError(f"Unsupported physical device command: {command}")

            device = self._resolve_device(namespace=namespace, identifier=identifier)
            self.teach_in(device.device_id, command_payload)
        except Exception as exc:
            self._publish_invalid(topic=topic, exc=exc)

    def _submit_message(
        self,
        *,
        device: Device,
        message: str,
        value: Any,
    ) -> str:
        self._validate_device_tx_capable(device)
        tx_profile = resolve_device_tx_profile(
            device,
            controller_mapping_path=self._controller_mapping_path,
        )
        tx_definition = load_tx_definition(tx_profile)
        self._validate_message(
            message=message,
            tx_profile=tx_profile,
            tx_definition=tx_definition,
        )
        sender_id = _required_sender_id(device)
        device_id = normalize_device_id(device.device_id)

        self._aggregator.submit(
            key=device_id,
            semantic_ref=message,
            value=value,
            eep_definition=tx_definition,
            source="messages",
            sender_id=sender_id,
            destination_id=device_id,
            port="physical-device",
        )
        return tx_profile

    def _parse_message_set_topic(
        self,
        topic: str,
    ) -> tuple[TopicNamespace, str, str]:
        prefix = f"{self._base_topic}/"
        if not topic.startswith(prefix):
            raise DeviceTxRuntimeError(f"Invalid physical device TX topic: {topic}")

        parts = topic[len(prefix) :].split("/")
        if len(parts) != 5 or parts[2] != "message" or parts[4] != "set":
            raise DeviceTxRuntimeError(f"Invalid physical device TX topic: {topic}")

        namespace = parts[0]
        if namespace not in {"device", "alias"}:
            raise DeviceTxRuntimeError(f"Invalid physical device TX namespace: {namespace}")

        identifier = parts[1]
        message = parts[3].strip()
        if not identifier:
            raise DeviceTxRuntimeError("Physical device TX topic is missing device identifier")
        if not message:
            raise DeviceTxRuntimeError("Physical device TX topic is missing message name")
        return cast(TopicNamespace, namespace), identifier, message

    def _parse_command_topic(
        self,
        topic: str,
    ) -> tuple[TopicNamespace, str]:
        prefix = f"{self._base_topic}/"
        if not topic.startswith(prefix):
            raise DeviceTxRuntimeError(f"Invalid physical device command topic: {topic}")

        parts = topic[len(prefix) :].split("/")
        if len(parts) != 3 or parts[2] != "command":
            raise DeviceTxRuntimeError(f"Invalid physical device command topic: {topic}")

        namespace = parts[0]
        if namespace not in {"device", "alias"}:
            raise DeviceTxRuntimeError(f"Invalid physical device TX namespace: {namespace}")

        identifier = parts[1]
        if not identifier:
            raise DeviceTxRuntimeError("Physical device command topic is missing device identifier")

        return cast(TopicNamespace, namespace), identifier

    def _resolve_device(
        self,
        *,
        namespace: TopicNamespace,
        identifier: str,
    ) -> Device:
        registry = self._registry_provider()
        if namespace == "device":
            device = registry.get_by_device_id(normalize_device_id(identifier))
        else:
            alias = normalize_alias(identifier)
            device = next(
                (
                    candidate
                    for candidate in registry.devices
                    if candidate.alias is not None and normalize_alias(candidate.alias) == alias
                ),
                None,
            )
        if device is None:
            raise DeviceTxRuntimeError(
                f"Unknown physical device TX target: {namespace}/{identifier}"
            )
        return device

    @staticmethod
    def _validate_device_tx_capable(device: Device) -> None:
        if not device.enabled:
            raise DeviceTxRuntimeError(f"Physical device is disabled: {device.device_id}")
        if device.communication not in TX_CAPABLE_COMMUNICATION:
            raise DeviceTxRuntimeError(
                "Physical device is not TX-capable: "
                f"{device.device_id} communication={device.communication}"
            )

    @staticmethod
    def _validate_message(
        *,
        message: str,
        tx_profile: str,
        tx_definition: EEPDefinition,
    ) -> None:
        available = {item.name for item in tx_definition.messages}
        if message not in available:
            raise DeviceTxRuntimeError(
                f"Unknown TX message for profile {tx_profile}: {message}; "
                f"available={', '.join(sorted(available))}"
            )

    def _handle_encoded(
        self,
        device_id: str,
        telegrams: list[EncodedTxTelegram],
    ) -> None:
        for encoded in telegrams:
            send_result = _coerce_send_result(
                self._radio_sender(_radio_erp1_from_encoded(encoded))
                if self._radio_sender is not None
                else None,
                sender_configured=self._radio_sender is not None,
            )

            event = _runtime_event(encoded, send_result)
            if self._tx_event_callback is not None:
                self._tx_event_callback(event)
            self._mqtt_client.publish_json(
                f"{self._base_topic}/busmonitor/tx/event",
                _runtime_event_payload(event),
                qos=0,
                retain=False,
            )
            self._mqtt_client.publish_value(
                f"{self._base_topic}/busmonitor/tx/raw/telegram",
                encoded.raw_telegram,
                qos=0,
                retain=False,
            )
            LOGGER.debug(
                "Encoded physical device TX telegram: device_id=%s telegram_type=%s raw=%s",
                device_id,
                encoded.telegram_type_id,
                encoded.raw_telegram,
            )
            if send_result.transmission == "failed" and self._status_publisher is not None:
                self._status_publisher.publish_error(
                    component="device-tx",
                    message="Physical device TX transmission failed",
                    device_id=device_id,
                    sender_id=encoded.sender_id,
                    destination_id=encoded.destination_id,
                    telegram_type_id=encoded.telegram_type_id,
                    rorg=encoded.rorg,
                    data=encoded.data,
                    raw_telegram=encoded.raw_telegram,
                    error=send_result.error,
                )

    def _handle_aggregation_error(self, device_id: str, exc: Exception) -> None:
        LOGGER.warning("Physical device TX aggregation failed for %s: %s", device_id, exc)
        if self._status_publisher is not None:
            self._status_publisher.publish_error(
                component="device-tx",
                message="Physical device TX aggregation failed",
                device_id=device_id,
                error=str(exc),
            )

    def _publish_invalid(self, *, topic: str, exc: Exception) -> None:
        LOGGER.warning("Ignoring invalid physical device TX message on %s: %s", topic, exc)
        if self._status_publisher is not None:
            self._status_publisher.publish_error(
                component="device-tx",
                message="Invalid physical device TX message",
                topic=topic,
                error=str(exc),
            )


def _parse_command_payload(payload: bytes) -> tuple[str, dict[str, Any]]:
    payload_text = payload.decode("utf-8", errors="replace").strip()

    if not payload_text:
        raise DeviceTxRuntimeError("Physical device command payload is empty")

    if payload_text.startswith("{"):
        parsed = json.loads(payload_text)
        if not isinstance(parsed, dict):
            raise DeviceTxRuntimeError("Physical device command JSON must be an object")
        command = parsed.get("command")
        if not isinstance(command, str) or not command.strip():
            raise DeviceTxRuntimeError("Physical device command JSON requires command")
        return command.strip(), parsed

    return payload_text, {}


def _teach_in_telegram(
    *,
    tx_definition: EEPDefinition,
    payload: dict[str, Any],
    sender_id: str,
    destination_id: str,
    manufacturer_id: str,
) -> EncodedTxTelegram:
    metadata = generate_teach_in_telegram(
        sender_id=sender_id,
        eep_definition=tx_definition,
        manufacturer_id=str(payload.get("manufacturer_id", manufacturer_id)),
    )
    data = str(metadata["payload"]).replace(" ", "").upper()
    return EncodedTxTelegram(
        rorg=str(metadata["rorg"]).upper(),
        data=" ".join(data[index : index + 2] for index in range(0, len(data), 2)),
        sender_id=sender_id,
        destination_id=destination_id,
        status=str(metadata.get("status", "00")).replace(" ", "").upper(),
        telegram_type_id="teach_in",
        port="physical-device",
    )


def _parse_payload(payload_text: str) -> Any:
    if payload_text.startswith("{") or payload_text.startswith("["):
        return json.loads(payload_text)
    return payload_text


def _message_value(payload: Any) -> Any:
    if isinstance(payload, dict):
        if "value" not in payload:
            raise DeviceTxRuntimeError("JSON TX payload must contain a 'value' field")
        return payload["value"]
    if isinstance(payload, list):
        raise DeviceTxRuntimeError("Physical device TX payload cannot be a JSON array")
    return payload


def _required_sender_id(device: Device) -> str:
    if not device.sender_id:
        raise DeviceTxRuntimeError(
            f"TX-capable physical device has no assigned sender_id: {device.device_id}"
        )
    return device.sender_id.upper()


def _radio_erp1_from_encoded(encoded: EncodedTxTelegram) -> RadioERP1Telegram:
    return RadioERP1Telegram(
        rorg=encoded.rorg,
        data=encoded.data.replace(" ", ""),
        sender_id=encoded.sender_id,
        status=encoded.status,
        destination_id=encoded.destination_id,
    )


def _coerce_send_result(
    result: RadioSendResult | None,
    *,
    sender_configured: bool,
) -> RadioSendResult:
    if result is not None:
        return result
    return RadioSendResult(
        interface_id=None,
        transmission="accepted" if sender_configured else "disabled",
    )


def _runtime_event(
    encoded: EncodedTxTelegram,
    send_result: RadioSendResult,
) -> RuntimeTelegramEvent:
    timestamps = build_timestamp_fields()
    return RuntimeTelegramEvent(
        timestamp_local=str(timestamps["timestamp_local"]),
        timestamp_unix=float(timestamps["timestamp_unix"]),
        direction="tx",
        runtime_mode="live",
        sender_id=encoded.sender_id,
        destination_id=encoded.destination_id,
        rorg=encoded.rorg,
        data=encoded.data,
        erp1_status=encoded.status,
        contains_teach_in=encoded.telegram_type_id == "teach_in",
        raw_telegram=encoded.raw_telegram,
        subtelegram_count=1,
        rssi_dbm=None,
        port=encoded.port,
        interface_id=send_result.interface_id,
        transmission=send_result.transmission,
    )


def _runtime_event_payload(event: RuntimeTelegramEvent) -> dict[str, Any]:
    return tx_event_to_mqtt_payload(event)
