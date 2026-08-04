"""止血:注册转邀请制。

这是 ADR 0008 的第 0 步。它不解决任何架构问题 —— 归属、角色、隔离执行器都还在后面 ——
但它单独就把下面这条**跑出来过**的链掐断在第一环和最后一环:

    POST /api/auth/register                 200   ← 注册完全开放
    PUT  /api/settings/network              403
    POST /api/workspaces                    200   ← 他在自己建的工作区里是 owner
    PUT  /api/settings/network              200   ← 通了
    POST /api/workflows  {含 code 节点}      200   ← 服务端执行任意 Python

**注册转邀请制**挡住第一环:引导完 —— 也就是库里已经有账号了 —— 之后,陌生人进不来。
开关留在配置里而不是数据库里:它是**部署的属性**,不是某个人的属性。

最后一环(服务端执行任意 Python)当时用一个默认关的开关止血。第 5 步之后那个开关**撤掉了**:
代码跑在内核强制的隔离里,隔离不可用时拒绝执行 —— 判据从"开关开没开"换成"是否真的隔离得住"
(见 domain/sandbox 与 tests/test_sandbox.py)。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.util import fresh_client

CODE_GRAPH = {
    "nodes": [
        {"id": "start_1", "type": "start", "config": {}},
        {"id": "code_1", "type": "code", "config": {"code": "output = 1"}},
    ],
    "edges": [],
}


def _register(username: str = "stranger") -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": username, "password": "whatever123"})
    return client


# ---------------- 注册 ----------------


def _set_open(value: bool) -> None:
    """开关搬进库了(见 db.models.DeploymentConfig)—— 测试也走同一处,不再改 settings。"""
    from app.core.db import SessionLocal
    from app.domain import deployment

    with SessionLocal() as db:
        deployment.set_open_registration(db, value)
        db.commit()


def test_the_first_account_can_always_register() -> None:
    """引导必须走得通 —— 空库上没有人可以发邀请。"""
    fresh_client()  # 建库并占掉第一个账号
    # fresh_client 自己就是那第一次注册;能走到这里就说明它成功了。


def test_a_stranger_cannot_register_once_someone_is_there(monkeypatch) -> None:
    """引导之后,注册不再是自助的。"""
    fresh_client()
    _set_open(False)  # 必须在 fresh_client 之后 —— 它会重建库,先写就没了
    stranger = TestClient(app)

    denied = stranger.post("/api/auth/register", json={"username": "stranger", "password": "whatever123"})

    assert denied.status_code == 403, denied.text
    assert "邀请" in denied.json()["detail"], denied.json()


def test_an_open_deployment_can_opt_back_in(monkeypatch) -> None:
    """有的部署确实想开放注册(比如内网 demo)—— 让他们显式说。"""
    fresh_client()
    _set_open(False)  # 这一条守的是**邀请制**下的行为;默认是开放的
    _set_open(True)
    stranger = TestClient(app)

    allowed = stranger.post("/api/auth/register", json={"username": "stranger", "password": "whatever123"})

    assert allowed.status_code == 200, allowed.text


def test_an_invited_person_can_still_get_in(monkeypatch) -> None:
    """关掉前门必须同时开侧门。

    老的工作区邀请是「按用户名邀请一个**已注册**账号」—— 而账号从哪来正是被关掉的那条路。
    所以需要两种邀请:一种进这个**部署**(拿到账号),一种进某个**工作区**。这正是 ADR 0008
    那条两层划分在实现里第一次显形的地方。
    """
    owner = fresh_client()
    _set_open(False)  # 必须在 fresh_client 之后 —— 它会重建库
    invite = owner.post("/api/auth/invites", json={"note": "给 mate"})
    assert invite.status_code == 200, invite.text
    code = invite.json()["code"]

    mate = TestClient(app)
    joined = mate.post(
        "/api/auth/register",
        json={"username": "mate", "password": "whatever123", "invite_code": code},
    )
    assert joined.status_code == 200, joined.text

    # 用过就不能再用第二次 —— 一个码换一个账号。
    third = TestClient(app)
    reused = third.post(
        "/api/auth/register",
        json={"username": "another", "password": "whatever123", "invite_code": code},
    )
    assert reused.status_code == 403, reused.text


def test_a_workspace_invitation_still_works() -> None:
    """有了账号之后,进工作区的流程一点没变。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    code = owner.post("/api/auth/invites", json={}).json()["code"]
    mate = TestClient(app)
    mate.post("/api/auth/register", json={"username": "mate", "password": "whatever123", "invite_code": code})

    invited = owner.post(
        f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"}
    )
    assert invited.status_code == 200, invited.text
