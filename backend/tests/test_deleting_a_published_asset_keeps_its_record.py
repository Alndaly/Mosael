"""删掉发过的成片,发布记录和平台上的作品 ID 留着;还在发的素材删不掉;删发布账号时没发完的任务撤单(MED-3)。

此前 `publish_tasks.asset_id` 是 `ON DELETE CASCADE`:用户删一份发过的成片腾空间,发布历史跟着没了,作品 ID(之后按它查
播放、评论)也没了。还在发的素材也照删 —— 发布器读到一半的文件没了。删发布账号时任务行随外键级联删掉,背后任务总线上的
job 却一直停在「运行中」。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key
from app.db.models import Asset, Job, PublishTask, User
from app.domain.jobs import CANCELLED_ERROR_KEY
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
        # 任务总线上「取消」是 failed + jobErr_cancelled(见 jobs._cancel_job_row)。
        assert (job.status, job.error_key) == ("failed", CANCELLED_ERROR_KEY), "任务行没了,job 还停在运行中"
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


def test_老库的发布记录升级后_删素材不再连带删掉_名字补上_再跑一次什么都不做() -> None:
    from app.db.migrations import _migrate_publish_records_outlive_their_asset

    client = _client()
    ws, _, task = setup_browser_task(client)
    _claim(client, task["id"])
    _report(client, task["id"], status="success", post=POST)
    columns = "id, workspace_id, account_id, asset_id, title, description, tags, short_title, status, error_message, " \
        "screenshot_path, job_id, created_at, updated_at, options, claimed_by, post"
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE publish_tasks RENAME TO publish_tasks_new"))
        conn.execute(text(OLD_PUBLISH_TASKS))
        conn.execute(text(f"INSERT INTO publish_tasks ({columns}) SELECT {columns} FROM publish_tasks_new"))
        conn.execute(text("DROP TABLE publish_tasks_new"))
    engine.dispose()

    _migrate_publish_records_outlive_their_asset()
    _migrate_publish_records_outlive_their_asset()  # 第二次:已经是新形状,只按名字补一遍(没有要补的)

    with engine.connect() as conn:
        asset_fk = next(row for row in conn.execute(text("PRAGMA foreign_key_list(publish_tasks)")) if row[3] == "asset_id")
        asset_column = next(row for row in conn.execute(text("PRAGMA table_info(publish_tasks)")) if row[1] == "asset_id")
    assert asset_fk[6] == "SET NULL"
    assert asset_column[3] == 0, "asset_id 还是不可空"
    kept = _task_out(client, ws["id"], task["id"])
    assert kept["asset_name"] == "成片A"
    assert kept["post"]["post_id"] == POST["post_id"]

    assert client.delete(f"/api/assets/{task['asset_id']}").status_code == 204
    assert _task_out(client, ws["id"], task["id"]) is not None, "升级之后删素材,发布记录还是连带删了"


def test_老库里没有发布表_迁移什么都不做() -> None:
    from app.db.migrations import _migrate_publish_records_outlive_their_asset

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE publish_tasks"))
    engine.dispose()

    _migrate_publish_records_outlive_their_asset()

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
    assert "publish_tasks" not in tables
