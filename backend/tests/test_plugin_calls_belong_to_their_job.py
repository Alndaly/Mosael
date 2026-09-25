"""插件工具在任务里跑时,它的进程归那个任务:取消任务就真的停下它;同时在跑的插件调用有上限。

此前插件进程没登记到任务名下(`register_job_child` 只有导出在用)。用户在工作流上点停止,
改掉的只是一行状态 —— 那个插件进程照样跑到自己结束或超时,占着 CPU 和第三方额度。
而且没有任何准入:一个循环 × 并行分支能同时拉起几十个插件解释器。
"""

from __future__ import annotations

import textwrap
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain import jobs
from app.domain.jobs import cancel_job, detach_job_child, kill_job_child, register_job_child, reset_parent_job, set_parent_job
from app.domain.plugins import tools
from app.domain.plugins.runtime import PluginRuntimeError, ToolResult, execute_tool
from tests.test_plugin_declares_budget_and_keeps_data import install
from tests.util import fresh_client

SLEEPER = """
    import json, sys, time
    json.loads(sys.stdin.read())
    time.sleep(120)
    print(json.dumps({"ok": True, "output": {}}))
"""


def _running_job() -> str:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace_id, kind="workflow", status="running")
        db.add(job)
        db.commit()
        return job.id


def _sleeper(tmp_path: Path) -> tuple[Path, str]:
    plugin_dir = tmp_path / "sleeper"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(SLEEPER), encoding="utf-8")
    return plugin_dir, "main.py"


def _run_in_job(job_id: str, plugin: tuple[Path, str], outcome: dict[str, BaseException | None]) -> threading.Thread:
    """像 dispatch_job 那样,在一个把 job_id 当作父任务的线程里跑插件。"""

    def body() -> None:
        token = set_parent_job(job_id)
        try:
            execute_tool(*plugin, "sleep", {}, timeout=120)
            outcome["error"] = None
        except BaseException as exc:  # noqa: BLE001 — 交给主线程断言
            outcome["error"] = exc
        finally:
            reset_parent_job(token)

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def _wait_for_children(job_id: str, count: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if len(jobs._CHILDREN.get(job_id, ())) >= count:
            return
        time.sleep(0.05)
    raise AssertionError(f"{count} 个插件进程没有登记到任务 {job_id} 名下")


def test_取消任务会杀掉正在跑的插件进程(tmp_path) -> None:
    """工作流的并行分支里同时跑着两个插件节点:两个都归工作流那个任务,取消时两个都停。"""
    job_id = _running_job()
    plugin = _sleeper(tmp_path)
    outcomes: list[dict[str, BaseException | None]] = [{}, {}]
    threads = [_run_in_job(job_id, plugin, outcome) for outcome in outcomes]
    _wait_for_children(job_id, 2)

    started = time.monotonic()
    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id))
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), "插件进程比取消它的任务活得久"
    assert time.monotonic() - started < 15

    for outcome in outcomes:
        error = outcome["error"]
        # 是取消杀的,不是插件自己崩了 —— 原因要说对,不能是一句「退出码 -9」。
        assert isinstance(error, PluginRuntimeError) and error.key == "pluginErr_cancelled", error
    assert job_id not in jobs._CHILDREN, "跑完的插件进程还挂在任务名下"


def test_任务已经取消了才起的插件进程当场就停(tmp_path) -> None:
    job_id = _running_job()
    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id))
    outcome: dict[str, BaseException | None] = {}
    thread = _run_in_job(job_id, _sleeper(tmp_path), outcome)
    thread.join(timeout=15)
    assert not thread.is_alive()
    error = outcome["error"]
    assert isinstance(error, PluginRuntimeError) and error.key == "pluginErr_cancelled", error


def test_摘掉一个子进程不影响同一任务的其它子进程() -> None:
    job_id = _running_job()
    first, second = Mock(), Mock()
    register_job_child(job_id, first)
    register_job_child(job_id, second)
    try:
        detach_job_child(job_id, first)
        assert kill_job_child(job_id) is True
        first.kill.assert_not_called()
        second.kill.assert_called_once()
    finally:
        detach_job_child(job_id, second)
    assert kill_job_child(job_id) is False


def test_插件调用走的是任务总线上的那份名额() -> None:
    assert tools.PLUGIN_SLOTS is jobs.PLUGIN_SLOTS


def test_同时在跑的插件调用不超过名额(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance_id = install(tmp_path, [{"name": "go"}])
    monkeypatch.setattr(tools, "PLUGIN_SLOTS", threading.Semaphore(2))
    lock = threading.Lock()
    running = 0
    peak = 0

    def fake_execute(*args, **kwargs):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.3)
        with lock:
            running -= 1
        return ToolResult(output={}, state={})

    monkeypatch.setattr(tools, "execute_tool", fake_execute)

    statuses: list[str] = []

    def call() -> None:
        with SessionLocal() as db:
            statuses.append(tools.invoke(db, instance_id, "go", {}).status)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert statuses == ["succeeded"] * 5
    assert peak == 2, f"同时跑了 {peak} 个插件调用"
