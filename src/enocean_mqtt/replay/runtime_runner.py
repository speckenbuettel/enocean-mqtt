"""Reusable replay/runtime telegram execution runner."""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from typing import Any

from enocean_mqtt.devices.gateway_observations import record_gateway_rx
from enocean_mqtt.eep.json_registry import load_eep_definition
from enocean_mqtt.esp3.telegram_quality import assess_telegram
from enocean_mqtt.gateway.orchestrator import GatewayOrchestrator
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.gateway.unknown_devices import UnknownDeviceRegistry
from enocean_mqtt.mqtt.client import MQTTClient
from enocean_mqtt.replay.busmonitor_export import (
    replay_telegram_to_runtime_event,
    runtime_event_to_payload,
)
from enocean_mqtt.replay.controller import ReplayController
from enocean_mqtt.replay.models import ReplayTelegram
from enocean_mqtt.replay.session import ReplaySession
from enocean_mqtt.runtime.event import RuntimeTelegramEvent
from enocean_mqtt.runtime.state_manager import RuntimeStateManager
from enocean_mqtt.storage.sqlite_store import SQLiteRuntimeStore
from enocean_mqtt.web_api.live_events import publish_live_event


class RuntimePipelineStatistics:
    """Mutable statistics for one runtime telegram source."""

    def __init__(self) -> None:
        self.statistics: Counter[str] = Counter()
        self.metrics_payload: dict[str, Any] = {}
        self.rorg_statistics: dict[str, Counter[str]] = defaultdict(Counter)
        self.unknown_rorg_statistics: dict[str, Counter[str]] = defaultdict(Counter)
        self.unknown_rorg_senders: dict[str, set[str]] = defaultdict(set)
        self.active_known_senders: dict[str, float] = {}
        self.started_monotonic = time.monotonic()


class ReplayRuntimeRunner:
    """Execute replay sessions and shared runtime telegram processing."""

    def __init__(
        self,
        replay_controller: ReplayController,
        runtime_state_manager: RuntimeStateManager,
        mqtt_client: MQTTClient,
        base_topic: str,
        orchestrator: GatewayOrchestrator,
        status_publisher: GatewayStatusPublisher,
        unknown_devices_registry: UnknownDeviceRegistry,
        gateway_health_publish_interval_seconds: int,
        active_device_window_seconds: int = 86400,
        sqlite_store: SQLiteRuntimeStore | None = None,
    ) -> None:
        self._replay_controller = replay_controller
        self._runtime_state_manager = runtime_state_manager
        self._mqtt_client = mqtt_client
        self._base_topic = base_topic.rstrip("/")
        self._orchestrator = orchestrator
        self._status_publisher = status_publisher
        self._unknown_devices_registry = unknown_devices_registry
        self._gateway_health_publish_interval_seconds = gateway_health_publish_interval_seconds
        self._active_device_window_seconds = active_device_window_seconds
        self._sqlite_store = sqlite_store
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._mqtt_publish_failures = 0
        self._external_statistics = RuntimePipelineStatistics()
        self._last_external_health_publish_monotonic = 0.0
        self._external_statistics_lock = threading.RLock()
        self._gateway_sender_ids: set[str] = set()

    def start_async(self, session: ReplaySession) -> None:
        """Start replay session in a background thread."""

        with self._lock:
            if self.is_running:
                raise RuntimeError("Replay session already running")

            self._replay_controller.start(session)
            self._runtime_state_manager.switch_to_replay(
                reason="runtime_command_replay_start",
            )

            self._thread = threading.Thread(
                target=self._run_thread,
                args=(session,),
                daemon=True,
                name="enocean-mqtt-replay-runner",
            )
            self._thread.start()

    def run_sync(
        self, session: ReplaySession, *, stop_requested: threading.Event | None = None,
    ) -> None:
        """Run replay session synchronously."""

        with self._lock:
            if self.is_running:
                raise RuntimeError("Replay session already running")

            self._replay_controller.start(session)
            self._runtime_state_manager.switch_to_replay(
                reason="startup_replay_session",
            )

        self._run_session(session, raise_errors=True, stop_requested=stop_requested)

    def stop(self, reason: str) -> None:
        """Stop active replay session."""

        if self._runtime_state_manager.runtime_mode != "replay":
            return

        self._replay_controller.stop()
        self._runtime_state_manager.switch_to_live(reason=reason)

    @property
    def is_running(self) -> bool:
        """Return whether a replay thread is active."""

        return self._thread is not None and self._thread.is_alive()

    def process_external_telegram(self, telegram: ReplayTelegram) -> dict[str, Any]:
        """Process one non-replay telegram through the shared runtime pipeline."""

        with self._external_statistics_lock:
            combined_statistics = self._process_runtime_telegram(
                telegram=telegram,
                pipeline_statistics=self._external_statistics,
            )

        now_monotonic = time.monotonic()

        if (
            now_monotonic - self._last_external_health_publish_monotonic
            >= self._gateway_health_publish_interval_seconds
        ):
            self._status_publisher.publish_health(
                mqtt_connected=self._mqtt_client.is_connected(),
            )
            self._status_publisher.publish_uptime()
            self._last_external_health_publish_monotonic = now_monotonic

        return combined_statistics

    def record_external_tx_event(self, event: RuntimeTelegramEvent) -> None:
        """Persist an already published TX event and include it in metrics."""

        if event.direction != "tx":
            raise ValueError("External TX metric event must use direction 'tx'")

        if self._sqlite_store is not None:
            self._sqlite_store.persist_event(event)

        with self._external_statistics_lock:
            pipeline_statistics = self._external_statistics
            statistics = pipeline_statistics.statistics
            metrics_payload = pipeline_statistics.metrics_payload

            statistics["telegrams_total"] += 1
            statistics["tx_telegrams_total"] += 1

            elapsed_seconds = max(
                time.monotonic() - pipeline_statistics.started_monotonic,
                1.0,
            )
            metrics_payload["tx_telegrams_per_minute"] = (
                statistics["tx_telegrams_total"] / elapsed_seconds * 60.0
            )
            metrics_payload["tx_telegram_mean_interval_seconds"] = round(
                elapsed_seconds / statistics["tx_telegrams_total"],
                1,
            )

            combined_statistics: dict[str, Any] = {
                **dict(statistics),
                **metrics_payload,
            }
            rx_telegrams_per_minute = statistics["rx_telegrams_total"] / elapsed_seconds * 60.0

            self._status_publisher.publish_metrics(
                statistics=combined_statistics,
                unknown_devices=self._unknown_devices_registry.count_devices(),
                telegrams_per_minute=rx_telegrams_per_minute,
            )

    def _safe_publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        retain: bool = False,
    ) -> None:
        try:
            self._mqtt_client.publish_json(
                topic,
                payload,
                retain=retain,
            )
        except Exception:
            self._mqtt_publish_failures += 1
            raise

    def _safe_publish_value(
        self,
        topic: str,
        value: Any,
        retain: bool = False,
    ) -> None:
        try:
            self._mqtt_client.publish_value(
                topic,
                value,
                retain=retain,
            )
        except Exception:
            self._mqtt_publish_failures += 1
            raise

    def _handle_reconnect_if_needed(self) -> None:
        """Republish gateway topics after MQTT reconnect and report outage."""

        if not self._mqtt_client.is_connected():
            return

        if not self._mqtt_client.consume_connection_interruption():
            return

        failures = self._mqtt_publish_failures
        self._mqtt_publish_failures = 0

        self._status_publisher.republish_gateway_topics(
            mqtt_connected=True,
        )
        self._status_publisher.publish_error(
            component="mqtt",
            message="MQTT connection was interrupted",
            reconnects=self._mqtt_client.reconnects,
            dropped_publish_attempts=failures,
            runtime_mode=self._runtime_state_manager.runtime_mode,
        )

    def _process_runtime_telegram(
        self,
        telegram: ReplayTelegram,
        pipeline_statistics: RuntimePipelineStatistics,
    ) -> dict[str, Any]:
        runtime_event = replay_telegram_to_runtime_event(telegram)

        assessment = assess_telegram(
            rorg=runtime_event.rorg, data=runtime_event.data,
            sender_id=runtime_event.sender_id, status=runtime_event.erp1_status,
            direction=runtime_event.direction,
        )
        registry = self._orchestrator.registry
        device = registry.get_by_device_id(runtime_event.sender_id or "")
        if (assessment is None and device is not None and device.registry_profile
                and self._orchestrator.gateway_for_sender(runtime_event.sender_id or "") is None):
            try:
                definition = load_eep_definition(device.registry_profile)
            except Exception:
                # Keep registry/schema failures visible in the existing decoder path.
                definition = None
            if definition is not None:
                assessment = assess_telegram(
                    rorg=runtime_event.rorg, data=runtime_event.data,
                    sender_id=runtime_event.sender_id, status=runtime_event.erp1_status,
                    direction=runtime_event.direction, definition=definition,
                )
        if assessment is None and device is None:
            assessment = assess_telegram(
                rorg=runtime_event.rorg, data=runtime_event.data,
                sender_id=runtime_event.sender_id, status=runtime_event.erp1_status,
                direction=runtime_event.direction,
                known_sender_ids=(d.device_id for d in registry.devices),
            )

        if self._sqlite_store is not None:
            if assessment is not None:
                self._sqlite_store.persist_diagnostic(runtime_event, assessment.to_payload())
            if assessment is None or assessment.reason not in {
                "invalid_rorg", "invalid_sender_id", "invalid_payload_hex", "invalid_status",
            }:
                self._sqlite_store.persist_event(runtime_event)

        payload = runtime_event_to_payload(runtime_event)
        if assessment is not None:
            payload["quality"] = assessment.to_payload()
            stats = pipeline_statistics.statistics
            stats[f"{assessment.classification}_telegrams"] += 1
            pipeline_statistics.metrics_payload.setdefault("telegram_quality_reasons", {})
            reasons = pipeline_statistics.metrics_payload["telegram_quality_reasons"]
            reasons[assessment.reason] = reasons.get(assessment.reason, 0) + 1

        publish_live_event(payload)

        statistics = pipeline_statistics.statistics
        metrics_payload = pipeline_statistics.metrics_payload
        rorg_statistics = pipeline_statistics.rorg_statistics
        unknown_rorg_statistics = pipeline_statistics.unknown_rorg_statistics
        unknown_rorg_senders = pipeline_statistics.unknown_rorg_senders
        active_known_senders = pipeline_statistics.active_known_senders

        statistics["telegrams_total"] += 1

        direction = runtime_event.direction
        statistics[f"{direction}_telegrams_total"] += 1
        if direction == "rx":
            counter = runtime_event.repeater_count
            category = (
                "original" if counter in (0, 15)
                else "repeated" if counter in (1, 2)
                else "unclassified"
            )
            statistics[f"{category}_telegrams_total"] += 1

        rorg = runtime_event.rorg or "unknown"
        if assessment is None or assessment.reason not in {"invalid_rorg", "unrecognized_rorg"}:
            rorg_statistics[rorg]["telegrams_total"] += 1

        metrics_payload["last_sender_id"] = runtime_event.sender_id
        metrics_payload["last_rorg"] = rorg
        if direction == "rx":
            metrics_payload["last_rx"] = {
                "raw_telegram": runtime_event.raw_telegram,
                "rorg": runtime_event.rorg,
                "sender_id": runtime_event.sender_id,
                "data": runtime_event.data,
                "erp1_status": runtime_event.erp1_status,
            }

        event_topic = f"{self._base_topic}/busmonitor/{direction}/event"
        raw_topic = f"{self._base_topic}/busmonitor/{direction}/raw/telegram"

        self._safe_publish_json(event_topic, payload)

        if runtime_event.raw_telegram is not None:
            self._safe_publish_value(raw_topic, runtime_event.raw_telegram)

        sender_id = runtime_event.sender_id
        known_device = False

        gateways = getattr(self._orchestrator, "gateways", None)
        if gateways is not None:
            gateway_ids = gateways.sender_ids()
            for gateway_id in gateway_ids - self._gateway_sender_ids:
                self._unknown_devices_registry.remove(gateway_id)
                self._safe_publish_value(
                    f"{self._base_topic}/busmonitor/unknown_devices/{gateway_id}",
                    "", retain=True,
                )
            self._gateway_sender_ids = gateway_ids
            for senders in unknown_rorg_senders.values():
                senders.difference_update(gateway_ids)

        if sender_id:
            device = self._orchestrator.registry.get_by_device_id(sender_id)
            known_device = device is not None or sender_id.upper() in self._gateway_sender_ids
            if gateways is not None:
                record_gateway_rx(
                    gateways, runtime_event, device.registry_profile if device else None,
                )

        observed_at = runtime_event.timestamp_unix or time.time()
        active_cutoff = observed_at - self._active_device_window_seconds
        expired_senders = [
            active_sender
            for active_sender, last_seen in active_known_senders.items()
            if last_seen < active_cutoff
        ]
        for active_sender in expired_senders:
            del active_known_senders[active_sender]

        if (assessment is not None and assessment.skip_decode
                and (known_device or assessment.classification != "teach_in_candidate")):
            # Already archived and exposed as raw evidence, never a device value.
            pass
        elif runtime_event.rorg == "D0" and known_device:
            statistics["non_eep_telegrams"] += 1
        elif known_device and sender_id is not None:
            active_known_senders[sender_id.strip().upper()] = observed_at

            gateway = self._orchestrator.gateway_for_sender(sender_id)
            if gateway is not None and direction == "rx":
                statistics["gateway_telegrams"] += 1
            # Identification alone is not semantic decoding.
            if gateway is not None:
                from enocean_mqtt.devices.gateway_decode import decode_gateway_payload
                channel = gateway.channel(sender_id)
                profile = (channel.profile if channel else
                           device.registry_profile if device else None)
                outcome, _, _ = decode_gateway_payload(
                    profile, telegram.payload_hex, telegram.eno_rorg, telegram.status,
                )
                if direction == "rx" and outcome == "decoded":
                    if self._orchestrator.process_telegram(telegram):
                        statistics["decoded_telegrams"] += 1
                elif direction == "rx" and outcome in ("invalid_profile", "malformed_payload"):
                    statistics["decode_errors"] += 1
            else:
                success = self._orchestrator.process_telegram(telegram)
                if success:
                    statistics["decoded_telegrams"] += 1
                else:
                    statistics["decode_errors"] += 1
        else:
            statistics["unknown_device_telegrams"] += 1

            if sender_id:
                unknown_rorg_senders[rorg].add(sender_id.strip().upper())
                unknown_record = self._unknown_devices_registry.observe(
                    sender_id=sender_id,
                    timestamp=runtime_event.timestamp_unix,
                    rorg=rorg,
                    dbm=runtime_event.rssi_dbm,
                    data=runtime_event.data,
                )

                unknown_topic = (
                    f"{self._base_topic}/busmonitor/unknown_devices/{sender_id.strip().upper()}"
                )

                self._safe_publish_json(
                    unknown_topic,
                    unknown_record.to_payload(),
                    retain=True,
                )

            if rorg:
                unknown_rorg_statistics[rorg]["telegrams_total"] += 1

        metrics_payload["active_devices_total"] = len(active_known_senders)

        elapsed_seconds = max(
            time.monotonic() - pipeline_statistics.started_monotonic,
            1.0,
        )

        telegrams_per_minute = statistics["rx_telegrams_total"] / elapsed_seconds * 60.0

        metrics_payload["rorg_metrics"] = _build_rorg_metrics(
            rorg_statistics,
            elapsed_seconds,
        )
        metrics_payload["unknown_rorg_metrics"] = _build_unknown_rorg_metrics(
            unknown_rorg_statistics,
            unknown_rorg_senders,
            elapsed_seconds,
        )
        metrics_payload["telegram_mean_interval_seconds"] = round(
            elapsed_seconds / max(statistics["rx_telegrams_total"], 1),
            1,
        )

        combined_statistics: dict[str, Any] = {
            **dict(statistics),
            **metrics_payload,
        }

        self._status_publisher.publish_metrics(
            statistics=combined_statistics,
            unknown_devices=self._unknown_devices_registry.count_devices(),
            telegrams_per_minute=telegrams_per_minute,
        )

        return combined_statistics

    def _run_thread(self, session: ReplaySession) -> None:
        try:
            self._run_session(session, raise_errors=False)
        finally:
            with self._lock:
                self._thread = None

    def _run_session(
        self, session: ReplaySession, raise_errors: bool,
        stop_requested: threading.Event | None = None,
    ) -> None:
        reader = self._replay_controller.create_reader(session)
        pipeline_statistics = RuntimePipelineStatistics()
        last_health_publish_monotonic = 0.0
        completed_normally = True

        try:
            for telegram in reader.iter_telegrams(limit=session.limit):
                if stop_requested is not None and stop_requested.is_set():
                    completed_normally = False
                    break
                self._handle_reconnect_if_needed()

                if self._runtime_state_manager.runtime_mode != "replay":
                    completed_normally = False
                    break

                session.statistics = self._process_runtime_telegram(
                    telegram=telegram,
                    pipeline_statistics=pipeline_statistics,
                )

                now_monotonic = time.monotonic()

                if (
                    now_monotonic - last_health_publish_monotonic
                    >= self._gateway_health_publish_interval_seconds
                ):
                    self._status_publisher.publish_health(
                        mqtt_connected=self._mqtt_client.is_connected(),
                    )

                    self._status_publisher.publish_uptime()

                    last_health_publish_monotonic = now_monotonic

                if stop_requested is not None:
                    if stop_requested.wait(session.interval_seconds):
                        completed_normally = False
                        break
                else:
                    time.sleep(session.interval_seconds)

        except Exception:
            completed_normally = False

            if raise_errors:
                raise

        finally:
            self._replay_controller.stop()

            if completed_normally:
                self._runtime_state_manager.switch_to_live(
                    reason="replay_completed",
                )
            else:
                self._runtime_state_manager.switch_to_live(
                    reason="replay_stopped",
                )


def _build_rorg_metrics(
    rorg_statistics: dict[str, Counter[str]],
    elapsed_seconds: float,
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}

    for rorg, statistics in rorg_statistics.items():
        telegrams_total = statistics["telegrams_total"]

        metrics[rorg] = {
            "telegrams_total": telegrams_total,
            "telegrams_per_minute": round(
                telegrams_total / elapsed_seconds * 60.0,
                1,
            ),
        }

    return metrics


def _build_unknown_rorg_metrics(
    unknown_rorg_statistics: dict[str, Counter[str]],
    unknown_rorg_senders: dict[str, set[str]],
    elapsed_seconds: float,
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}

    for rorg, statistics in unknown_rorg_statistics.items():
        telegrams_total = statistics["telegrams_total"]

        metrics[rorg] = {
            "telegrams_total": telegrams_total,
            "unique_senders": len(unknown_rorg_senders.get(rorg, set())),
            "telegrams_per_minute": round(
                telegrams_total / elapsed_seconds * 60.0,
                1,
            ),
        }

    return metrics
