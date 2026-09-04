"""Deprecated DolphinView replay helper.

This legacy helper currently references removed busmonitor export APIs.
The canonical replay runtime is implemented in mqtt_replay.py.
"""

from __future__ import annotations


def main() -> None:
    """Legacy compatibility entrypoint."""

    raise RuntimeError(
        "replay_dolphinview.py is deprecated. "
        "Use enocean_mqtt.replay.mqtt_replay instead."
    )


if __name__ == "__main__":
    main()
