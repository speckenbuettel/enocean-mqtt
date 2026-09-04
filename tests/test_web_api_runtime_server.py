import logging

from enocean_mqtt.web_api.runtime_server import _process_log_level


def test_uvicorn_uses_configured_process_log_level() -> None:
    root_logger = logging.getLogger()
    original_level = root_logger.level

    try:
        root_logger.setLevel(logging.WARNING)
        assert _process_log_level() == logging.WARNING
    finally:
        root_logger.setLevel(original_level)
