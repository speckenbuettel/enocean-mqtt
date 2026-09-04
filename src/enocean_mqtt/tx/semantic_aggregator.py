"""Shared semantic TX aggregation and Registry-v3 encoding."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from enocean_mqtt.eep.models import EEPDefinition
from enocean_mqtt.eep.runtime_encoder import EEPEncodeError, encode_semantic_snapshot_all

SemanticSource = Literal["channels", "messages"]
DEFAULT_AGGREGATION_WINDOW_SECONDS = 10.0
MIN_AGGREGATION_WINDOW_SECONDS = 1.0


class SemanticTxAggregationError(ValueError):
    """Raised when a semantic TX snapshot cannot be encoded."""


@dataclass(slots=True)
class EncodedTxTelegram:
    rorg: str
    data: str
    sender_id: str
    destination_id: str
    status: str
    telegram_type_id: str | None
    port: str

    @property
    def raw_telegram(self) -> str:
        sender = " ".join(
            self.sender_id[index:index + 2]
            for index in range(0, len(self.sender_id), 2)
        )
        return " ".join([self.rorg, *self.data.split(), sender, self.status])


@dataclass(slots=True)
class _State:
    values: dict[str, Any] = field(default_factory=dict)
    pending_refs: set[str] = field(default_factory=set)
    timer: threading.Timer | None = None


class SemanticTxAggregator:
    """Collect semantic values, complete a snapshot and encode it by bindings."""

    def __init__(
        self,
        *,
        on_encoded: Callable[[str, list[EncodedTxTelegram]], None],
        on_error: Callable[[str, Exception], None] | None = None,
    ) -> None:
        self._on_encoded = on_encoded
        self._on_error = on_error
        self._states: dict[str, _State] = {}
        self._lock = threading.RLock()

    def submit(
        self,
        *,
        key: str,
        semantic_ref: str,
        value: Any,
        eep_definition: EEPDefinition,
        source: SemanticSource,
        sender_id: str,
        destination_id: str = "FFFFFFFF",
        enabled_refs: set[str] | None = None,
        port: str,
    ) -> None:
        with self._lock:
            state = self._states.setdefault(key, _State())
            state.values[semantic_ref] = value
            state.pending_refs.add(semantic_ref)
            if state.timer is not None:
                state.timer.cancel()
            timer = threading.Timer(
                aggregation_window_seconds(eep_definition),
                self._flush,
                kwargs={
                    "key": key,
                    "eep_definition": eep_definition,
                    "source": source,
                    "sender_id": sender_id.upper(),
                    "destination_id": destination_id.upper(),
                    "enabled_refs": set(enabled_refs or ()),
                    "port": port,
                },
            )
            timer.daemon = True
            state.timer = timer
            timer.start()

    def clear_value(self, *, key: str, semantic_ref: str) -> None:
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return
            state.values.pop(semantic_ref, None)
            state.pending_refs.discard(semantic_ref)
            if state.timer is not None and not state.pending_refs:
                state.timer.cancel()
                state.timer = None

    def snapshot(self, key: str) -> dict[str, Any]:
        with self._lock:
            state = self._states.get(key)
            return dict(state.values) if state is not None else {}

    def _flush(
        self,
        *,
        key: str,
        eep_definition: EEPDefinition,
        source: SemanticSource,
        sender_id: str,
        destination_id: str,
        enabled_refs: set[str],
        port: str,
    ) -> None:
        try:
            with self._lock:
                state = self._states.setdefault(key, _State())
                state.timer = None
                snapshot = dict(state.values)
                trigger_refs = set(state.pending_refs)
                state.pending_refs.clear()
            telegrams = encode_completed_snapshot(
                eep_definition=eep_definition,
                source=source,
                snapshot=snapshot,
                trigger_refs=trigger_refs,
                sender_id=sender_id,
                destination_id=destination_id,
                enabled_refs=enabled_refs,
                port=port,
            )
            self._on_encoded(key, telegrams)
        except Exception as exc:
            if self._on_error is not None:
                self._on_error(key, exc)


def complete_semantic_snapshot(
    *,
    eep_definition: EEPDefinition,
    source: SemanticSource,
    snapshot: dict[str, Any],
    enabled_refs: set[str] | None = None,
) -> dict[str, Any]:
    completed = dict(snapshot)
    enabled = set(enabled_refs or ())
    definitions = eep_definition.channels if source == "channels" else eep_definition.messages
    for definition in definitions:
        if definition.name in completed or definition.tx is None:
            continue
        if definition.tx.runtime_default != "channel_enabled":
            continue
        reference = definition.tx.runtime_default_channel or definition.name
        completed[definition.name] = "available" if reference in enabled else "not_available"
    return completed


def encode_completed_snapshot(
    *,
    eep_definition: EEPDefinition,
    source: SemanticSource,
    snapshot: dict[str, Any],
    trigger_refs: set[str] | None,
    sender_id: str,
    destination_id: str = "FFFFFFFF",
    enabled_refs: set[str] | None = None,
    port: str,
) -> list[EncodedTxTelegram]:
    try:
        encoded = encode_semantic_snapshot_all(
            eep_definition=eep_definition,
            snapshot=complete_semantic_snapshot(
                eep_definition=eep_definition,
                source=source,
                snapshot=snapshot,
                enabled_refs=enabled_refs,
            ),
            source=source,
            trigger_refs=trigger_refs,
        )
    except EEPEncodeError as exc:
        raise SemanticTxAggregationError(str(exc)) from exc
    return [
        EncodedTxTelegram(
            rorg=item.rorg,
            data=item.data,
            sender_id=sender_id.upper(),
            destination_id=destination_id.upper(),
            status=item.status,
            telegram_type_id=item.telegram_type_id,
            port=port,
        )
        for item in encoded
    ]


def aggregation_window_seconds(eep_definition: EEPDefinition) -> float:
    if eep_definition.tx is not None and eep_definition.tx.aggregation_window_seconds is not None:
        return max(MIN_AGGREGATION_WINDOW_SECONDS, eep_definition.tx.aggregation_window_seconds)
    return DEFAULT_AGGREGATION_WINDOW_SECONDS
