"""「执行脚本」不再把 `{{上游.输出}}` 拼进脚本:脚本(以及「代码」节点的代码)不插值,上游的值放进 input,原样作为数据交给执行器。

交给执行器的那一份从 worker 通道上领出来看(worker_client 扮演 Electron),不把 run_action 换掉。
"""

from __future__ import annotations

import threading
import time
import types

from app.core.db import SessionLocal
from app.domain import browser as bdom
from app.domain.workflows.binding import interpolate_node_config
from app.domain.workflows.executors import browser as bx
from tests.util import fresh_client, worker_client


def test_执行脚本的脚本不插值_入参插值() -> None:
    context = {"n": {"title": '"); alert(1); ("'}}
    config = interpolate_node_config(
        "browser_evaluate",
        {"session": "s", "expression": "input.title + '{{n.title}}'", "input": {"title": "{{n.title}}"}},
        context,
    )
    assert config["expression"] == "input.title + '{{n.title}}'"  # 原样,不拼进代码
    assert config["input"] == {"title": '"); alert(1); ("'}


def test_代码节点的代码也不插值() -> None:
    config = interpolate_node_config("code", {"code": "output = {{n.v}}", "input": {"v": "{{n.v}}"}}, {"n": {"v": 5}})
    assert config["code"] == "output = {{n.v}}"
    assert config["input"] == {"v": 5}


def _claimed_args(run) -> dict:
    """在另一个线程里跑节点,扮演执行器领出它的动作、回报成功,交回领到的参数。"""
    worker = worker_client()
    error: list[Exception] = []

    def node() -> None:
        try:
            run()
        except Exception as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=node)
    thread.start()
    deadline = time.monotonic() + 30
    action = None
    while action is None and time.monotonic() < deadline:
        action = worker.post("/api/browser/worker/claim", json={"worker": "t"}).json().get("action")
        time.sleep(0.05)
    assert action is not None, error
    worker.patch("/api/browser/worker/report", json={
        "action_id": action["id"], "status": "done", "result": {"value": "ok"}, "lease_token": action["lease_token"],
    })
    thread.join(timeout=5)
    assert not error, error
    return action["args"]


def _session() -> tuple[str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        return ws, bdom.open_session(db, workspace_id=ws, actor=None).id


def _scope(ws: str):
    return types.SimpleNamespace(workspace_id=ws, id="wf-test", name="wf")


def _in_node(ws: str, fn, config: dict):
    def run() -> None:
        with SessionLocal() as db:
            fn(db, _scope(ws), config)
    return run


def test_执行脚本把入参原样交给执行器() -> None:
    ws, sid = _session()
    args = _claimed_args(_in_node(ws, bx.browser_evaluate, {
        "session": sid, "expression": "input.a + 1", "input": {"a": 41},
    }))
    # origin:这一步是哪次运行、哪个节点发起的(执行器交回的下载 / 截图据此记出处);不在工作流里时都是空串。
    assert args == {"expression": "input.a + 1", "input": {"a": 41}, "origin": {"run": "", "node": ""}}
