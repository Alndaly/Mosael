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
    child.wait(timeout=30)
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


def test_the_desktop_shell_can_ask_the_backend_to_shut_down(monkeypatch) -> None:
    """Windows 上壳发不了 SIGTERM(Node 的 kill 在那边就是强杀):壳带着壳令牌请后端自己收尾退出。"""
    from app.api.routes import health
    from app.core.shell_origin import shell_token

    asked: list[str] = []
    monkeypatch.setattr(health.lifeline, "shut_down_soon", lambda reason: asked.append(reason))
    monkeypatch.setattr(settings, "local_desktop", True)
    client = fresh_client()

    assert client.post("/api/health/shutdown").status_code == 404, "没带壳令牌:当没有这个接口"
    assert client.post("/api/health/shutdown", headers={"X-Mosael-Shell": "guess"}).status_code == 404
    assert asked == []
    answer = client.post("/api/health/shutdown", headers={"X-Mosael-Shell": shell_token()})
    assert answer.status_code == 202
    assert len(asked) == 1


def test_a_team_server_has_no_shutdown_endpoint(monkeypatch) -> None:
    from app.api.routes import health
    from app.core.shell_origin import shell_token

    asked: list[str] = []
    monkeypatch.setattr(health.lifeline, "shut_down_soon", lambda reason: asked.append(reason))
    monkeypatch.setattr(settings, "local_desktop", False)
    answer = fresh_client().post("/api/health/shutdown", headers={"X-Mosael-Shell": shell_token()})
    assert answer.status_code == 404
    assert asked == []


def test_shutting_down_soon_answers_first_then_takes_the_signal_path(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(lifeline, "SHUTDOWN_DELAY", 0)
    monkeypatch.setattr(lifeline, "_shut_down", lambda reason: calls.append(reason))
    lifeline.shut_down_soon("asked by the shell").join(timeout=2)
    assert calls == ["asked by the shell"]
