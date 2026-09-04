from __future__ import annotations

from collections.abc import Sequence

import pytest

from enocean_mqtt.gateway.process_control import restart_current_process


def test_restart_current_process_reexecutes_runtime_in_place() -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_execv(executable: str, arguments: Sequence[str]) -> object:
        calls.append((executable, list(arguments)))
        raise OSError("test replacement")

    with pytest.raises(OSError, match="test replacement"):
        restart_current_process(
            executable="/runtime/python",
            arguments=["/runtime/enocean-mqtt", "--config", "gateway.json"],
            exec_function=fake_execv,
        )

    assert calls == [
        (
            "/runtime/python",
            [
                "/runtime/python",
                "/runtime/enocean-mqtt",
                "--config",
                "gateway.json",
            ],
        )
    ]


def test_restart_current_process_rejects_returning_exec_function() -> None:
    with pytest.raises(RuntimeError, match="returned unexpectedly"):
        restart_current_process(
            executable="/runtime/python",
            arguments=["/runtime/enocean-mqtt"],
            exec_function=lambda executable, arguments: None,
        )
