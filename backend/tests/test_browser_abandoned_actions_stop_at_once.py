"""调用方不等了(运行停下、动作超时),执行器一拍之内就知道、停手;失败现场的截图不排在那条被放弃的动作后面。

此前执行器只靠 20 秒一次的心跳续约失败才中止:运行已经停了,它还在页面上接着点、接着等最多 20 秒;
而失败现场那张截图排在同一会话上,8 秒的截图上限先到,失败记录里就没有图。
"""

from __future__ import annotations

import threading
import time

from app.core.db import SessionLocal
from app.domain import browser
from tests.util import fresh_client, worker_client


def _session(ws: str) -> str:
    with SessionLocal() as db:
        return browser.open_session(db, workspace_id=ws, actor=None).id


def _in_thread(fn) -> dict:
    box: dict = {}

    def go() -> None:
        try:
            box["value"] = fn()
        except browser.BrowserDomainError as exc:
            box["error"] = exc

    box["thread"] = threading.Thread(target=go)
    box["thread"].start()
    return box


def _claim(worker) -> dict:
    for _ in range(50):
        action = worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
        if action:
            return action
        time.sleep(0.05)
    raise AssertionError("没领到动作")


def _abandoned(worker, *claimed: dict) -> list[str]:
    claims = [{"action_id": one["id"], "lease_token": one["lease_token"]} for one in claimed]
    return worker.post("/api/browser/worker/abandoned", json={"worker": "w", "claims": claims}).json()["abandoned"]


def test_运行停下之后_执行器下一拍问就知道这条已经放弃了() -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = _session(ws)
    worker = worker_client()
    stop = threading.Event()
    box = _in_thread(lambda: browser.run_action(sid, "wait", {"timeout_ms": 60000}, timeout=60, should_stop=stop.is_set))
    claimed = _claim(worker)
    assert _abandoned(worker, claimed) == []  # 还在等它:不放弃

    stop.set()
    box["thread"].join(timeout=5)
    assert box["error"].key == "browserErr_actionHalted"
    assert _abandoned(worker, claimed) == [claimed["id"]]


def test_问放弃名单不续约_不归你的令牌也算放弃() -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = _session(ws)
    worker = worker_client()
    box = _in_thread(lambda: browser.run_action(sid, "wait", {}, timeout=60))
    claimed = _claim(worker)
    assert _abandoned(worker, {**claimed, "lease_token": "别人的"}) == [claimed["id"]]
    worker.patch("/api/browser/worker/report", json={
        "action_id": claimed["id"], "status": "done", "lease_token": claimed["lease_token"],
    })
    box["thread"].join(timeout=5)


def test_动作超时之后_失败现场的截图马上就能领走_不等被放弃的那条做完() -> None:
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors import browser as executor

    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = _session(ws)
    worker = worker_client()

    def wait_then_fail() -> dict:
        try:
            executor._run(sid, "wait", {"selector": "#never", "timeout_ms": 100}, timeout=0.5)
        except WorkflowDomainError as exc:
            return exc.details
        raise AssertionError("应该超时")

    box = _in_thread(wait_then_fail)
    claimed = _claim(worker)
    assert claimed["action"] == "wait"
    # 执行器没回报(还在页面上等);调用方 0.5 秒超时放手,接着要一张失败现场
    shot = _claim(worker)
    assert shot["action"] == "screenshot" and shot["session_id"] == sid
    assert _abandoned(worker, claimed) == [claimed["id"]]
    worker.patch("/api/browser/worker/report", json={
        "action_id": shot["id"], "status": "done", "result": {"value": "data:image/png;base64,AA"},
        "lease_token": shot["lease_token"],
    })
    box["thread"].join(timeout=5)
    assert box["value"]["screenshot"] == "data:image/png;base64,AA"
