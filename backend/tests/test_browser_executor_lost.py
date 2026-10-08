"""执行器在动作做到一半时没了(崩溃、被杀、断网):多久知道、报的是什么。

实测(2026-10,真实 Electron 执行器,杀掉执行器进程):一条领走了的动作要等满它的执行上限(脚本预算 90 秒 + 15)
才失败,报的是「执行超时:执行器领走之后一直没做完」—— 而它的租约 60 秒就到了。租约到点的判定只在执行器认领 /
心跳时做(expire_action_leases),执行器没了,就没人来判。接着失败现场的截图又排了一个完整的排队上限(60 秒)
才放弃:一次失败拖成近三分钟。执行器一直不在时同理:60 秒排队超时之后,截图再排 60 秒。
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserAction, now
from app.domain import browser
from app.domain.workflows.executors import browser as browser_nodes
from tests.util import fresh_client, until, worker_client


def _session() -> str:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        return browser.open_session(db, workspace_id=ws, actor=None).id


def _claim(worker) -> dict:
    """领到为止:调用方的线程什么时候把动作排进去,看机器忙不忙。此前是睡 0.5 秒、只领一次。"""
    box: dict = {}

    def claimed() -> bool:
        box["action"] = worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
        return bool(box["action"])

    assert until(claimed, interval=0.05), "没领到动作"
    return box["action"]


def test_领走之后执行器没了_租约一到就报执行器失联_不等满执行上限() -> None:
    sid = _session()
    box: dict = {}

    def go() -> None:
        try:
            box["value"] = browser.run_action(sid, "evaluate", {"expression": "1"}, timeout=60)
        except browser.BrowserDomainError as exc:
            box["error"] = exc

    thread = threading.Thread(target=go)
    thread.start()
    claimed = _claim(worker_client())
    assert claimed["action"] == "evaluate"
    # 执行器从此不再心跳、不再回报。租约到点(这里直接拨到过去,省掉 60 秒)。
    with SessionLocal() as db:
        db.get(BrowserAction, claimed["id"]).lease_expires_at = now() - timedelta(seconds=1)
        db.commit()
    # 不修的话要等满执行上限(60 秒):线画在它的一半。
    thread.join(timeout=30)
    assert not thread.is_alive(), "租约早就到了,调用方还在等执行上限"
    assert box["error"].key == "browserErr_executorLost", box
    with SessionLocal() as db:
        act = db.get(BrowserAction, claimed["id"])
        assert (act.status, act.error) == ("failed", "browserErr_executorLost")


def test_租约没到就照常等_执行器回报了就是回报的结果(monkeypatch) -> None:
    #: 数调用方在「已被领走」之后看了几拍租约 —— 看过好几拍、租约还在,才说明「没到点就不判失联」。
    #: 此前是睡 0.6 秒,机器一忙这段时间里一拍都没看,断言照样成立。
    looked_while_running: list[str] = []
    real_lease_expired = browser._lease_expired

    def lease_expired(act):
        if act.status == "running":
            looked_while_running.append(act.id)
        return real_lease_expired(act)

    monkeypatch.setattr(browser, "_lease_expired", lease_expired)
    sid = _session()
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(value=browser.run_action(sid, "extract", {"selector": "h1"})))
    thread.start()
    worker = worker_client()
    claimed = _claim(worker)
    assert until(lambda: len(looked_while_running) >= 3), "领走之后调用方一直没看租约"
    worker.patch("/api/browser/worker/report", json={
        "action_id": claimed["id"], "status": "done", "result": {"value": "标题"}, "lease_token": claimed["lease_token"],
    })
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert box.get("value") == {"value": "标题"}


@pytest.fixture
def no_executor(monkeypatch):
    monkeypatch.setattr(browser, "_executor_contact", None)
    #: 排队上限给得很长:截图要是还按它等,这条测试就要等这么久
    monkeypatch.setattr(browser, "QUEUE_TIMEOUT_SECONDS", 30.0)
    monkeypatch.setattr(browser_nodes, "_SHOT_TIMEOUT_SECONDS", 1.0)


def test_失败现场的截图_执行器不在时按它自己的短上限放弃_不再排满一个排队上限(no_executor) -> None:
    sid = _session()
    started = time.monotonic()
    scene = browser_nodes._failure_scene(sid, "click", {"selector": "#go"})
    elapsed = time.monotonic() - started
    # 按排队上限等就是 30 秒:线画在它的一半(截图自己的上限是 1 秒)。
    assert elapsed < 15, f"截图在排队上限上等了 {elapsed:.1f} 秒"
    assert scene == {"action": "click", "selector": "#go"}, "拿不到图就只有动作和选择器"
