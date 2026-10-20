"""Process-level controls for the gateway runtime."""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

ExecFunction = Callable[[str, list[str]], object]


@contextmanager
def shutdown_signals() -> Iterator[threading.Event]:
    """Request orderly shutdown on SIGTERM/SIGINT; restore embedding handlers."""
    stopped = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        stopped.set()

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for sig in previous:
            signal.signal(sig, request_stop)
        yield stopped
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def restart_current_process(
    *,
    executable: str | None = None,
    arguments: Sequence[str] | None = None,
    exec_function: ExecFunction = os.execv,
) -> None:
    """Replace the current process with a fresh gateway runtime.

    Re-executing in place keeps the process under the same systemd service or
    Docker container and does not depend on an external restart policy.
    """

    python_executable = executable or sys.executable
    runtime_arguments = list(arguments if arguments is not None else sys.argv)

    exec_function(
        python_executable,
        [python_executable, *runtime_arguments],
    )

    raise RuntimeError("Process re-execution returned unexpectedly")
