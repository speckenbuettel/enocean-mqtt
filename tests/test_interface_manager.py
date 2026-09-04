from collections.abc import Callable
from time import sleep
from typing import Any

from enocean_mqtt.esp3 import interface_manager as interface_manager_module
from enocean_mqtt.esp3.interface_manager import ESP3InterfaceManager
from enocean_mqtt.esp3.radio import RadioERP1Telegram
from enocean_mqtt.runtime_config import (
    InterfaceNetworkBridgeConfig,
    InterfaceTransportConfig,
    SerialReconnectConfig,
)


def test_interface_manager_connects_and_disconnects_named_interface() -> None:
    publisher = FakeStatusPublisher()
    fake_serial = FakeSerial()
    manager = ESP3InterfaceManager(
        interfaces=[
            InterfaceTransportConfig(
                interface_id="usb300_01",
                enabled=True,
                device="COM_TEST",
                base_id="FFAA8000",
            )
        ],
        telegram_callback=lambda _telegram: None,
        status_publisher=publisher,
        serial_factory=lambda **_kwargs: fake_serial,
    )

    connected_status = manager.connect("usb300_01")

    assert connected_status["interface_id"] == "usb300_01"
    assert connected_status["connected"] is True
    assert connected_status["base_id"] == "FFAA8000"
    assert publisher.statuses[-1]["interface_id"] == "usb300_01"
    assert publisher.statuses[-1]["connected"] is True

    disconnected_status = manager.disconnect("usb300_01")

    assert disconnected_status["connected"] is False
    assert fake_serial.closed is True
    assert publisher.statuses[-1]["connected"] is False


def test_interface_manager_refreshes_live_transport_metrics() -> None:
    publisher = FakeStatusPublisher()
    manager = ESP3InterfaceManager(
        interfaces=[
            InterfaceTransportConfig(
                interface_id="usb300_01",
                enabled=True,
                tx_enabled=True,
                device="COM_TEST",
            )
        ],
        telegram_callback=lambda _telegram: None,
        status_publisher=publisher,
        serial_factory=lambda **_kwargs: FakeSerial(),
    )
    manager.connect("usb300_01")
    transport = manager._transports["usb300_01"]
    transport.metrics.received_esp3_frames = 7

    manager.refresh_status()

    assert publisher.statuses[-1]["metrics"]["received_esp3_frames"] == 7
    manager.disconnect("usb300_01")


def test_interface_manager_reports_open_errors_without_hardware() -> None:
    publisher = FakeStatusPublisher()
    manager = ESP3InterfaceManager(
        interfaces=[
            InterfaceTransportConfig(
                interface_id="usb300_01",
                enabled=True,
                device="COM_TEST",
                base_id="FFAA8000",
                reconnect=SerialReconnectConfig(enabled=False),
            )
        ],
        telegram_callback=lambda _telegram: None,
        status_publisher=publisher,
        serial_factory=lambda **_kwargs: (_ for _ in ()).throw(
            OSError("port unavailable")
        ),
    )

    status = manager.connect("usb300_01")

    assert status["connected"] is False
    assert status["status"] == "error"
    assert status["last_error"] == "port unavailable"


def test_interface_manager_default_sender_uses_configured_default() -> None:
    publisher = FakeStatusPublisher()
    serial_a = FakeSerial()
    serial_b = FakeSerial()
    serials = {
        "COM_A": serial_a,
        "COM_B": serial_b,
    }
    manager = ESP3InterfaceManager(
        interfaces=[
            InterfaceTransportConfig(
                interface_id="usb300_01",
                enabled=True,
                device="COM_A",
                base_id="FFAA8000",
            ),
            InterfaceTransportConfig(
                interface_id="fam_usb_01",
                enabled=True,
                tx_enabled=True,
                device="COM_B",
                base_id="FFAA8100",
            ),
        ],
        telegram_callback=lambda _telegram: None,
        status_publisher=publisher,
        tx_enabled=True,
        default_interface="fam_usb_01",
        serial_factory=lambda **kwargs: serials[str(kwargs["port"])],
    )

    manager.connect("usb300_01")
    manager.connect("fam_usb_01")
    serial_b.on_write = lambda: manager._transports[
        "fam_usb_01"
    ]._response_codes.put(0)
    sender = manager.default_sender()
    assert sender is not None

    result = sender(
        RadioERP1Telegram(
            rorg="F6",
            data="30",
            sender_id="FFAA8101",
            status="30",
        )
    )

    assert serial_a.written == []
    assert len(serial_b.written) == 1
    assert result.transmission == "accepted"

    manager.stop_all()


def test_interface_manager_network_bridge_switches_from_serial(monkeypatch) -> None:
    publisher = FakeStatusPublisher()
    fake_serial = FakeSerial()
    fake_bridges: list[FakeSer2NetBridge] = []

    def bridge_factory(config):
        bridge = FakeSer2NetBridge(config)
        fake_bridges.append(bridge)
        return bridge

    monkeypatch.setattr(
        interface_manager_module,
        "Ser2NetBridge",
        bridge_factory,
    )
    manager = ESP3InterfaceManager(
        interfaces=[
            InterfaceTransportConfig(
                interface_id="usb300_01",
                enabled=True,
                device="COM_TEST",
                baudrate=57600,
                base_id="FFAA8000",
                network_bridge=InterfaceNetworkBridgeConfig(
                    enabled=True,
                    host="0.0.0.0",
                    port=7000,
                ),
            )
        ],
        telegram_callback=lambda _telegram: None,
        status_publisher=publisher,
        serial_factory=lambda **_kwargs: fake_serial,
    )

    manager.connect("usb300_01")
    bridged_status = manager.network_bridge_start("usb300_01")

    assert fake_serial.closed is True
    assert bridged_status["connected"] is False
    assert bridged_status["network_bridge"]["running"] is True
    assert bridged_status["network_bridge"]["port"] == 7000
    assert len(fake_bridges) == 1

    manager.connect("usb300_01")

    assert fake_bridges[0].stopped is True
    assert manager.status("usb300_01")["connected"] is True


def test_interface_manager_network_bridge_preflight_keeps_serial_connected(
    monkeypatch,
) -> None:
    publisher = FakeStatusPublisher()
    fake_serial = FakeSerial()

    def bridge_factory(config):
        return UnavailableFakeSer2NetBridge(config)

    monkeypatch.setattr(
        interface_manager_module,
        "Ser2NetBridge",
        bridge_factory,
    )
    manager = ESP3InterfaceManager(
        interfaces=[
            InterfaceTransportConfig(
                interface_id="usb300_01",
                enabled=True,
                device="COM_TEST",
                base_id="FFAA8000",
                network_bridge=InterfaceNetworkBridgeConfig(enabled=True),
            )
        ],
        telegram_callback=lambda _telegram: None,
        status_publisher=publisher,
        serial_factory=lambda **_kwargs: fake_serial,
    )

    manager.connect("usb300_01")

    try:
        manager.network_bridge_start("usb300_01")
    except RuntimeError as exc:
        assert "ser2net binary not found" in str(exc)
    else:
        raise AssertionError("network bridge start should fail")

    assert fake_serial.closed is False
    assert manager.status("usb300_01")["connected"] is True


class FakeStatusPublisher:
    def __init__(self) -> None:
        self.statuses: list[dict[str, Any]] = []
        self.logs: list[dict[str, Any]] = []

    def set_enocean_interface_status(
        self,
        *,
        interface_id: str | None = None,
        connected: bool,
        port: str | None,
        base_id: str | None = None,
        tx_enabled: bool = False,
        transport_status: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.statuses.append(
            {
                "interface_id": interface_id,
                "connected": connected,
                "port": port,
                "base_id": base_id,
                "tx_enabled": tx_enabled,
                "transport_status": transport_status,
                "metrics": metrics or {},
            }
        )

    def publish_log(
        self,
        level: str,
        component: str,
        message: str,
        **details: Any,
    ) -> None:
        self.logs.append(
            {
                "level": level,
                "component": component,
                "message": message,
                "details": details,
            }
        )


class FakeSerial:
    def __init__(self) -> None:
        self.closed = False
        self.written: list[bytes] = []
        self.on_write: Callable[[], None] | None = None

    def read(self, _size: int = 1) -> bytes:
        sleep(0.01)
        return b""

    def write(self, data: bytes) -> int:
        self.written.append(data)
        if self.on_write is not None:
            self.on_write()
        return len(data)

    def close(self) -> None:
        self.closed = True


class FakeSer2NetBridge:
    def __init__(self, config) -> None:
        self.config = config
        self.running = False
        self.stopped = False

    def ensure_available(self) -> None:
        return

    def start(self) -> None:
        self.running = True
        self.stopped = False

    def stop(self) -> None:
        self.running = False
        self.stopped = True

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "running": self.running,
            "host": self.config.host,
            "port": self.config.port,
            "serial_device": self.config.serial_device,
            "baudrate": self.config.baudrate,
            "ser2net_binary": self.config.ser2net_binary,
            "last_error": None,
        }


class UnavailableFakeSer2NetBridge(FakeSer2NetBridge):
    def ensure_available(self) -> None:
        raise RuntimeError("ser2net binary not found: ser2net")
