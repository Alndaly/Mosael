"""删掉发过的成片,发布记录和平台上的作品 ID 留着;还在发的素材删不掉;删发布账号时没发完的任务撤单(MED-3)。

此前 `publish_tasks.asset_id` 是 `ON DELETE CASCADE`:用户删一份发过的成片腾空间,发布历史跟着没了,作品 ID(之后按它查
播放、评论)也没了。还在发的素材也照删 —— 发布器读到一半的文件没了。删发布账号时任务行随外键级联删掉,背后任务总线上的
job 却一直停在「运行中」。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key
from app.db.models import Asset, Job, PublishTask, User
from tests.test_publish_worker import WORKER, setup_browser_task
from tests.util import fresh_client

POST = {"post_id": "7420000000000000001", "url": "https://www.douyin.com/video/7420000000000000001", "ids": {}}


def _client():
    client = fresh_client()
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
    return client


def _claim(client, task_id: str) -> None:
    claimed = client.post("/api/publish/worker/claim", json={"exclude_accounts": [], "worker": WORKER}).json()["task"]
    assert claimed["id"] == task_id


def _report(client, task_id: str, **report) -> None:
    response = client.patch("/api/publish/worker/report", json={"task_id": task_id, **report})
    assert response.status_code == 200, response.text


def _task_out(client, ws_id: str, task_id: str) -> dict | None:
    return next((t for t in client.get(f"/api/publish/tasks?workspace_id={ws_id}").json() if t["id"] == task_id), None)


def test_删掉发过的成片_发布记录和作品ID都留着_还说得出发的是哪份() -> None:
    client = _client()
    ws, _, task = setup_browser_task(client)
    _claim(client, task["id"])
    _report(client, task["id"], status="success", post=POST)

    deleted = client.delete(f"/api/assets/{task['asset_id']}")

    assert deleted.status_code == 204, deleted.text
    kept = _task_out(client, ws["id"], task["id"])
    assert kept is not None, "删素材把发布记录连带删了"
    assert kept["asset_id"] is None
    assert kept["asset_name"] == "成片A"
    assert kept["status"] == "success"
    assert kept["post"]["post_id"] == POST["post_id"]


@pytest.mark.parametrize("claimed", [False, True], ids=["排着", "在发"])
def test_还在发的素材删不掉_说清在发到哪个账号(claimed: bool) -> None:
    client = _client()
    _, _, task = setup_browser_task(client)
    if claimed:
        _claim(client, task["id"])

    refused = client.delete(f"/api/assets/{task['asset_id']}")

    assert refused.status_code == 409, refused.text
    assert "主号" in refused.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Asset, task["asset_id"]) is not None


def test_发完了_失败的也算_素材就能删() -> None:
    client = _client()
    _, _, task = setup_browser_task(client)
    _claim(client, task["id"])
    _report(client, task["id"], status="failed", error_message="平台拒了")

    assert client.delete(f"/api/assets/{task['asset_id']}").status_code == 204


def test_智能体删素材_素材还在发就不开卡() -> None:
    """卡是授权界面:批准了一张执行时才报错的卡,等于让用户白批一次。开卡时就说。"""
    from app.domain.agent.confirmations import request_confirmation
    from app.domain.agent.errors import ConfirmationError

    client = _client()
    ws, _, task = setup_browser_task(client)
    with SessionLocal() as db:
        user_id = db.query(User).filter(User.username == "tester").one().id
        with pytest.raises(ConfirmationError) as refused:
            request_confirmation(
                db, workspace_id=ws["id"], tool="delete_assets", payload={"asset_ids": [task["asset_id"]]}, actor_id=user_id
            )
    assert refused.value.key == "assetErr_beingPublished"


def test_删发布账号_没发完的任务背后的job落已取消_发布器查不到任务就停() -> None:
    client = _client()
    ws, account, task = setup_browser_task(client)
    _claim(client, task["id"])
    with SessionLocal() as db:
        job_id = db.get(PublishTask, task["id"]).job_id

    assert client.delete(f"/api/publish/accounts/{account['id']}").status_code == 204

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert (job.status, job.error_key) == ("cancelled", ""), "任务行没了,job 还停在运行中"
    # 发布器每半秒查一次任务状态,查不到就中止(electron/publish/publishWorker.ts 的 checkpoint)。
    assert client.get(f"/api/publish/worker/task/{task['id']}").status_code == 404


def test_删发布账号_已经发完的任务的job不动() -> None:
    client = _client()
    _, account, task = setup_browser_task(client)
    _claim(client, task["id"])
    _report(client, task["id"], status="success", post=POST)
    with SessionLocal() as db:
        job_id = db.get(PublishTask, task["id"]).job_id

    assert client.delete(f"/api/publish/accounts/{account['id']}").status_code == 204

    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "succeeded"


#: 升级之前的 publish_tasks(维护者库上读出来的原样):asset_id 不可空、ON DELETE CASCADE,没有 asset_name。
OLD_PUBLISH_TASKS = """
CREATE TABLE publish_tasks (
    id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    asset_id VARCHAR(64) NOT NULL,
    title VARCHAR(300) NOT NULL,
    description TEXT NOT NULL,
    tags JSON NOT NULL,
    short_title VARCHAR(80) NOT NULL,
    status VARCHAR(40) NOT NULL,
    error_message TEXT,
    screenshot_path TEXT,
    job_id VARCHAR(64),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL, options JSON NOT NULL DEFAULT '{}', claimed_by VARCHAR(64) NOT NULL DEFAULT '', post JSON NOT NULL DEFAULT '{}',
    PRIMARY KEY (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES publish_accounts (id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL
)
"""
