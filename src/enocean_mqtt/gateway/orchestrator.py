"""Gateway orchestration for semantic MQTT publishing."""

from __future__ import annotations

import logging

from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.eep.json_registry import EEPRegistryError, load_eep_definition
from enocean_mqtt.eep.runtime_decode_service import decode_runtime_telegram
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
    ) -> None:
        self._registry = registry
        self._publisher = publisher
        self._status_publisher = status_publisher

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

        if not sender_id:
            return False

        device = self._registry.get_by_device_id(sender_id)

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
                            "value": channel.value,
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
