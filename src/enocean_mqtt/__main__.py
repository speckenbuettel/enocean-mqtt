"""Primary runtime entrypoint for enocean-mqtt.

This module intentionally delegates to the existing runtime startup
implementation while the runtime architecture is being consolidated.

Target invocation:

    python -m enocean_mqtt
"""

from __future__ import annotations

import sys

from enocean_mqtt.instance_lock import InstanceAlreadyRunningError, instance_lock
from enocean_mqtt.replay.mqtt_replay import main as runtime_main


def main() -> None:
    """Run exactly one gateway process for the current operating-system user."""

    try:
        with instance_lock():
            runtime_main()
    except InstanceAlreadyRunningError as exc:
        print(f"enocean-mqtt startup refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
