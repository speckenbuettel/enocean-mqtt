"""Central runtime state management."""

from __future__ import annotations

from enocean_mqtt.gateway.status import GatewayStatusPublisher


class RuntimeStateManager:
    """Manage global runtime mode transitions."""

    VALID_RUNTIME_MODES = {
        "live",
        "replay",
    }

    def __init__(
        self,
        status_publisher: GatewayStatusPublisher,
        initial_runtime_mode: str = "live",
    ) -> None:
        if initial_runtime_mode not in self.VALID_RUNTIME_MODES:
            raise ValueError(
                f"Unsupported runtime mode: {initial_runtime_mode}"
            )

        self._status_publisher = status_publisher
        self._runtime_mode = initial_runtime_mode

        self._status_publisher.set_runtime_mode(
            initial_runtime_mode
        )

    @property
    def runtime_mode(self) -> str:
        """Return active runtime mode."""

        return self._runtime_mode

    def switch_to_live(
        self,
        reason: str,
    ) -> None:
        """Switch runtime into live mode."""

        self._switch_runtime_mode(
            new_runtime_mode="live",
            reason=reason,
        )

    def switch_to_replay(
        self,
        reason: str,
    ) -> None:
        """Switch runtime into replay mode."""

        self._switch_runtime_mode(
            new_runtime_mode="replay",
            reason=reason,
        )

    def _switch_runtime_mode(
        self,
        new_runtime_mode: str,
        reason: str,
    ) -> None:
        if new_runtime_mode not in self.VALID_RUNTIME_MODES:
            raise ValueError(
                f"Unsupported runtime mode: {new_runtime_mode}"
            )

        previous_runtime_mode = self._runtime_mode

        if previous_runtime_mode == new_runtime_mode:
            return

        self._runtime_mode = new_runtime_mode

        self._status_publisher.set_runtime_mode(
            new_runtime_mode
        )

        self._status_publisher.publish_log(
            level="info",
            component="runtime",
            message="Runtime mode changed",
            previous_runtime_mode=previous_runtime_mode,
            new_runtime_mode=new_runtime_mode,
            reason=reason,
        )
