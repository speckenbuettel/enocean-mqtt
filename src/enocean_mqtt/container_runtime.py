"""Container initialization and credential-free liveness checks."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any


def _create(path: Path, content: bytes) -> None:
    """Create exclusively; never overwrite an existing deployment file."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
    except FileExistsError:
        pass


def initialize(root: Path, defaults: Path) -> None:
    for directory in ("config", "data/sqlite", "export"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in ("device-controller-mappings.json", "config.example.json"):
        _create(root / "config" / name, (defaults / name).read_bytes())
    config: dict[str, Any] = json.loads((defaults / "config.example.json").read_bytes())
    config["enocean"] = {"interfaces": [], "tx_enabled": False}
    config["mqtt"]["host"] = "mqtt"
    config["mqtt"]["username"] = None
    config["mqtt"]["password_file"] = None
    config["application"]["timezone"] = "UTC"
    config["sqlite"]["enabled"] = True
    config["web_api"]["authentication"]["enabled"] = True
    config["paths"]["devices_csv_import"] = "export/devices-import.csv"
    _create(root / "config/config.json", (json.dumps(config, indent=2) + "\n").encode())
    for name, payload in (
        ("devices.json", {"devices": []}),
        ("virtual-devices.json", {"virtual_devices": []}),
        ("sender-id-registry.json", {"manufacturer_id": "760", "interfaces": []}),
    ):
        _create(root / "config" / name, (json.dumps(payload, indent=2) + "\n").encode())


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd()
    try:
        if args == ["init"]:
            initialize(root, Path("/opt/enocean-defaults"))
            print("Initialized missing files only. Configure MQTT and provision an admin.")
            return 0
        if args == ["health"]:
            config = json.loads((root / "config/config.json").read_bytes())
            web = config.get("web_api", {})
            if web.get("enabled", False):
                host = web.get("host", "0.0.0.0")
                host = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
                with socket.create_connection((host, web.get("port", 8001)), timeout=3):
                    pass
            return 0
        if args and args[0] == "start":
            args.pop(0)
        if not (root / "config/config.json").is_file() and "--config" not in args:
            print("Missing config/config.json. Run 'init' first.", file=sys.stderr)
            return 1
        os.execvp("enocean-mqtt", ["enocean-mqtt", *args])
    except (OSError, ValueError):
        print("Container operation failed. Check configuration and mounted-directory permissions.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
