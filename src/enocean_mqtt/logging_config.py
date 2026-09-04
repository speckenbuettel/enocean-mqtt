"""Console logging configuration."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from enocean_mqtt.runtime_config import LoggingConfig


class JSONLogFormatter(logging.Formatter):
    """Render one structured JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(config: LoggingConfig) -> None:
    """Apply validated process-wide console logging configuration."""

    handler = logging.StreamHandler()
    if config.format == "json":
        handler.setFormatter(JSONLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(
        level=getattr(logging, config.level),
        handlers=[handler],
        force=True,
    )
