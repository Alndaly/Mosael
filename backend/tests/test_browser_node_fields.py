"""浏览器节点的字段声明和它们真正交给执行器的东西。

- 「打开浏览器」:名字只在具名模式下出现、那时必填;档案只在池模式下出现、那时必填(active_when + required)。
- 「点击」的选择器 / 文字、「等待」的元素 / 网址 / 文字:恰好填一样(one_of)。
- 点击 / 输入的等待时长、提取 / 滚动的「找不到时输出空」:交到执行器手上。

交给执行器的那一份从 worker 通道上领出来看(worker_client 扮演 Electron),不把 run_action 换掉。
"""

from __future__ import annotations

import threading
import time
import types

from app.core.db import SessionLocal
from app.domain import browser as bdom
from app.domain.workflows import validate_graph
from app.domain.workflows.executors import browser as bx
from tests.util import fresh_client, worker_client


def _errors(*nodes: dict) -> list[str]:
    return validate_graph({"nodes": [{"id": "start", "type": "start", "config": {}}, *nodes], "edges": []})


def _node(node_type: str, **config) -> dict:
    return {"id": "n", "type": node_type, "config": config}


def test_具名模式要名字_池模式要档案_临时模式都不要() -> None:
    assert any("session_name" in e for e in _errors(_node("browser_open", session_mode="named")))
    assert any("profile_id" in e for e in _errors(_node("browser_open", session_mode="pool")))
    assert _errors(_node("browser_open")) == []  # 缺省就是临时
    assert _errors(_node("browser_open", session_mode="named", session_name="小红书")) == []


def test_点击的选择器和文字恰好一样() -> None:
    assert any("selector / text" in e for e in _errors(_node("browser_click", session="s")))
    assert any("只能填一个" in e for e in _errors(_node("browser_click", session="s", selector="#a", text="b")))
    assert _errors(_node("browser_click", session="s", text="发布")) == []


def test_等待的三样条件恰好一样_都在第一屏() -> None:
    from app.domain.workflows import NODE_TYPES

    specs = NODE_TYPES["browser_wait"]["config"]
    assert not any(specs[key].get("advanced") for key in ("selector", "url_contains", "text"))
    assert any("只能填一个" in e for e in _errors(_node("browser_wait", session="s", selector="#a", text="b")))
    assert _errors(_node("browser_wait", session="s", url_contains="/done")) == []


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
    deadline = time.monotonic() + 5
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


def test_点击和输入带上等待时长_没填就交给执行器用缺省() -> None:
    ws, sid = _session()
    args = _claimed_args(_in_node(ws, bx.browser_click, {"session": sid, "selector": "#go", "wait_ms": "8000"}))
    assert args["wait_ms"] == 8000
    args = _claimed_args(_in_node(ws, bx.browser_input, {"session": sid, "selector": "#q", "value": "hi"}))
    assert "wait_ms" not in args


def test_提取和滚动带上找不到时输出空的开关() -> None:
    ws, sid = _session()
    args = _claimed_args(_in_node(ws, bx.browser_extract, {"session": sid, "selector": ".p", "allow_missing": "true"}))
    assert args["allow_missing"] is True
    args = _claimed_args(_in_node(ws, bx.browser_scroll, {"session": sid, "selector": "#f"}))
    assert args["allow_missing"] is False
