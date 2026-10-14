"""enocean-mqtt core package."""

from pathlib import Path

from enocean_mqtt.version import load_project_version

__all__ = ["__version__"]

__version__ = load_project_version(Path(__file__).resolve().parents[2] / "VERSION")
