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
    assert _errors(_node("browser_open", session_mode="named")) == ["「打开浏览器」缺少必填:会话名称"]
    assert _errors(_node("browser_open", session_mode="pool")) == ["「打开浏览器」缺少必填:浏览器池档案"]
    assert _errors(_node("browser_open")) == []  # 缺省就是临时
    assert _errors(_node("browser_open", session_mode="named", session_name="小红书")) == []


def test_点击的选择器和文字恰好一样() -> None:
    assert _errors(_node("browser_click", session="s")) == ["「浏览器·点击」的 元素选择器 / 文本 要填一个"]
    assert _errors(_node("browser_click", session="s", selector="#a", text="b")) == [
        "「浏览器·点击」的 元素选择器 / 文本 只能填一个"
    ]
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


#: 按选择器找元素的六种节点:都能「在框架里」(同源 iframe)找。脚本节点自己写 JS,不需要这一格。
FRAME_NODES = ("browser_click", "browser_input", "browser_upload", "browser_extract", "browser_wait", "browser_scroll")


def test_按选择器找元素的节点都有在框架里这一格() -> None:
    from app.core.i18n import tr
    from app.domain.workflows import NODE_TYPES, config_label

    for node_type in FRAME_NODES:
        spec = NODE_TYPES[node_type]["config"]["frame"]
        assert spec["advanced"] is True and spec["type"] == "template", node_type
        assert tr(config_label("frame", spec)) == "在框架里"
    assert "frame" not in NODE_TYPES["browser_evaluate"]["config"]


def test_在框架里交到执行器手上() -> None:
    ws, sid = _session()
    cases = [
        (bx.browser_click, {"selector": "#frame-btn"}),
        (bx.browser_input, {"selector": "#frame-input", "value": "hi"}),
        (bx.browser_extract, {"selector": "#inframe"}),
        (bx.browser_wait, {"selector": "#frame-late"}),
        (bx.browser_scroll, {"selector": "#inframe"}),
    ]
    for fn, config in cases:
        args = _claimed_args(_in_node(ws, fn, {"session": sid, "frame": "#same", **config}))
        assert args["frame"] == "#same", fn.__name__
    args = _claimed_args(_in_node(ws, bx.browser_click, {"session": sid, "selector": "#btn"}))
    assert args["frame"] == "", "没填就是外层页面"


def test_上传在框架里也交到执行器手上(tmp_path) -> None:
    from app.domain.host_files import HostFile

    ws, sid = _session()
    (tmp_path / "a.txt").write_text("x")

    def run() -> None:
        bdom.upload_file(sid, HostFile(path=tmp_path / "a.txt"), selector="#frame-file", frame="#same")

    args = _claimed_args(run)
    assert (args["selector"], args["frame"]) == ("#frame-file", "#same")
