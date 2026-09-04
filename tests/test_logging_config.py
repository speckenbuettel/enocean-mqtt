import json
import logging

import pytest

from enocean_mqtt.logging_config import JSONLogFormatter, configure_logging
from enocean_mqtt.runtime_config import LoggingConfig, LoggingLevel


def test_json_log_formatter_emits_structured_record() -> None:
    record = logging.LogRecord(
        name="enocean_mqtt.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=12,
        msg="Gerät %s",
        args=("A",),
        exc_info=None,
    )

    payload = json.loads(JSONLogFormatter().format(record))

    assert payload["level"] == "WARNING"
    assert payload["logger"] == "enocean_mqtt.test"
    assert payload["message"] == "Gerät A"
    assert payload["timestamp"].endswith("Z")


def test_configure_logging_applies_level_and_json_format() -> None:
    configure_logging(LoggingConfig(level="DEBUG", format="json"))

    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert isinstance(root_logger.handlers[0].formatter, JSONLogFormatter)


@pytest.mark.parametrize(
    ("configured_level", "emitted_message", "filtered_message"),
    [
        ("INFO", "operational transition", "telegram trace"),
        ("WARNING", "degraded operation", "operational transition"),
    ],
)
def test_configure_logging_filters_messages_below_threshold(
    configured_level: LoggingLevel,
    emitted_message: str,
    filtered_message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(LoggingConfig(level=configured_level, format="text"))
    logger = logging.getLogger("enocean_mqtt.test")

    if configured_level == "INFO":
        logger.debug(filtered_message)
        logger.info(emitted_message)
    else:
        logger.info(filtered_message)
        logger.warning(emitted_message)

    captured = capsys.readouterr().err
    assert emitted_message in captured
    assert filtered_message not in captured
