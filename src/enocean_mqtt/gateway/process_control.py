"""Process-level controls for the gateway runtime."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence

ExecFunction = Callable[[str, list[str]], object]


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
