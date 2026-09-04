"""In-memory datapoint registry."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from enocean_mqtt.datapoints.models import Datapoint
from enocean_mqtt.datapoints.projection import project_from_config_files


@dataclass(slots=True)
class DatapointRegistry:
    """In-memory API datapoint registry."""

    datapoints: list[Datapoint]
    issues: list[dict[str, Any]] = dataclass_field(default_factory=list)

    @classmethod
    def from_config_files(
        cls,
        *,
        devices_file: str | Path,
        virtual_devices_file: str | Path | None = None,
    ) -> DatapointRegistry:
        """Build a read-only datapoint registry from configured devices."""

        datapoints, issues = project_from_config_files(
            devices_file=devices_file,
            virtual_devices_file=virtual_devices_file,
        )

        return cls(
            datapoints=sorted(datapoints, key=lambda item: item.id),
            issues=issues,
        )

    def by_device(self, device_id: str) -> list[Datapoint]:
        """Return datapoints belonging to an API-facing device ID."""

        return [
            datapoint
            for datapoint in self.datapoints
            if datapoint.device_id == device_id
        ]

    def get(self, datapoint_id: str) -> Datapoint | None:
        """Return one datapoint by ID."""

        for datapoint in self.datapoints:
            if datapoint.id == datapoint_id:
                return datapoint

        return None

    def to_api_dict(self) -> dict[str, Any]:
        """Return the API list payload."""

        return {
            "datapoints": [
                datapoint.to_api_dict()
                for datapoint in self.datapoints
            ],
            "count": len(self.datapoints),
            "issues": self.issues,
        }
