"""Runtime control hooks shared with the embedded Web API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

InterfaceCommand = Callable[[str | None], dict[str, Any]]
InterfaceStatus = Callable[[str | None], dict[str, Any]]

_interface_status_provider: InterfaceStatus | None = None
_interface_connect: InterfaceCommand | None = None
_interface_disconnect: InterfaceCommand | None = None
_interface_reconnect: InterfaceCommand | None = None
_interface_network_bridge_start: InterfaceCommand | None = None
_interface_network_bridge_stop: InterfaceCommand | None = None
_interface_network_bridge_restart: InterfaceCommand | None = None


def configure_interface_controls(
    *,
    status_provider: InterfaceStatus | None,
    connect: InterfaceCommand | None,
    disconnect: InterfaceCommand | None,
    reconnect: InterfaceCommand | None,
    network_bridge_start: InterfaceCommand | None = None,
    network_bridge_stop: InterfaceCommand | None = None,
    network_bridge_restart: InterfaceCommand | None = None,
) -> None:
    """Expose live interface controls to the embedded Web API."""

    global _interface_status_provider
    global _interface_connect
    global _interface_disconnect
    global _interface_reconnect
    global _interface_network_bridge_start
    global _interface_network_bridge_stop
    global _interface_network_bridge_restart

    _interface_status_provider = status_provider
    _interface_connect = connect
    _interface_disconnect = disconnect
    _interface_reconnect = reconnect
    _interface_network_bridge_start = network_bridge_start
    _interface_network_bridge_stop = network_bridge_stop
    _interface_network_bridge_restart = network_bridge_restart


def interface_controls_available() -> bool:
    """Return whether live interface controls are registered."""

    return all(
        callback is not None
        for callback in (
            _interface_status_provider,
            _interface_connect,
            _interface_disconnect,
            _interface_reconnect,
            _interface_network_bridge_start,
            _interface_network_bridge_stop,
            _interface_network_bridge_restart,
        )
    )


def interface_status(interface_id: str | None = None) -> dict[str, Any]:
    """Return live interface status via the registered runtime hook."""

    if _interface_status_provider is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_status_provider(interface_id)


def interface_connect(interface_id: str | None = None) -> dict[str, Any]:
    """Connect a live interface via the registered runtime hook."""

    if _interface_connect is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_connect(interface_id)


def interface_disconnect(interface_id: str | None = None) -> dict[str, Any]:
    """Disconnect a live interface via the registered runtime hook."""

    if _interface_disconnect is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_disconnect(interface_id)


def interface_reconnect(interface_id: str | None = None) -> dict[str, Any]:
    """Reconnect a live interface via the registered runtime hook."""

    if _interface_reconnect is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_reconnect(interface_id)


def interface_network_bridge_start(
    interface_id: str | None = None,
) -> dict[str, Any]:
    """Start a ser2net bridge via the registered runtime hook."""

    if _interface_network_bridge_start is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_network_bridge_start(interface_id)


def interface_network_bridge_stop(
    interface_id: str | None = None,
) -> dict[str, Any]:
    """Stop a ser2net bridge via the registered runtime hook."""

    if _interface_network_bridge_stop is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_network_bridge_stop(interface_id)


def interface_network_bridge_restart(
    interface_id: str | None = None,
) -> dict[str, Any]:
    """Restart a ser2net bridge via the registered runtime hook."""

    if _interface_network_bridge_restart is None:
        raise RuntimeError("Interface controls are not available")

    return _interface_network_bridge_restart(interface_id)
