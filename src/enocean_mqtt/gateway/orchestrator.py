"""Gateway orchestration for semantic MQTT publishing."""

from __future__ import annotations

import logging

from enocean_mqtt.devices.gateway_decode import decode_gateway_payload
from enocean_mqtt.devices.gateways import ExternalGateway, GatewayRegistry
from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.runtime_decode_service import decode_runtime_telegram
from enocean_mqtt.esp3.signal import RORG_NAMES
from enocean_mqtt.esp3.telegram_quality import assess_telegram
from enocean_mqtt.gateway.publisher import DevicePublisher
from enocean_mqtt.gateway.status import GatewayStatusPublisher
from enocean_mqtt.replay.models import ReplayTelegram

logger = logging.getLogger(__name__)


class GatewayOrchestrator:
    """Resolve devices, decode telegrams and publish semantic MQTT state."""

    def __init__(
        self,
        registry: DeviceRegistry,
        publisher: DevicePublisher,
        status_publisher: GatewayStatusPublisher | None = None,
        gateways: GatewayRegistry | None = None,
    ) -> None:
        self._registry = registry
        self._publisher = publisher
        self._status_publisher = status_publisher
        self.gateways = gateways

    def gateway_for_sender(self, sender_id: str) -> ExternalGateway | None:
        return self.gateways.resolve(sender_id) if self.gateways is not None else None

    @property
    def registry(self) -> DeviceRegistry:
        """Return active device registry."""

        return self._registry

    def update_registry(self, registry: DeviceRegistry) -> None:
        """Replace active runtime device registry."""

        self._registry = registry

    def process_telegram(self, telegram: ReplayTelegram) -> bool:
        """Decode and publish one semantic device telegram."""

        sender_id = telegram.sender_id

        # SIGNAL is independent of EEPs; unknown RORGs remain in the raw archive.
        incoming_rorg = (telegram.eno_rorg or "").upper()
        if incoming_rorg == "D0" or (incoming_rorg and incoming_rorg not in RORG_NAMES):
            return False

        if not sender_id:
            return False

        device = self._registry.get_by_device_id(sender_id)

        gateway = self.gateway_for_sender(sender_id)
        if gateway is not None:
            if telegram.normalized_direction != "rx":
                return False
            channel = gateway.channel(sender_id)
            profile = channel.profile if channel else (device.registry_profile if device else None)
            outcome, decoded, error = decode_gateway_payload(
                profile, telegram.payload_hex, telegram.eno_rorg, telegram.status,
            )
            if decoded is not None:
                self._publisher.publish_gateway_command(
                    gateway=gateway, sender_id=sender_id, decoded=decoded,
                    timestamp=telegram.timestamp,
                )
            if error:
                logger.debug("Gateway channel %s: %s (%s)", sender_id, error, outcome)
            return decoded is not None

        if device is None:
            return False

        profile = device.registry_profile

        if not profile:
            logger.debug(
                "Skipping device %s without profile/eep assignment",
                device.device_id,
            )
            return False

        payload_hex = telegram.payload_hex

        if not payload_hex:
            logger.debug(
                "Skipping device %s without payload",
                device.device_id,
            )
            return False

        logger.debug(
            "Loading EEP definition %s for device %s",
            profile,
            device.device_id,
        )

        try:
            eep_definition = load_eep_definition(profile)

        except EEPRegistryError as exc:
            logger.warning(
                "Skipping telegram for device %s due to missing EEP registry entry %s",
                device.device_id,
                profile,
            )

            if self._status_publisher is not None:
                self._status_publisher.publish_error(
                    component="runtime-decoder",
                    message="Missing EEP registry entry",
                    device_id=device.device_id,
                    sender_id=sender_id,
                    profile=profile,
                    telegram_rorg=telegram.eno_rorg,
                    payload_hex=payload_hex,
                    error=str(exc),
                )

            return False

        except Exception:
            logger.exception(
                "Skipping telegram for device %s due to invalid EEP registry entry %s",
                device.device_id,
                profile,
            )

            return False

        try:
            assessment = assess_telegram(
                rorg=telegram.eno_rorg, data=payload_hex, sender_id=sender_id,
                status=telegram.status, direction=telegram.normalized_direction or "rx",
                definition=eep_definition,
            )
            if assessment is not None and assessment.skip_decode:
                return False
            decoded = decode_runtime_telegram(
                eep_definition=eep_definition,
                payload_hex=payload_hex,
                status_hex=telegram.status,
                rorg=telegram.eno_rorg,
                direction=telegram.normalized_direction,
                sender_id=sender_id,
            )

            if (
                self._status_publisher is not None
                and logger.isEnabledFor(logging.DEBUG)
            ):
                self._status_publisher.publish_log(
                    level="debug",
                    component="runtime-decoder",
                    message="Runtime telegram decoded",
                    device_id=device.device_id,
                    sender_id=sender_id,
                    profile=profile,
                    telegram_rorg=telegram.eno_rorg,
                    telegram_type_id=decoded.telegram_type_id,
                    payload_hex=payload_hex,
                    status_hex=telegram.status,
                    fields=decoded.fields,
                    status_fields=decoded.status_fields,
                    decoded_channels={
                        channel_name: {
                            "value": channel.published_value,
                            **({"meaning": channel.meaning} if channel.meaning is not None else {}),
                            "raw_value": channel.raw_value,
                            "unit": channel.unit,
                            "semantic_role": channel.semantic_role,
                            "range_label": channel.range_label,
                            "object_type": channel.object_type,
                            "data_type": channel.data_type,
                        }
                        for channel_name, channel in decoded.values.items()
                    },
                )

        except Exception:
            logger.exception(
                "Runtime decoder failed for device %s using profile %s",
                device.device_id,
                profile,
            )

            return False

        self._publisher.publish_decoded_telegram(
            device=device,
            decoded=decoded,
            timestamp=telegram.timestamp,
            rorg=telegram.eno_rorg,
            data=payload_hex,
        )

        return True
