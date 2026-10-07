"""浏览器动作排队排久了,说清楚是哪一种:排在同一会话前一条后面不算排队;执行器在线就报「排队超时、前面有 N 条」,
不在线才报「桌面端没开」。

此前排队 60 秒一律报 browserErr_actionNotClaimed(桌面端没开):同一次运行里另一条分支在同一个具名会话上做事,
前面那条长等待还没做完,它就被报成桌面端没开 —— 执行器明明一直在线、在心跳。
"""

from __future__ import annotations

import threading
import time

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserAction
from app.domain import browser
from tests.util import fresh_client, worker_client


def _ws() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _session(ws: str, name: str) -> str:
    with SessionLocal() as db:
        return browser.open_session(
            db, workspace_id=ws, kind="named", name=name, owner_kind="workflow", owner_id="run-1", actor=None
        ).id


def _in_thread(fn) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def go() -> None:
        try:
            box["value"] = fn()
        except browser.BrowserDomainError as exc:
            box["error"] = exc

    thread = threading.Thread(target=go)
    thread.start()
    return thread, box


@pytest.fixture
def short_queue(monkeypatch):
    monkeypatch.setattr(browser, "QUEUE_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(browser, "_executor_contact", None)


def test_排在同一会话前一条后面_不算排队_前一条做完就轮到它(short_queue) -> None:
    ws = _ws()
    sid = _session(ws, "xhs")
    worker = worker_client()

    first, first_box = _in_thread(lambda: browser.run_action(sid, "wait", {"timeout_ms": 60000}, timeout=30))
    time.sleep(0.5)
    claimed = worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
    assert claimed["action"] == "wait"

    # 同一次运行的另一条分支在同一个会话上做事:前面那条还在跑,它等的时间远超排队上限
    second, second_box = _in_thread(lambda: browser.run_action(sid, "extract", {"selector": "h1"}))
    time.sleep(2.5)
    assert second.is_alive() and "error" not in second_box
    # 执行器这时也领不走它(同一会话串行)
    assert worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"] is None

    worker.patch("/api/browser/worker/report", json={
        "action_id": claimed["id"], "status": "done", "lease_token": claimed["lease_token"],
    })
    # 前一条一做完,后一条的排队就开始计时(上面把上限压成了 1 秒)—— 当场就领,不先等前一条的线程收尾:
    # 机器一忙,那一下 join 就能超过 1 秒,后一条已经按排队超时放弃,这里领到的是 None。
    next_one = worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
    first.join(timeout=5)
    assert next_one["action"] == "extract"
    worker.patch("/api/browser/worker/report", json={
        "action_id": next_one["id"], "status": "done", "result": {"value": "标题"}, "lease_token": next_one["lease_token"],
    })
    second.join(timeout=5)
    assert second_box.get("value") == {"value": "标题"}


def test_执行器在线但前面排满了_报排队超时和前面有几条(short_queue) -> None:
    ws = _ws()
    busy, mine = _session(ws, "a"), _session(ws, "b")
    with SessionLocal() as db:
        db.add(BrowserAction(session_id=busy, workspace_id=ws, action="click", args={}, status="queued"))
        db.commit()
    # 执行器在线(心跳过),只是一直没领到这一条
    worker_client().post("/api/browser/worker/heartbeat", json={"worker": "w", "claims": []})

    with pytest.raises(browser.BrowserDomainError) as caught:
        browser.run_action(mine, "extract", {"selector": "h1"})
    assert caught.value.key == "browserErr_actionQueueTimeout"
    assert caught.value.params["ahead"] == 1
    assert "1" in str(caught.value) and "桌面端没开" not in str(caught.value)


def test_没有执行器来过_才报桌面端没开(short_queue) -> None:
    ws = _ws()
    sid = _session(ws, "xhs")
    with pytest.raises(browser.BrowserDomainError) as caught:
        browser.run_action(sid, "extract", {"selector": "h1"})
    assert caught.value.key == "browserErr_actionNotClaimed"
    with SessionLocal() as db:
        act = db.query(BrowserAction).filter(BrowserAction.session_id == sid).one()
        assert (act.status, act.error) == ("failed", "browserErr_actionNotClaimed")


def test_执行器很久没来_也算不在线(short_queue, monkeypatch) -> None:
    ws = _ws()
    sid = _session(ws, "xhs")
    monkeypatch.setattr(browser, "_executor_contact", time.monotonic() - browser.EXECUTOR_FRESH_SECONDS - 1)
    with pytest.raises(browser.BrowserDomainError) as caught:
        browser.run_action(sid, "extract", {"selector": "h1"})
    assert caught.value.key == "browserErr_actionNotClaimed"
