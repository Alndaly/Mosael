"""后端跟着壳走,并且说得清自己是谁(app/core/lifeline)。"""

from __future__ import annotations

import subprocess
import sys
import threading

from app.core import lifeline
from app.core.config import settings
from tests.util import fresh_client


def test_health_says_which_backend_this_is() -> None:
    body = fresh_client().get("/api/health").json()
    assert body["status"] == "ok" and body["app"] == "mosael"
    assert body["instance"] == lifeline.INSTANCE_ID
    assert body["data_dir_id"] == lifeline.data_dir_id(settings.data_dir)
    assert body["version"]
    assert str(settings.data_dir) not in str(body), "不登录就能读的接口不该暴露数据目录路径"


def test_data_dir_id_matches_the_shell() -> None:
    """壳(electron/backend-lifecycle.cjs)对同一个字符串算出同一个值 —— 那边的测试用的是同一个常量。"""
    assert lifeline.data_dir_id("/tmp/mosael-data") == "40a9c9be4789eb9d"


def test_a_dead_parent_is_noticed() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert lifeline.parent_alive(child.pid) is False
    import os

    assert lifeline.parent_alive(os.getpid()) is True
    assert lifeline.parent_alive(0) is False


def test_the_watchdog_shuts_down_once_the_parent_is_gone() -> None:
    gone = threading.Event()
    state = {"alive": True}
    lifeline.watch_parent(12345, interval=0.01, on_gone=gone.set, alive=lambda pid: state["alive"])
    assert not gone.wait(0.1), "壳还在就不该动"
    state["alive"] = False
    assert gone.wait(2), "壳没了要收尾"


def test_no_parent_pid_means_no_watchdog(monkeypatch) -> None:
    monkeypatch.delenv(lifeline.PARENT_ENV, raising=False)
    assert lifeline.watch_parent_from_env() is None
    monkeypatch.setenv(lifeline.PARENT_ENV, "not-a-pid")
    assert lifeline.watch_parent_from_env() is None
