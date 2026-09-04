"""Virtual device MQTT runtime using the Registry v3 TX encoder."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Final, cast

from enocean_mqtt.eep.json_registry import load_eep_definition
from enocean_mqtt.eep.models import ChannelDefinition, EEPDefinition
from enocean_mqtt.eep.runtime_encoder import (
    EEPEncodeError,
    encode_semantic_snapshot_all,
)
from enocean_mqtt.eep.semantic_mapping import derived_value
from enocean_mqtt.esp3.radio import RadioERP1Telegram
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.runtime.event import (
    RadioSendResult,
    RuntimeTelegramEvent,
    tx_event_to_mqtt_payload,
)
from enocean_mqtt.storage.sqlite_store import SQLiteRuntimeStore
from enocean_mqtt.time import build_timestamp_fields
from enocean_mqtt.virtual_devices.models import VirtualDevice
from enocean_mqtt.virtual_devices.registry import VirtualDeviceRegistry

LOGGER = logging.getLogger(__name__)
SUPPORTED_RORGS = {"F6", "D5", "A5"}
DEFAULT_AGGREGATION_WINDOW_SECONDS = 10.0
MIN_AGGREGATION_WINDOW_SECONDS = 1.0


class VirtualDeviceRuntimeError(ValueError):
    """Raised when a virtual device operation fails."""


@dataclass(slots=True)
class EncodedVirtualTelegram:
    """Encoded ERP1 telegram for a virtual device."""

    rorg: str
    data: str
    sender_id: str
    status: str
    raw_telegram: str
    teach_in: bool = False

    @classmethod
    def from_teach_in(cls, teach_in_telegram: dict[str, Any]) -> EncodedVirtualTelegram:
        """Build an encoded virtual telegram from persisted teach-in metadata."""

        try:
            rorg = str(teach_in_telegram["rorg"]).strip().upper()
            data = str(teach_in_telegram["payload"]).replace(" ", "").upper()
            sender_id = str(teach_in_telegram["sender_id"]).replace(" ", "").upper()
        except KeyError as exc:
            raise VirtualDeviceRuntimeError(
                f"Teach-in telegram is missing field: {exc.args[0]}"
            ) from exc

        status = str(teach_in_telegram.get("status", "00")).replace(" ", "").upper()

        return cls(
            rorg=rorg,
            data=data,
            sender_id=sender_id,
            status=status,
            raw_telegram=_format_erp1_telegram(
                rorg=rorg,
                data=data,
                sender_id=sender_id,
                status=status,
            ),
            teach_in=True,
        )

    def to_radio_erp1(self) -> RadioERP1Telegram:
        """Return this encoded telegram as a RADIO_ERP1 transport payload."""

        return RadioERP1Telegram(
            rorg=self.rorg,
            data=self.data,
            sender_id=self.sender_id,
            status=self.status,
        )

    def to_runtime_event(self, send_result: RadioSendResult) -> RuntimeTelegramEvent:
        timestamp_fields = build_timestamp_fields()

        return RuntimeTelegramEvent(
            timestamp_local=str(timestamp_fields["timestamp_local"]),
            timestamp_unix=float(timestamp_fields["timestamp_unix"]),
            direction="tx",
            runtime_mode="live",
            sender_id=self.sender_id,
            destination_id="FFFFFFFF",
            rorg=self.rorg,
            data=self.data,
            erp1_status=self.status,
            contains_teach_in=self.teach_in,
            raw_telegram=self.raw_telegram,
            subtelegram_count=1,
            rssi_dbm=None,
            port="virtual-device",
            interface_id=send_result.interface_id,
            transmission=send_result.transmission,
        )


@dataclass(slots=True)
class VirtualDeviceState:
    """Runtime state cache for one virtual device."""

    values: dict[str, str] = dataclass_field(default_factory=dict)
    channel_updates: dict[str, str] = dataclass_field(default_factory=dict)
    pending_channels: set[str] = dataclass_field(default_factory=set)
    timer: threading.Timer | None = None


class VirtualDeviceRuntime:
    """Runtime for MQTT-visible virtual EnOcean devices.

    The runtime acts as an adapter from MQTT channel topics to the generic
    Registry v3 encoder. It owns MQTT subscriptions, state aggregation and TX
    publication, but it no longer performs bit-level telegram encoding itself.
    """

    def __init__(
        self,
        *,
        mqtt_client: MQTTClient,
        base_topic: str,
        registry: VirtualDeviceRegistry,
        sqlite_store: SQLiteRuntimeStore | None = None,
        radio_sender: Callable[[RadioERP1Telegram], RadioSendResult | None] | None = None,
        tx_event_callback: Callable[[RuntimeTelegramEvent], None] | None = None,
    ) -> None:
        self._mqtt_client = mqtt_client
        self._base_topic = base_topic.rstrip("/")
        self.registry = registry
        self._sqlite_store = sqlite_store
        self._radio_sender = radio_sender
        self._subscriptions: set[str] = set()
        self._tx_event_callback = tx_event_callback
        self._states: dict[str, VirtualDeviceState] = {}
        self._lock = threading.RLock()

    def register(self) -> None:
        for device in self.registry.devices:
            if device.enabled:
                self.register_device(device)

    def register_device(self, device: VirtualDevice) -> None:
        self._validate_device_channels(device)
        self._publish_info(device)

        with self._lock:
            self._states.setdefault(device.virtual_device_id, VirtualDeviceState())

        for channel in device.channels:
            topic = self._set_topic(device.virtual_device_id, channel)

            if topic in self._subscriptions:
                continue

            self._mqtt_client.subscribe(
                topic,
                self._handle_set_message,
                qos=1,
            )

            self._subscriptions.add(topic)
            LOGGER.debug("Registered virtual device topic: %s", topic)

        command_topic = self._command_topic(device.virtual_device_id)

        if command_topic not in self._subscriptions:
            self._mqtt_client.subscribe(
                command_topic,
                self._handle_command_message,
                qos=1,
            )
            self._subscriptions.add(command_topic)
            LOGGER.debug("Registered virtual device command topic: %s", command_topic)

    def get_device_state(self, virtual_device_id: str) -> dict[str, Any] | None:
        """Return the current state projection for one virtual device."""

        normalized_id = virtual_device_id.strip().lower()
        device = self.registry.get_by_id(normalized_id)

        if device is None:
            return None

        with self._lock:
            state = self._states.get(normalized_id)

            if state is None or not state.values:
                return None

            snapshot = dict(state.values)
            channel_updates = dict(state.channel_updates)

        return _virtual_device_state_payload(
            device=device,
            snapshot=snapshot,
            channel_updates=channel_updates,
        )

    def get_device_states(self) -> dict[str, dict[str, Any]]:
        """Return current state projections for all virtual devices with values."""

        with self._lock:
            virtual_device_ids = list(self._states)

        states: dict[str, dict[str, Any]] = {}

        for virtual_device_id in virtual_device_ids:
            state = self.get_device_state(virtual_device_id)

            if state is not None:
                states[virtual_device_id] = state

        return states

    def teach_in(self, virtual_device_id: str) -> None:
        """Transmit the configured teach-in telegram for one virtual device."""

        normalized_id = virtual_device_id.strip().lower()
        device = self.registry.get_by_id(normalized_id)

        if device is None:
            raise VirtualDeviceRuntimeError(
                f"Unknown virtual device: {normalized_id}"
            )

        if device.teach_in_telegram is None:
            raise VirtualDeviceRuntimeError(
                f"Virtual device has no teach-in telegram: {normalized_id}"
            )

        self._publish_encoded_telegram(
            EncodedVirtualTelegram.from_teach_in(device.teach_in_telegram)
        )

    def _handle_set_message(self, topic: str, payload: bytes) -> None:
        try:
            virtual_device_id, channel = self._parse_set_topic(topic)
            device = self.registry.get_by_id(virtual_device_id)

            if device is None:
                raise VirtualDeviceRuntimeError(f"Unknown virtual device: {virtual_device_id}")

            if channel not in device.channels:
                raise VirtualDeviceRuntimeError(
                    f"Channel {channel!r} is not enabled for virtual device {virtual_device_id}"
                )

            value = payload.decode("utf-8").strip()
            timestamp_fields = build_timestamp_fields()

            if value == "":
                self._handle_empty_set_payload(
                    device=device,
                    channel=channel,
                    timestamp_fields=timestamp_fields,
                )
                return

            last_update = str(timestamp_fields["timestamp_local"])

            with self._lock:
                state = self._states.setdefault(
                    virtual_device_id,
                    VirtualDeviceState(),
                )
                state.values[channel] = value
                state.channel_updates[channel] = last_update
                state.pending_channels.add(channel)
                snapshot = dict(state.values)
                channel_updates = dict(state.channel_updates)
                self._schedule_snapshot_locked(device, state)

            self._publish_channel_state(
                device,
                channel,
                value,
                timestamp_fields,
            )
            self._publish_device_state(
                device,
                snapshot,
                channel_updates,
                timestamp_fields,
            )

        except Exception as exc:
            self._publish_error(topic=topic, error=str(exc))

    def _handle_command_message(self, topic: str, payload: bytes) -> None:
        try:
            virtual_device_id = self._parse_command_topic(topic)
            command = _parse_virtual_command(payload)

            if command != "teach_in":
                raise VirtualDeviceRuntimeError(f"Unsupported virtual device command: {command}")

            self.teach_in(virtual_device_id)

        except Exception as exc:
            self._publish_error(topic=topic, error=str(exc))

    def _handle_empty_set_payload(
        self,
        *,
        device: VirtualDevice,
        channel: str,
        timestamp_fields: dict[str, Any],
    ) -> None:
        """Handle retained-topic deletion on a virtual channel set topic."""

        with self._lock:
            state = self._states.setdefault(
                device.virtual_device_id,
                VirtualDeviceState(),
            )
            state.values.pop(channel, None)
            state.channel_updates.pop(channel, None)
            state.pending_channels.discard(channel)

            if state.timer is not None and not state.pending_channels:
                state.timer.cancel()
                state.timer = None

            snapshot = dict(state.values)
            channel_updates = dict(state.channel_updates)

        self._mqtt_client.clear_retained_topic(
            f"{self._base_topic}/virtual/{device.virtual_device_id}/channel/{channel}/state"
        )
        self._publish_device_state(
            device,
            snapshot,
            channel_updates,
            timestamp_fields,
        )

    def _schedule_snapshot_locked(
        self,
        device: VirtualDevice,
        state: VirtualDeviceState,
    ) -> None:
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None

        aggregation_window_seconds = _aggregation_window_seconds(
            load_eep_definition(device.registry_profile)
        )

        timer = threading.Timer(
            aggregation_window_seconds,
            self._flush_device_snapshot,
            args=(device.virtual_device_id,),
        )
        timer.daemon = True
        state.timer = timer
        timer.start()

    def _flush_device_snapshot(self, virtual_device_id: str) -> None:
        try:
            device = self.registry.get_by_id(virtual_device_id)

            if device is None:
                raise VirtualDeviceRuntimeError(f"Unknown virtual device: {virtual_device_id}")

            with self._lock:
                state = self._states.setdefault(
                    virtual_device_id,
                    VirtualDeviceState(),
                )
                state.timer = None
                snapshot = dict(state.values)
                pending_channels = set(state.pending_channels)
                state.pending_channels.clear()

            encoded_telegrams = encode_virtual_device_snapshot(
                device=device,
                snapshot=snapshot,
                trigger_channels=pending_channels,
            )

            if not encoded_telegrams:
                LOGGER.debug(
                    "Virtual device %s not TX-ready yet; waiting for required channels",
                    virtual_device_id,
                )
                return

            for encoded in encoded_telegrams:
                self._publish_encoded_telegram(encoded)

        except Exception as exc:
            self._publish_error(
                topic=f"{self._base_topic}/virtual/{virtual_device_id}",
                error=str(exc),
            )

    def _publish_encoded_telegram(self, encoded: EncodedVirtualTelegram) -> None:
        raw_send_result = (
            self._radio_sender(encoded.to_radio_erp1()) if self._radio_sender is not None else None
        )
        send_result = raw_send_result or RadioSendResult(
            None,
            "accepted" if self._radio_sender is not None else "disabled",
        )

        event = encoded.to_runtime_event(send_result)

        self._mqtt_client.publish_json(
            f"{self._base_topic}/busmonitor/tx/event",
            _runtime_event_to_payload(event),
            qos=0,
            retain=False,
        )
        self._mqtt_client.publish_value(
            f"{self._base_topic}/busmonitor/tx/raw/telegram",
            encoded.raw_telegram,
            qos=0,
            retain=False,
        )

        if self._tx_event_callback is not None:
            self._tx_event_callback(event)
        elif self._sqlite_store is not None:
            self._sqlite_store.persist_event(event)
        if send_result.transmission == "failed":
            self._publish_error(
                topic=f"{self._base_topic}/busmonitor/tx/event",
                error=send_result.error or "Unknown interface transmission error",
            )

    def _publish_channel_state(
        self,
        device: VirtualDevice,
        channel: str,
        value: str,
        timestamp_fields: dict[str, Any],
    ) -> None:
        channel_definition = _channel_definition_for_name(device, channel)
        coerced_value = _coerce_payload_value(value)
        state_payload: dict[str, Any] = {
            **timestamp_fields,
            "channel": channel,
            "value": coerced_value,
        }

        if channel_definition is not None:
            if channel_definition.unit is not None:
                state_payload["unit"] = channel_definition.unit
            if channel_definition.semantic_role is not None:
                state_payload["semantic_role"] = channel_definition.semantic_role
            if channel_definition.object_type is not None:
                state_payload["object_type"] = channel_definition.object_type
            _add_derived_values(
                state_payload,
                semantic_role=channel_definition.semantic_role,
                value=coerced_value,
            )

        self._mqtt_client.publish_json(
            f"{self._base_topic}/virtual/{device.virtual_device_id}/channel/{channel}/state",
            state_payload,
            qos=0,
            retain=True,
        )

    def _publish_device_state(
        self,
        device: VirtualDevice,
        snapshot: dict[str, str],
        channel_updates: dict[str, str],
        timestamp_fields: dict[str, Any],
    ) -> None:
        state_payload = _virtual_device_state_payload(
            device=device,
            snapshot=snapshot,
            channel_updates=channel_updates,
        )

        self._mqtt_client.publish_json(
            f"{self._base_topic}/virtual/{device.virtual_device_id}/state",
            {
                **timestamp_fields,
                **state_payload,
                "last_seen": timestamp_fields["timestamp_local"],
            },
            qos=0,
            retain=True,
        )

    def _publish_error(self, *, topic: str, error: str) -> None:
        self._mqtt_client.publish_json(
            f"{self._base_topic}/gateway/error",
            {
                **build_timestamp_fields(),
                "level": "error",
                "component": "virtual-device",
                "message": "Virtual device TX failed",
                "topic": topic,
                "error": error,
            },
            qos=0,
            retain=False,
        )

    def _publish_info(self, device: VirtualDevice) -> None:
        self._mqtt_client.publish_json(
            f"{self._base_topic}/virtual/{device.virtual_device_id}/info",
            device.model_dump(mode="json"),
            qos=0,
            retain=True,
        )

    def _validate_device_channels(self, device: VirtualDevice) -> None:
        eep_definition = load_eep_definition(device.registry_profile)

        available_channels = {
            channel.name for channel in eep_definition.channels if channel.output.mqtt
        }

        missing = [channel for channel in device.channels if channel not in available_channels]

        if missing:
            raise VirtualDeviceRuntimeError(
                f"Virtual device channel not found in EEP registry: {', '.join(missing)}"
            )

    def _command_topic(self, virtual_device_id: str) -> str:
        return f"{self._base_topic}/virtual/{virtual_device_id}/command"

    def _set_topic(self, virtual_device_id: str, channel: str) -> str:
        return f"{self._base_topic}/virtual/{virtual_device_id}/channel/{channel}/set"

    def _parse_command_topic(self, topic: str) -> str:
        prefix = f"{self._base_topic}/virtual/"

        if not topic.startswith(prefix):
            raise VirtualDeviceRuntimeError(f"Invalid virtual command topic: {topic}")

        remainder = topic[len(prefix) :]
        parts = remainder.split("/")

        if len(parts) != 2 or parts[1] != "command":
            raise VirtualDeviceRuntimeError(f"Invalid virtual command topic: {topic}")

        return parts[0]

    def _parse_set_topic(self, topic: str) -> tuple[str, str]:
        prefix = f"{self._base_topic}/virtual/"

        if not topic.startswith(prefix):
            raise VirtualDeviceRuntimeError(f"Invalid virtual topic: {topic}")

        remainder = topic[len(prefix) :]
        parts = remainder.split("/")

        if len(parts) != 4 or parts[1] != "channel" or parts[3] != "set":
            raise VirtualDeviceRuntimeError(f"Invalid virtual set topic: {topic}")

        return parts[0], parts[2]


_MISSING_REQUIRED: Final = object()


def encode_virtual_device_value(
    *,
    device: VirtualDevice,
    channel_name: str,
    value: str,
) -> EncodedVirtualTelegram:
    """Encode a single value using snapshot logic for compatibility tests."""

    return _require_encoded(
        encode_virtual_device_snapshot(
            device=device,
            snapshot={channel_name: value},
            trigger_channels={channel_name},
        )
    )


def encode_virtual_device_snapshot(
    *,
    device: VirtualDevice,
    snapshot: dict[str, str],
    trigger_channels: set[str] | None = None,
) -> list[EncodedVirtualTelegram]:
    """Encode a virtual device state snapshot through the Registry v3 encoder."""

    eep_definition = load_eep_definition(device.registry_profile)

    unsupported_rorgs = {
        telegram.telegram_id.rorg.upper()
        for telegram in eep_definition.telegrams
        if telegram.telegram_id.rorg.upper() not in SUPPORTED_RORGS
    }

    if unsupported_rorgs:
        raise VirtualDeviceRuntimeError(
            f"Unsupported virtual device RORG: {', '.join(sorted(unsupported_rorgs))}"
        )

    semantic_snapshot = _virtual_device_semantic_snapshot(
        device=device,
        snapshot=snapshot,
        eep_definition=eep_definition,
    )

    if not isinstance(semantic_snapshot, dict):
        return []

    try:
        encoded_telegrams = encode_semantic_snapshot_all(
            eep_definition=eep_definition,
            snapshot=semantic_snapshot,
            source="channels",
            trigger_refs=trigger_channels,
        )
    except EEPEncodeError as exc:
        raise VirtualDeviceRuntimeError(str(exc)) from exc

    return [
        EncodedVirtualTelegram(
            rorg=encoded.rorg,
            data=encoded.data,
            sender_id=device.sender_id.upper(),
            status=encoded.status,
            raw_telegram=_format_erp1_telegram(
                rorg=encoded.rorg,
                data=encoded.data,
                sender_id=device.sender_id.upper(),
                status=encoded.status,
            ),
        )
        for encoded in encoded_telegrams
    ]


def _virtual_device_semantic_snapshot(
    *,
    device: VirtualDevice,
    snapshot: dict[str, str],
    eep_definition: EEPDefinition,
) -> dict[str, Any] | object:
    semantic_snapshot: dict[str, Any] = {}

    for channel in eep_definition.channels:
        value = _snapshot_value_for_channel(
            device=device,
            channel=channel,
            snapshot=snapshot,
        )

        if value is _MISSING_REQUIRED:
            return cast(object, _MISSING_REQUIRED)

        if value is None:
            continue

        semantic_snapshot[channel.name] = value

    return semantic_snapshot


def _snapshot_value_for_channel(
    *,
    device: VirtualDevice,
    channel: ChannelDefinition,
    snapshot: dict[str, str],
) -> Any:
    if channel.name in snapshot:
        return snapshot[channel.name]

    if channel.tx is not None and channel.tx.runtime_default == "channel_enabled":
        reference_channel = channel.tx.runtime_default_channel or channel.name
        return "available" if reference_channel in device.channels else "not_available"

    if channel.tx is not None and channel.tx.runtime_default == "channel_enabled":
        return "available" if channel.name in device.channels else "not_available"

    if channel.name not in device.channels:
        return None

    return None


def _virtual_device_state_payload(
    *,
    device: VirtualDevice,
    snapshot: dict[str, str],
    channel_updates: dict[str, str],
) -> dict[str, Any]:
    channels: dict[str, dict[str, Any]] = {}

    for channel, value in sorted(snapshot.items()):
        channel_definition = _channel_definition_for_name(device, channel)
        coerced_value = _coerce_payload_value(value)
        channel_state: dict[str, Any] = {
            "value": coerced_value,
            "last_update": channel_updates.get(channel),
        }

        if channel_state["last_update"] is None:
            channel_state.pop("last_update")

        if channel_definition is not None:
            if channel_definition.unit is not None:
                channel_state["unit"] = channel_definition.unit
            if channel_definition.semantic_role is not None:
                channel_state["semantic_role"] = channel_definition.semantic_role
            if channel_definition.object_type is not None:
                channel_state["object_type"] = channel_definition.object_type
            _add_derived_values(
                channel_state,
                semantic_role=channel_definition.semantic_role,
                value=coerced_value,
            )

        channels[channel] = channel_state

    last_updates = [timestamp for timestamp in channel_updates.values() if timestamp]
    last_update = max(last_updates) if last_updates else None

    payload: dict[str, Any] = {
        "virtual_device_id": device.virtual_device_id,
        "sender_id": device.sender_id.upper(),
        "display_name": (
            device.metadata.get("display_name")
            or device.metadata.get("name")
            or device.description
            or device.virtual_device_id
        ),
        "channels": channels,
    }

    if last_update is not None:
        payload["last_update"] = last_update
        payload["last_seen"] = last_update

    return payload


def _runtime_event_to_payload(event: RuntimeTelegramEvent) -> dict[str, Any]:
    return tx_event_to_mqtt_payload(event)


def _parse_virtual_command(payload: bytes) -> str:
    payload_text = payload.decode("utf-8", errors="replace").strip()

    if not payload_text:
        raise VirtualDeviceRuntimeError("Virtual device command payload is empty")

    if payload_text.startswith("{"):
        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise VirtualDeviceRuntimeError("Invalid virtual device command JSON") from exc

        command = data.get("command")
        if not isinstance(command, str) or not command.strip():
            raise VirtualDeviceRuntimeError("Virtual device command JSON requires command")
        return command.strip()

    return payload_text


def _aggregation_window_seconds(eep_definition: EEPDefinition) -> float:
    if eep_definition.tx is not None and eep_definition.tx.aggregation_window_seconds is not None:
        return max(
            MIN_AGGREGATION_WINDOW_SECONDS,
            eep_definition.tx.aggregation_window_seconds,
        )

    return DEFAULT_AGGREGATION_WINDOW_SECONDS


def _channel_definition_for_name(
    device: VirtualDevice,
    channel_name: str,
) -> ChannelDefinition | None:
    eep_definition = load_eep_definition(device.registry_profile)

    for channel in eep_definition.channels:
        if channel.name == channel_name:
            return channel

    return None


def _format_erp1_telegram(
    *,
    rorg: str,
    data: str,
    sender_id: str,
    status: str,
) -> str:
    sender_id_bytes = " ".join(
        sender_id[index : index + 2] for index in range(0, len(sender_id), 2)
    )
    parts = [rorg, *data.split(), sender_id_bytes, status]

    return " ".join(parts)


def _coerce_payload_value(value: str) -> Any:
    normalized = value.strip()

    if normalized.lower() in {"true", "false"}:
        return normalized.lower() == "true"

    try:
        if "." in normalized:
            return float(normalized)

        return int(normalized)
    except ValueError:
        return value


def _add_derived_values(
    payload: dict[str, Any],
    *,
    semantic_role: str | None,
    value: Any,
) -> None:
    value_bool = derived_value(
        semantic_role=semantic_role,
        value_name="value_bool",
        value=value,
    )

    if value_bool is not None:
        payload["value_bool"] = value_bool


def _require_encoded(
    encoded: list[EncodedVirtualTelegram],
) -> EncodedVirtualTelegram:
    if not encoded:
        raise VirtualDeviceRuntimeError("Virtual device snapshot is missing required channels")

    return encoded[0]
