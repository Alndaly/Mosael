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

from app.core.db import SessionLocal
from app.db.models import BrowserAction, now
from app.domain import browser
from tests.util import fresh_client, worker_client


def _session() -> str:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        return browser.open_session(db, workspace_id=ws, actor=None).id


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
    time.sleep(0.5)
    claimed = worker_client().post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
    assert claimed["action"] == "evaluate"
    # 执行器从此不再心跳、不再回报。租约到点(这里直接拨到过去,省掉 60 秒)。
    with SessionLocal() as db:
        db.get(BrowserAction, claimed["id"]).lease_expires_at = now() - timedelta(seconds=1)
        db.commit()
    started = time.monotonic()
    thread.join(timeout=10)
    assert not thread.is_alive(), "租约早就到了,调用方还在等执行上限"
    assert time.monotonic() - started < 5
    assert box["error"].key == "browserErr_executorLost", box
    with SessionLocal() as db:
        act = db.get(BrowserAction, claimed["id"])
        assert (act.status, act.error) == ("failed", "browserErr_executorLost")


def test_租约没到就照常等_执行器回报了就是回报的结果() -> None:
    sid = _session()
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(value=browser.run_action(sid, "extract", {"selector": "h1"})))
    thread.start()
    time.sleep(0.5)
    worker = worker_client()
    claimed = worker.post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
    time.sleep(0.6)  # 轮询走了好几拍,租约还在:不该被判失联
    worker.patch("/api/browser/worker/report", json={
        "action_id": claimed["id"], "status": "done", "result": {"value": "标题"}, "lease_token": claimed["lease_token"],
    })
    thread.join(timeout=5)
    assert box.get("value") == {"value": "标题"}
