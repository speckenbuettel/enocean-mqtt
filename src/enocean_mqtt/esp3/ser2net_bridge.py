"""ser2net-backed ESP3 serial network bridge."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Ser2NetBridgeConfig:
    """Runtime options for one ser2net bridge process."""

    interface_id: str
    serial_device: str
    baudrate: int = 57600
    host: str = "0.0.0.0"
    port: int = 7000
    ser2net_binary: str = "ser2net"


class Ser2NetBridge:
    """Own a foreground ser2net process for one serial interface."""

    def __init__(self, config: Ser2NetBridgeConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._config_file: Path | None = None
        self._last_error: str | None = None
        self._started_at: float | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the ser2net process is still alive."""

        return self._process is not None and self._process.poll() is None

    def ensure_available(self) -> None:
        """Raise if ser2net cannot be executed."""

        if shutil.which(self.config.ser2net_binary) is None:
            self._last_error = (
                f"ser2net binary not found: {self.config.ser2net_binary}"
            )
            raise RuntimeError(self._last_error)

    def start(self) -> None:
        """Start ser2net in foreground mode."""

        if self.is_running:
            return

        self.ensure_available()
        binary = self.config.ser2net_binary
        config_file = self._write_config_file()

        try:
            self._process = subprocess.Popen(
                [
                    binary,
                    "-n",
                    "-c",
                    str(config_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as exc:
            self._last_error = str(exc)
            self._remove_config_file()
            raise

        time.sleep(0.1)

        if self._process.poll() is not None:
            return_code = self._process.returncode
            self._process = None
            self._last_error = (
                f"ser2net exited during startup with code {return_code}"
            )
            self._remove_config_file()
            raise RuntimeError(self._last_error)

        self._last_error = None
        self._started_at = time.time()

    def stop(self) -> None:
        """Stop ser2net and clean up the generated config file."""

        process = self._process
        self._process = None

        if process is not None and process.poll() is None:
            process.terminate()

            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)

        self._started_at = None
        self._remove_config_file()

    def status(self) -> dict[str, Any]:
        """Return bridge process status."""

        process = self._process
        pid = process.pid if process is not None and process.poll() is None else None

        return {
            "enabled": True,
            "running": self.is_running,
            "host": self.config.host,
            "port": self.config.port,
            "serial_device": self.config.serial_device,
            "baudrate": self.config.baudrate,
            "ser2net_binary": self.config.ser2net_binary,
            "pid": pid,
            "started_at": self._started_at,
            "last_error": self._last_error,
        }

    def _write_config_file(self) -> Path:
        self._remove_config_file()

        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix=f"enocean-mqtt-{self.config.interface_id}-",
            suffix=".ser2net.yaml",
            delete=False,
        )

        with handle:
            handle.write(self._config_text())

        self._config_file = Path(handle.name)

        return self._config_file

    def _remove_config_file(self) -> None:
        if self._config_file is None:
            return

        try:
            os.unlink(self._config_file)
        except FileNotFoundError:
            pass
        finally:
            self._config_file = None

    def _config_text(self) -> str:
        name = self.config.interface_id.replace("-", "_")
        serial_mode = f"{self.config.baudrate}n81"
        accepter = f"tcp,{self.config.host},{self.config.port}"

        return "\n".join(
            [
                "%YAML 1.1",
                "---",
                "connection: &" + name,
                "  accepter: " + accepter,
                "  connector: serialdev,"
                + self.config.serial_device
                + ","
                + serial_mode
                + ",local",
                "",
            ]
        )
