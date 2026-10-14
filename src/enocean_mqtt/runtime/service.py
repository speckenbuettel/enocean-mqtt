"""Runtime service facade for Web API and tooling access.

The service intentionally does not own runtime state. It provides a narrow
read facade over existing runtime components while the runtime-state ownership
model is being consolidated.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from enocean_mqtt.datapoints import DatapointRegistry, DatapointRuntimeRegistry
from enocean_mqtt.devices.projection import ApiDevice, ApiDeviceRegistry

DeviceStatesProvider = Callable[[], Mapping[str, Mapping[str, Any]]]


class DeviceStateProvider(Protocol):
    """Provider for current state of one runtime device."""

    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        """Return a copy or projection of current state for one device."""


class PhysicalDatapointWriter(Protocol):
    """Writer for TX-capable physical-device message datapoints."""

    def set_value(self, device_id: str, message: str, value: Any) -> None:
        """Submit one semantic message value for radio transmission."""


class VirtualDatapointWriter(Protocol):
    """Writer for virtual-device channel datapoints."""

    def set_value(self, virtual_device_id: str, channel: str, value: Any) -> None:
        """Submit one virtual channel value for radio transmission."""


@dataclass(frozen=True, slots=True)
class DeviceStatePayloads:
    """Device-state payloads with their semantic source label."""

    states: dict[str, dict[str, Any]]
    source: str


@dataclass(slots=True)
class RuntimeService:
    """Read facade over current runtime components.

    The service is deliberately thin. It must not introduce a second runtime
    cache beside the existing publisher and virtual-device runtime state.
    """

    datapoint_registry: DatapointRegistry
    api_device_registry: ApiDeviceRegistry
    device_publisher: DeviceStateProvider | None = None
    virtual_device_runtime: DeviceStateProvider | None = None
    device_tx_runtime: PhysicalDatapointWriter | None = None
    virtual_device_writer: VirtualDatapointWriter | None = None
    fallback_device_states_provider: DeviceStatesProvider | None = None
    fallback_source: str = "fallback"

    def get_devices(self) -> dict[str, Any]:
        """Return API-facing device discovery payload."""

        return self.api_device_registry.to_api_dict()

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Return one API-facing device discovery payload."""

        device = self.api_device_registry.get(device_id)

        if device is None:
            return None

        return device.to_api_dict()

    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        """Return current runtime state for one API-facing device."""

        device = self.api_device_registry.get(device_id)

        if device is None:
            return None

        return self._state_for_api_device(device)

    def get_device_states(self) -> dict[str, dict[str, Any]]:
        """Return current runtime states keyed by API-facing device ID."""

        return self._device_state_payloads().states

    def get_datapoints(self) -> dict[str, Any]:
        """Return datapoint discovery payload."""

        return self.datapoint_registry.to_api_dict()

    def get_datapoint(self, datapoint_id: str) -> dict[str, Any] | None:
        """Return one datapoint discovery payload."""

        datapoint = self.datapoint_registry.get(datapoint_id)

        if datapoint is None:
            return None

        return datapoint.to_api_dict()

    def get_datapoint_runtime_registry(self) -> DatapointRuntimeRegistry:
        """Return datapoint runtime overlay using current runtime state."""

        payloads = self._device_state_payloads()

        runtime = DatapointRuntimeRegistry.from_device_state_payloads(
            datapoints=self.datapoint_registry,
            device_states=payloads.states,
            source=payloads.source,
        )
        runtime.issues.extend(self.datapoint_registry.issues)

        return runtime

    def set_datapoint_value(self, datapoint_id: str, value: Any) -> None:
        """Route a writable semantic datapoint to its owning TX runtime."""

        datapoint = self.datapoint_registry.get(datapoint_id)
        if datapoint is None:
            raise KeyError(datapoint_id)
        if not datapoint.writable:
            raise PermissionError(f"Datapoint is read-only: {datapoint_id}")

        source = datapoint.source
        if source.collection == "messages" and source.device_id is not None:
            if self.device_tx_runtime is None:
                raise RuntimeError("Physical-device TX runtime is unavailable")
            self.device_tx_runtime.set_value(source.device_id, source.name, value)
            return

        if (
            source.collection == "virtual_channels"
            and source.virtual_device_id is not None
        ):
            writer = self.virtual_device_writer
            if writer is None:
                raise RuntimeError("Virtual-device TX runtime is unavailable")
            writer.set_value(source.virtual_device_id, source.name, value)
            return

        raise RuntimeError(f"Unsupported writable datapoint source: {datapoint_id}")

    def _device_state_payloads(self) -> DeviceStatePayloads:
        states: dict[str, dict[str, Any]] = {}

        for device in self.api_device_registry.devices:
            state = self._state_for_api_device(device)

            if state is not None:
                states[device.id] = state

        if states:
            return DeviceStatePayloads(
                states=states,
                source="runtime",
            )

        return DeviceStatePayloads(
            states=self._fallback_device_states(),
            source=self.fallback_source,
        )

    def _state_for_api_device(self, device: ApiDevice) -> dict[str, Any] | None:
        if device.source_type == "physical_device":
            return self._physical_device_state(device)

        return self._virtual_device_state(device)

    def _physical_device_state(self, device: ApiDevice) -> dict[str, Any] | None:
        if self.device_publisher is None or device.device_id is None:
            return None

        return self.device_publisher.get_device_state(device.device_id)

    def _virtual_device_state(self, device: ApiDevice) -> dict[str, Any] | None:
        if self.virtual_device_runtime is None or device.virtual_device_id is None:
            return None

        return self.virtual_device_runtime.get_device_state(
            device.virtual_device_id
        )

    def _fallback_device_states(self) -> dict[str, dict[str, Any]]:
        if self.fallback_device_states_provider is None:
            return {}

        return {
            str(device_id): dict(state)
            for device_id, state in self.fallback_device_states_provider().items()
        }
