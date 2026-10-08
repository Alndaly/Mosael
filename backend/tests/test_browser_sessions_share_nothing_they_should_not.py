"""浏览器会话之间不该共用的东西:登录分区、正在用的会话、执行器的时间。

- 具名会话的登录分区按**工作区 + 原名**定。此前是 `persist:rpa-<清洗后的名字>`:别的工作区同名就是同一份
  登录;「xhs-主号」「xhs-副号」都清洗成 `xhs`;「小红书」清洗成空串直接被拒。
- 具名会话同一时刻只归一次运行:此前不看 owner 就复用,两次运行在同一个视图上互相点,先结束的那次把会话关掉。
- 动作的执行超时从**认领**算,排队另算、另报;同一个会话串行、不同会话并发(认领时就分好)。
- 这一轮停了(别的节点失败)在飞的动作不再等。

执行器(Electron)不在测试里,由 worker_client 扮演它打 /api/browser/worker/*。
"""

from __future__ import annotations

import threading
import time

import pytest

from app.core.db import SessionLocal
from app.core.i18n import t
from app.db.models import BrowserAction
from app.domain import browser
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import browser as bx
from types import SimpleNamespace
from app.domain.workflows.run_scope import halt_scope
from tests.util import fresh_client, until, worker_client


def _workspaces(count: int = 1) -> list[str]:
    client = fresh_client()
    return [client.post("/api/workspaces", json={"name": f"W{i}"}).json()["id"] for i in range(count)]


def _named(ws: str, name: str, owner: str = "run-1") -> browser.BrowserSession:
    with SessionLocal() as db:
        return browser.open_session(
            db, workspace_id=ws, kind="named", name=name, owner_kind="workflow", owner_id=owner, actor=None
        )


def _claim(worker) -> dict | None:
    return worker.post("/api/browser/worker/claim", json={"worker": "test"}).json().get("action")


def _claim_when_queued(worker) -> dict:
    """调用方的线程排进去之后再领,领到为止。此前是睡 0.3 秒、只领一次 —— 线程起得晚就领了个空。"""
    box: dict = {}

    def claimed() -> bool:
        box["action"] = _claim(worker)
        return box["action"] is not None

    assert until(claimed, interval=0.05), "没领到动作"
    return box["action"]


def _queued_on(session_id: str) -> bool:
    with SessionLocal() as db:
        return db.query(BrowserAction).filter_by(session_id=session_id, status="queued").first() is not None


def _queue(session_id: str, ws: str, action: str = "wait") -> str:
    with SessionLocal() as db:
        row = BrowserAction(session_id=session_id, workspace_id=ws, action=action, args={}, status="queued")
        db.add(row)
        db.commit()
        return row.id


# ---------- 登录分区 ----------


def test_两个工作区里同名的具名会话_是两份登录() -> None:
    ws_a, ws_b = _workspaces(2)
    assert _named(ws_a, "xhs").partition != _named(ws_b, "xhs").partition


def test_清洗后会撞名的名字_各是各的登录() -> None:
    [ws] = _workspaces()
    partitions = {_named(ws, name, owner=name).partition for name in ("xhs-主号", "xhs-副号", "小红书2", "抖音2")}
    assert len(partitions) == 4


def test_全中文的名字能用_名字原样留着给人看() -> None:
    [ws] = _workspaces()
    session = _named(ws, " 小红书 ")
    assert session.name == "小红书"
    assert session.partition == browser.named_partition(ws, "小红书")


def test_空名字和超长名字直接拒() -> None:
    [ws] = _workspaces()
    for bad in ("", "   ", "x" * (browser.SESSION_NAME_MAX + 1)):
        with pytest.raises(browser.BrowserDomainError) as caught:
            _named(ws, bad)
        assert caught.value.key == "browserErr_invalidSessionName"


# ---------- 同一时刻只归一次运行 ----------


def test_另一次运行正开着这个具名会话_拒绝而不是共用() -> None:
    [ws] = _workspaces()
    first = _named(ws, "xhs", owner="run-1")
    with pytest.raises(browser.BrowserDomainError) as caught:
        _named(ws, "xhs", owner="run-2")
    assert caught.value.key == "browserErr_sessionBusy"
    assert "xhs" in str(caught.value)
    # 同一次运行里再开一次(第二个「打开浏览器」)照旧复用
    assert _named(ws, "xhs", owner="run-1").id == first.id


def test_上一次运行关掉之后_下一次运行接着用同一份登录() -> None:
    [ws] = _workspaces()
    first = _named(ws, "xhs", owner="run-1")
    with SessionLocal() as db:
        browser.close_session(db, first.id)
    second = _named(ws, "xhs", owner="run-2")
    assert second.id != first.id
    assert second.partition == first.partition


# ---------- 认领:同会话串行、不同会话并发 ----------


def test_同一会话上还有动作在跑_下一条先不发_别的会话照发() -> None:
    [ws] = _workspaces()
    worker = worker_client()
    with SessionLocal() as db:
        s1 = browser.open_session(db, workspace_id=ws, actor=None).id
        s2 = browser.open_session(db, workspace_id=ws, actor=None).id
    first = _queue(s1, ws)
    second = _queue(s1, ws)
    other = _queue(s2, ws)

    assert _claim(worker)["id"] == first
    assert _claim(worker)["id"] == other  # s1 还有一条在跑,跳过它排着的那条
    assert _claim(worker) is None

    with SessionLocal() as db:
        db.get(BrowserAction, first).status = "done"
        db.commit()
    assert _claim(worker)["id"] == second


# ---------- 超时:排队和执行分开算、分开报 ----------


def _call(sid: str, **kwargs) -> dict:
    holder: dict = {}

    def run() -> None:
        try:
            holder["result"] = browser.run_action(sid, "wait", {}, **kwargs)
        except browser.BrowserDomainError as exc:
            holder["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    holder["thread"] = thread
    return holder


def test_一直没人领_报没被领走_不是执行超时(monkeypatch) -> None:
    monkeypatch.setattr(browser, "QUEUE_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(browser, "_executor_contact", None)  # 没有执行器来过(前面的测试认领过,进程内记着)
    [ws] = _workspaces()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
    holder = _call(sid, timeout=30)
    holder["thread"].join(timeout=30)
    assert not holder["thread"].is_alive()
    assert holder["error"].key == "browserErr_actionNotClaimed"
    assert "没被领走" in t(holder["error"].key, "zh")


def test_执行超时从认领算_排队的时间不算进去(monkeypatch) -> None:
    """排了 1 秒以上,执行上限 0.6 秒:排着的时候不算超时(还领得到),领走之后才报执行超时。"""
    monkeypatch.setattr(browser, "QUEUE_TIMEOUT_SECONDS", 10)
    [ws] = _workspaces()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
    holder = _call(sid, timeout=0.6)
    #: 从它**排进去**算起至少排 1 秒(比执行上限长)。此前从起线程算:线程起得晚,排的就不到 0.6 秒,测的不是这件事。
    assert until(lambda: _queued_on(sid)), "动作一直没排进去"
    time.sleep(1.0)
    action = _claim(worker)
    #: 领得到 = 排了比执行上限还久也没被判超时(要是从排队算,它 0.6 秒时就已经落了失败,领不到)。
    #: 此前还量了「领走之后过了 ≥ 0.4 秒才报超时」:量的起点是领取的响应回来那一刻,响应慢 0.2 秒就不成立。
    assert action is not None
    holder["thread"].join(timeout=30)
    assert not holder["thread"].is_alive()
    assert holder["error"].key == "browserErr_actionTimeout"
    with SessionLocal() as db:
        assert db.get(BrowserAction, action["id"]).status == "failed"


# ---------- 这一轮停了 ----------


def test_调用方说不等了_动作落失败_执行器下次心跳就知道() -> None:
    [ws] = _workspaces()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
    stop = threading.Event()
    holder = _call(sid, timeout=30, should_stop=stop.is_set)
    action = _claim_when_queued(worker)
    stop.set()
    holder["thread"].join(timeout=30)
    assert not holder["thread"].is_alive()
    assert holder["error"].key == "browserErr_actionHalted"
    body = {"worker": "test", "claims": [{"action_id": action["id"], "lease_token": action["lease_token"]}]}
    assert worker.post("/api/browser/worker/heartbeat", json=body).json()["renewed"] == []


def test_兄弟节点失败后_在飞的浏览器节点当场放手_不取证(monkeypatch) -> None:
    """引擎在节点失败时立起停的信号(run_scope);此前 run_action 不看它,要陪着等满两分钟,还再截一张图。"""
    [ws] = _workspaces()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
    shots: list[str] = []
    monkeypatch.setattr(bx, "_failure_scene", lambda *args: shots.append("shot") or {})
    monkeypatch.setattr(bx, "_session_in", lambda db, scope, config: sid)
    errors: list[Exception] = []

    def node() -> None:
        with halt_scope() as halt:
            holder["halt"] = halt
            try:
                with SessionLocal() as db:
                    bx.browser_click(db, SimpleNamespace(workspace_id=ws, id="wf", name="wf"), {"selector": "#go"})
            except WorkflowDomainError as exc:
                errors.append(exc)

    holder: dict = {}
    thread = threading.Thread(target=node)
    thread.start()
    _claim_when_queued(worker)
    holder["halt"].set()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert errors and errors[0].key == "wfErr_cancelled"
    assert shots == []
