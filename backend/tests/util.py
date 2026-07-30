from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.agent.host import wait_for_idle_turns
from app.core.config import settings
from app.core.db import Base, engine, init_db
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key, issue_worker_key
from app.main import app

PASSWORD = "pass1234"


def _assert_disposable_data_dir() -> None:
    """Refuse to drop_all unless the DB lives in a throwaway temp dir.

    conftest.py points OPEN_STUDIO_DATA_DIR at a mkdtemp() before anything imports settings — but
    conftest only loads under pytest. Calling these helpers directly (e.g. `python -c "from
    tests.util import fresh_client"`) would otherwise resolve to the REAL ~/.mibu-cut and
    drop every table in the user's live database. Fail loudly instead of silently wiping it.
    """
    data_dir = Path(settings.data_dir).resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    in_tmp = data_dir == tmp_root or tmp_root in data_dir.parents
    if not os.environ.get("OPEN_STUDIO_DATA_DIR") or not in_tmp:
        raise RuntimeError(
            f"refusing to drop_all: data_dir={data_dir} is not a temp dir. "
            "Run tests through pytest (conftest.py sets OPEN_STUDIO_DATA_DIR); never call "
            "fresh_client() from an ad-hoc `python -c` against the real database."
        )


def fresh_client(username: str = "tester") -> TestClient:
    """Drop/recreate the isolated test DB and return a logged-in client.

    Also mints the publish-worker key. TestClient(app) does not run the lifespan (only the
    context-manager form does), so without this the worker channel has no key issued and every
    worker route answers 401 — correct behaviour for an unstarted backend, but not what a test
    exercising those routes means to assert.
    """
    _assert_disposable_data_dir()
    # 先等在飞的 agent turn 跑完,再动 schema。turn 是 daemon 线程,请求返回后还在写库——
    # 生产里无所谓(进程比 turn 活得久),但这里下一步就要 drop_all。不等的话上一个测试的 turn
    # 会写进正在重建的库,表现为:turn 内部 FOREIGN KEY 失败、迁移时 duplicate column
    # (inspect 读到的 schema 与实际不符)、或别的测试的消息串进本测试的断言里。
    # 这三种症状都是概率性的,取决于测试顺序与机器速度——正是最难查的那类失败。
    wait_for_idle_turns()
    Base.metadata.drop_all(bind=engine)
    init_db()
    issue_worker_key()
    client = TestClient(app)
    login_as(client, username)
    return client


def worker_client() -> TestClient:
    """A client authenticated as the local publish worker rather than as a user."""
    client = TestClient(app)
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or issue_worker_key()
    return client


def login_as(client: TestClient, username: str) -> dict:
    res = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    if res.status_code == 409:
        res = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    payload = res.json()
    client.headers["Authorization"] = f"Bearer {payload['token']}"
    return payload["user"]


def second_client(username: str = "other") -> TestClient:
    """Another user against the same DB (no reset)."""
    client = TestClient(app)
    login_as(client, username)
    return client


def make_video_asset(client, workspace_id: str) -> dict:
    """入库一个最小可发布素材(直接写文件,不跑 ffmpeg)。"""
    media = settings.media_dir / "test-publish"
    media.mkdir(parents=True, exist_ok=True)
    source = media / "clip.mp4"
    source.write_bytes(b"fake-video-bytes")
    created = client.post(
        "/api/assets",
        json={
            "workspace_id": workspace_id,
            "kind": "video",
            "name": "成片A",
            "file_key": "media/test-publish/clip.mp4",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def wait_status(client, job_id: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            return status
        time.sleep(0.15)
    return status
