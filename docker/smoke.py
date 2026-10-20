"""Hardware-free acceptance test for a built Linux image using disposable Docker data."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

# Synthetic fixture, deliberately not an operational credential.
SMOKE_TOKEN = base64.b64encode(b"isolated-smoke-fixture-only-32bytes").decode("ascii")


def run(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *args], check=check, capture_output=True, text=True)
    return result.stdout.strip()


def main(image: str) -> None:
    suffix = uuid.uuid4().hex[:12]
    network, broker, gateway = (f"enocean-{part}-{suffix}" for part in ("net", "mqtt", "app"))
    with tempfile.TemporaryDirectory(prefix="enocean-docker-") as folder:
        root = Path(folder)
        for name in ("config", "data", "export"):
            (root / name).mkdir()
        mounts = [arg for name in ("config", "data", "export")
                  for arg in ("--mount", f"type=bind,src={root / name},dst=/app/{name}")]
        common = ["--user", f"{os.getuid()}:{os.getgid()}", *mounts]
        try:
            run("network", "create", network)
            broker_config = root / "mosquitto.conf"
            broker_config.write_text("listener 1883\nallow_anonymous true\npersistence false\n")
            run("run", "-d", "--name", broker, "--network", network, "--network-alias", "mqtt",
                "--mount", (f"type=bind,src={broker_config},"
                            "dst=/mosquitto/config/mosquitto.conf,readonly"),
                "eclipse-mosquitto:2")
            run("run", "--rm", *common, image, "init")
            config_file = root / "config/config.json"
            config = json.loads(config_file.read_text())
            assert config["web_api"]["authentication"]["enabled"]
            assert config["enocean"]["interfaces"] == []
            config["mqtt"]["base_topic"] = "smoke"
            config_file.write_text(json.dumps(config))
            secrets_dir = root / "config/secrets"
            secrets_dir.mkdir(mode=0o700)
            tokens = secrets_dir / "api-tokens.json"
            tokens.write_text(json.dumps({"tokens": [
                {"name": "smoke", "token": SMOKE_TOKEN, "roles": ["admin"]},
            ]}))
            tokens.chmod(0o600)
            before = config_file.read_bytes(), tokens.read_bytes()
            run("run", "--rm", *common, image, "init")
            assert before == (config_file.read_bytes(), tokens.read_bytes())
            marker = root / "config/persistence-marker"
            marker.write_text("preserve")
            options = ["run", "-d", "--name", gateway, "--network", network, "--read-only",
                       "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                       "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777", *common, image]
            probe = (
                "import json, urllib.request; "
                "r=urllib.request.Request('http://127.0.0.1:8001/api/v1/gateway/version', "
                f"headers={{'Authorization':'Bearer {SMOKE_TOKEN}'}}); "
                "v=json.load(urllib.request.urlopen(r,timeout=3)); "
                "assert v['version']==open('VERSION').read().strip()"
            )
            for cycle in range(2):
                run(*options)
                for _attempt in range(60):
                    result = subprocess.run(
                        ["docker", "exec", gateway, "python", "-c", probe],
                        capture_output=True, text=True,
                    )
                    if result.returncode == 0:
                        break
                    time.sleep(1)
                else:
                    print(result.stderr[-3000:], file=sys.stderr)
                    raise RuntimeError("Gateway API did not become ready")
                run("exec", gateway, "python", "-m", "enocean_mqtt.container_runtime", "health")
                run("exec", gateway, "python", "-c",
                    "import urllib.request,urllib.error; "
                    "r=urllib.request.Request('http://127.0.0.1:8001/api/v1/gateway/version'); "
                    "\ntry: urllib.request.urlopen(r); raise AssertionError('Unprotected API')"
                    "\nexcept urllib.error.HTTPError as e: assert e.code in (401,403)")
                run("exec", gateway, "python", "-c",
                    "from pathlib import Path; "
                    "from enocean_mqtt.eep.json_registry import load_eep_definition; "
                    "p=list(Path('eep/registry').glob('*.json')); assert p; "
                    "[load_eep_definition(f.stem) for f in p]")
                run("exec", gateway, "python", "-c",
                    "import sqlite3; c=sqlite3.connect('data/sqlite/enocean-mqtt.sqlite'); "
                    + ("c.execute('PRAGMA user_version=123'); c.commit()" if cycle == 0 else
                       "assert c.execute('PRAGMA user_version').fetchone()[0]==123"))
                run("stop", "--time", "30", gateway)
                assert run("inspect", "--format", "{{.State.ExitCode}}", gateway) == "0"
                assert run("exec", broker, "mosquitto_sub", "-t", "smoke/gateway/status",
                           "-C", "1", "-W", "5") == "offline"
                run("rm", gateway)
            assert marker.read_text() == "preserve"
            assert before == (config_file.read_bytes(), tokens.read_bytes())
            print("Container smoke passed: auth, profiles, read-only mode, SIGTERM, persistence")
        except Exception:
            print(run("logs", "--tail", "80", gateway, check=False), file=sys.stderr)
            # Docker sends application logs to stderr; retain diagnostic evidence
            # from this isolated fixture before disposing of its containers.
            logs = subprocess.run(["docker", "logs", "--tail", "80", gateway],
                                  capture_output=True, text=True)
            print(logs.stderr, file=sys.stderr)
            raise
        finally:
            run("rm", "-f", gateway, check=False)
            run("rm", "-f", broker, check=False)
            run("network", "rm", network, check=False)


if __name__ == "__main__":
    main(sys.argv[1])
