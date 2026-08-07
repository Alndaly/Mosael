from __future__ import annotations

import os
import tempfile
import contextlib
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.agent.host import wait_for_idle_turns
from app.domain.agent.autopilot import wait_for_idle_autopilot
from app.core.config import settings
from app.core.db import Base, engine, init_db
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key, issue_worker_key
from app.main import app

PASSWORD = "pass1234"


def _assert_disposable_data_dir() -> None:
    """Refuse to drop_all unless the DB lives in a throwaway temp dir.

    conftest.py points OPEN_STUDIO_DATA_DIR at a mkdtemp() before anything imports settings — but
    conftest only loads under pytest. Calling these helpers directly (e.g. `python -c "from
    tests.util import fresh_client"`) would otherwise resolve to the REAL ~/.open-studio and
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
    # 自动放行的执行线程同理:它在请求返回之后才批准并执行,底下就要 drop_all 了。
    wait_for_idle_autopilot()
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


def add_provider(db, *, model: str = "", capability_ids=None, owner_username: str = "", make_default: bool = True, **fields):
    """建一条连接、它的模型行,以及一把钥匙。

    档案上不再有 default_model —— 模型是独立实体。直接构造 ProviderProfile 而不建模型行的
    话,任何按能力解析模型的地方都会拿到空串(这正是重构时十几条测试红掉的原因,而它们红得
    有道理:少了模型行,那条连接确实没有可用模型)。

    钥匙同理:`api_key` / `oauth_credential` 不再是连接上的列(见 domain/provider_credentials),
    传进来的落成**某个人**的钥匙 —— 默认是最早那个账号。要指名给谁就传 owner_username。
    没有"共享钥匙"这回事:每个人配自己的。
    """
    from app.db.models import Workspace, ProviderProfile, User
    from app.domain import provider_credentials, provider_models

    api_key = fields.pop("api_key", None)
    oauth_credential = fields.pop("oauth_credential", None)
    secrets = fields.pop("secrets", None)
    model_catalog = fields.pop("model_catalog", None)

    profile = ProviderProfile(**fields)
    db.add(profile)
    db.flush()
    if model:
        row = provider_models.upsert(db, profile, model, source="manual", capability_ids=capability_ids)
        # 顺手设成**钥匙主人自己的**默认。取默认模型没有任何兜底(既没有"随便挑一个",也没有
        # "部署默认"——见 provider_models.resolve_default),所以"配好了一条连接"在测试里必须包含
        # "某个人把它设成了自己的默认"。真实使用里也是同一步:谁配的钥匙,谁顺手选一下。
        # 已经有默认的能力不覆盖;要测「没有默认时怎么办」传 make_default=False。
        from app.domain import provider_defaults

        if make_default:
            query = db.query(User)
            owner = (
                query.filter(User.username == owner_username).one()
                if owner_username
                else query.order_by(User.created_at).first()
            )
            for capability in provider_models.effective_capabilities(row) if owner is not None else ():
                if provider_defaults.get_row(db, capability, owner.id) is None:
                    provider_defaults.set_default(db, capability, row, owner_user_id=owner.id)
    if api_key is not None or oauth_credential is not None or secrets or model_catalog is not None:
        query = db.query(User)
        owner = (
            query.filter(User.username == owner_username).one()
            if owner_username
            else query.order_by(User.created_at).first()
        )
        if owner is not None:
            credential = provider_credentials.upsert(
                db, profile.id, owner.id, api_key=api_key or "", secrets=secrets or None
            )
            credential.oauth_credential = oauth_credential
            credential.model_catalog = model_catalog
    db.flush()
    return profile


@contextlib.contextmanager
def acting_as(db, user_id: str | None = None):
    """以某个人的身份跑一个工作流节点。

    引擎跑工作流时,节点通过 `jobs.current_actor` 拿到"这活儿替谁干"(父 job 上记着)。测试直接
    调节点时没有父 job —— 于是取供应商会拿不到任何钥匙。这里补上引擎本来会建立的那层上下文,
    而不是让领域代码去容忍"没有人"(那正是钥匙归人要消灭的状态)。

    用**调用方自己的会话**建这个 job:另开一个会话会和调用方尚未提交的行打架。
    """
    from app.db.models import User, Workspace
    from app.domain import jobs as jobs_domain

    actor = user_id or db.query(User).order_by(User.created_at).first().id
    job = jobs_domain.create_job(
        db,
        workspace_id=db.query(Workspace).first().id,
        kind="workflow",
        payload={},
        created_by=actor,
    )
    db.flush()
    token = jobs_domain._current_parent_job.set(job.id)
    try:
        yield actor
    finally:
        jobs_domain._current_parent_job.reset(token)
