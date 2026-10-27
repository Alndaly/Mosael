"""发布成功之后,要记下发出去的**那一条作品**:平台上的作品 ID、链接、发布时间。

此前任务只有一个状态 `success`。之后想查这条作品的播放、评论(TikHub 之类都按作品 ID 取),
只能拿标题去平台上猜是哪一条。执行器在点发布时从平台接口的返回里读到 ID(electron 那一侧),
这里管的是:收下、收窄、存住,并交给三个消费方 —— 任务列表、工作流的下游节点、智能体。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key
from app.db.models import Job, PublishTask
from tests.test_publish_worker import WORKER, setup_browser_task
from tests.util import fresh_client

POST = {
    "post_id": "7420000000000000001",
    "url": "https://www.douyin.com/video/7420000000000000001",
    "ids": {"item_id": "7420000000000000001"},
}


def _client():
    client = fresh_client()
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
    return client


def _run(client, task_id: str, **report) -> None:
    claimed = client.post("/api/publish/worker/claim", json={"exclude_accounts": [], "worker": WORKER}).json()["task"]
    assert claimed["id"] == task_id
    response = client.patch("/api/publish/worker/report", json={"task_id": task_id, **report})
    assert response.status_code == 200, response.text


def _task_out(client, ws_id: str, task_id: str) -> dict:
    return next(t for t in client.get(f"/api/publish/tasks?workspace_id={ws_id}").json() if t["id"] == task_id)


def test_发成功时记下作品ID和链接_任务列表里看得到() -> None:
    client = _client()
    ws, _, task = setup_browser_task(client)
    _run(client, task["id"], status="success", post=POST)

    post = _task_out(client, ws["id"], task["id"])["post"]
    assert post["platform"] == "douyin"
    assert (post["post_id"], post["url"], post["ids"]) == (POST["post_id"], POST["url"], POST["ids"])
    assert post["published_at"].endswith("Z")


def test_作品信息跟着进job结果_工作流下游取得到() -> None:
    client = _client()
    _, _, task = setup_browser_task(client)
    _run(client, task["id"], status="success", post=POST)

    with SessionLocal() as db:
        job = db.get(Job, db.get(PublishTask, task["id"]).job_id)
        assert job.result["post"]["post_id"] == POST["post_id"]


def test_没读到ID也记下平台和时间_但不编一个ID() -> None:
    """平台改了接口、执行器没读到 —— 空的一眼看得出没抓到,编的会被当真去查。"""
    client = _client()
    ws, _, task = setup_browser_task(client)
    _run(client, task["id"], status="success")

    post = _task_out(client, ws["id"], task["id"])["post"]
    assert post["post_id"] == "" and post["url"] == "" and post["ids"] == {}
    assert post["platform"] == "douyin" and post["published_at"]


def test_页面里来的东西逐项收窄() -> None:
    """报上来的内容出自一个浏览器页面:链接只认 http(s),标识只收短字符串,键名要像标识符。"""
    client = _client()
    ws, _, task = setup_browser_task(client)
    _run(client, task["id"], status="success", post={
        "post_id": "x" * 500,
        "url": "javascript:alert(1)",
        "ids": {"aweme_id": 7420000000000000001, "bad key": "1", "nested": {"a": 1}, "flag": True},
    })

    post = _task_out(client, ws["id"], task["id"])["post"]
    assert len(post["post_id"]) == 128
    assert post["url"] == ""
    assert post["ids"] == {"aweme_id": "7420000000000000001"}


def test_没发成的任务没有作品() -> None:
    client = _client()
    ws, _, task = setup_browser_task(client)
    _run(client, task["id"], status="failed", error_message="平台拒了", post=POST)

    assert _task_out(client, ws["id"], task["id"])["post"] is None


def test_工作流发布节点把作品ID和链接交给下游() -> None:
    from app.domain.workflows import NODE_TYPES

    spec = NODE_TYPES["publish"]
    assert {"post_id", "post_url"} <= set(spec["outputs"])
