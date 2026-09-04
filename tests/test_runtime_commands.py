from __future__ import annotations

from typing import Any, cast

import pytest

from enocean_mqtt.gateway.runtime_commands import RuntimeCommandHandler
from enocean_mqtt.gateway.runtime_schema import (
    RuntimeCommandValidationError,
    RuntimeCommandValidator,
)


class _StatusPublisher:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def publish_log(self, **payload: Any) -> None:
        self.logs.append(payload)

    def publish_error(self, **payload: Any) -> None:
        self.errors.append(payload)


def _runtime_command_handler() -> RuntimeCommandHandler:
    handler = RuntimeCommandHandler.__new__(RuntimeCommandHandler)
    handler_for_test = cast(Any, handler)
    handler_for_test._handlers = {}
    handler_for_test._validator = RuntimeCommandValidator()
    handler_for_test._status_publisher = _StatusPublisher()
    return handler


def test_runtime_command_execute_validates_and_calls_handler() -> None:
    handler = _runtime_command_handler()
    calls: list[dict[str, Any]] = []

    handler.register(
        "sample.command",
        calls.append,
        required_fields={
            "value": int,
        },
    )

    payload = handler.execute(
        "sample.command",
        {
            "value": 42,
        },
    )

    assert payload == {
        "status": "accepted",
        "command": "sample.command",
    }
    assert calls == [
        {
            "command": "sample.command",
            "value": 42,
        }
    ]


def test_runtime_command_execute_rejects_invalid_payload() -> None:
    handler = _runtime_command_handler()
    handler.register(
        "sample.command",
        lambda payload: None,
        required_fields={
            "value": int,
        },
    )

    with pytest.raises(RuntimeCommandValidationError) as exc_info:
        handler.execute("sample.command", {})

    assert exc_info.value.error_type == "missing_argument"
