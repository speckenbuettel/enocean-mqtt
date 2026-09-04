import json
from pathlib import Path

import pytest

from enocean_mqtt.instance_lock import (
    InstanceAlreadyRunningError,
    instance_lock,
)


def test_instance_lock_rejects_a_second_owner_and_reports_pid(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"

    with instance_lock(path):
        owner = json.loads(path.read_text(encoding="utf-8"))
        with pytest.raises(InstanceAlreadyRunningError, match=rf"pid={owner['pid']}"):
            with instance_lock(path):
                pass


def test_instance_lock_can_be_reacquired_after_release(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"

    with instance_lock(path):
        pass
    with instance_lock(path) as acquired_path:
        assert acquired_path == path
