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


class _Clock:
    """浏览器域读的那只钟(`browser.time.monotonic`):只在测试拨它的时候走;`sleep` 照真的睡,轮询照常转。

    记下每条线程读了几次 —— 「后一条的轮询已经看见拨过的钟了」要按那条线程算,前一条也在轮询。
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self._lock = threading.Lock()
        self._reads: dict[int, int] = {}

    def monotonic(self) -> float:
        with self._lock:
            ident = threading.get_ident()
            self._reads[ident] = self._reads.get(ident, 0) + 1
            return self.now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += seconds

    def reads(self, thread: threading.Thread) -> int:
        with self._lock:
            return self._reads.get(thread.ident or 0, 0)

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)


def _until(predicate, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("等待条件超时")


def _claim(worker) -> dict:
    return _until(lambda: worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"])


def _queued(session_id: str, action: str) -> bool:
    with SessionLocal() as db:
        return db.query(BrowserAction).filter(
            BrowserAction.session_id == session_id, BrowserAction.action == action).first() is not None


def test_排在同一会话前一条后面_不算排队_前一条做完就轮到它(short_queue, monkeypatch) -> None:
    """排队上限压成 1 秒,后一条在同一会话前一条后面「等」2.5 秒 —— 这 2.5 秒是**拨钟**拨出来的,不是睡出来的。

    此前真睡 2.5 秒,再要求「前一条一报完成就在 1 秒内领走后一条」:机器一忙(并行满载),报完成到领取之间就超过 1 秒,
    后一条已经按排队超时放弃 —— 测试红,而被测的规矩没错。钟不走,「前一条做完之后」那段排队就是 0,领取快慢无所谓;
    要是有人把「排在前一条后面」也算进排队,拨过的 2.5 秒照样让后一条超时放弃,断言照样红。
    """
    clock = _Clock()
    monkeypatch.setattr(browser, "time", clock)
    ws = _ws()
    sid = _session(ws, "xhs")
    worker = worker_client()

    first, first_box = _in_thread(lambda: browser.run_action(sid, "wait", {"timeout_ms": 60000}, timeout=30))
    claimed = _claim(worker)
    assert claimed["action"] == "wait"

    # 同一次运行的另一条分支在同一个会话上做事:前面那条还在跑,它等的时间远超排队上限
    second, second_box = _in_thread(lambda: browser.run_action(sid, "extract", {"selector": "h1"}))
    _until(lambda: _queued(sid, "extract"))
    clock.advance(2.5)
    seen = clock.reads(second)
    # 后一条的轮询至少又转了两圈、看见了拨过的钟(或者它已经放弃了 —— 那下一行断言说清楚)
    _until(lambda: clock.reads(second) >= seen + 4 or not second.is_alive())
    assert second.is_alive() and "error" not in second_box, f"排在同一会话前一条后面的时间被算成了排队:{second_box}"
    # 执行器这时也领不走它(同一会话串行)
    assert worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"] is None

    worker.patch("/api/browser/worker/report", json={
        "action_id": claimed["id"], "status": "done", "lease_token": claimed["lease_token"],
    })
    next_one = _claim(worker)
    first.join(timeout=30)
    assert not first.is_alive() and "error" not in first_box, first_box
    assert next_one["action"] == "extract"
    worker.patch("/api/browser/worker/report", json={
        "action_id": next_one["id"], "status": "done", "result": {"value": "标题"}, "lease_token": next_one["lease_token"],
    })
    second.join(timeout=30)
    assert second_box.get("value") == {"value": "标题"}, second_box


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
