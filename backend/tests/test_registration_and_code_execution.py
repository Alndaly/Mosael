"""止血:注册转邀请制,服务端执行代码默认关。

这是 ADR 0008 的第 0 步。它不解决任何架构问题 —— 归属、角色、隔离执行器都还在后面 ——
但它单独就把下面这条**跑出来过**的链掐断在第一环和最后一环:

    POST /api/auth/register                 200   ← 注册完全开放
    PUT  /api/settings/network              403
    POST /api/workspaces                    200   ← 他在自己建的工作区里是 owner
    PUT  /api/settings/network              200   ← 通了
    POST /api/workflows  {含 code 节点}      200   ← 服务端执行任意 Python

两件事各挡一头:

  - **注册转邀请制**:引导完 —— 也就是库里已经有账号了 —— 之后,陌生人进不来。
  - **服务端执行代码默认关**:这是**止血,不是设计**。真正的解法是把执行器搬进隔离环境
    (ADR 0008 D2,参照 dify-sandbox),那之后这个开关就该撤掉。在那之前,一个多租户产品
    不该默认允许任何人在服务端跑不受限的 Python。

两个开关都留在配置里而不是数据库里:它们是**部署的属性**,不是某个人的属性。
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


def test_the_first_account_can_always_register() -> None:
    """引导必须走得通 —— 空库上没有人可以发邀请。"""
    fresh_client()  # 建库并占掉第一个账号
    # fresh_client 自己就是那第一次注册;能走到这里就说明它成功了。


def test_a_stranger_cannot_register_once_someone_is_there(monkeypatch) -> None:
    """引导之后,注册不再是自助的。"""
    monkeypatch.setattr(settings, "open_registration", False)
    fresh_client()
    stranger = TestClient(app)

    denied = stranger.post("/api/auth/register", json={"username": "stranger", "password": "whatever123"})

    assert denied.status_code == 403, denied.text
    assert "邀请" in denied.json()["detail"], denied.json()


def test_an_open_deployment_can_opt_back_in(monkeypatch) -> None:
    """有的部署确实想开放注册(比如内网 demo)—— 让他们显式说。"""
    fresh_client()
    monkeypatch.setattr(settings, "open_registration", True)
    stranger = TestClient(app)

    allowed = stranger.post("/api/auth/register", json={"username": "stranger", "password": "whatever123"})

    assert allowed.status_code == 200, allowed.text


def test_an_invited_person_can_still_get_in(monkeypatch) -> None:
    """关掉前门必须同时开侧门。

    老的工作区邀请是「按用户名邀请一个**已注册**账号」—— 而账号从哪来正是被关掉的那条路。
    所以需要两种邀请:一种进这个**部署**(拿到账号),一种进某个**工作区**。这正是 ADR 0008
    那条两层划分在实现里第一次显形的地方。
    """
    monkeypatch.setattr(settings, "open_registration", False)
    owner = fresh_client()
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


# ---------------- 服务端执行代码 ----------------


def test_code_nodes_are_refused_when_execution_is_off(monkeypatch) -> None:
    """默认关:连**存**都不让存 —— 存下来就会被定时器点着,而定时执行没有主体。"""
    monkeypatch.setattr(settings, "server_side_code_execution", False)
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()

    refused = owner.post(
        "/api/workflows", json={"workspace_id": workspace["id"], "name": "载荷", "graph": CODE_GRAPH}
    )

    assert refused.status_code == 403, refused.text
    detail = refused.json()["detail"]
    assert "代码" in detail and ("关闭" in detail or "未启用" in detail), detail


def test_run_code_is_refused_when_execution_is_off(monkeypatch) -> None:
    """工作流节点与智能体工具是同一段实现,开关也必须是同一个。"""
    monkeypatch.setattr(settings, "server_side_code_execution", False)
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()

    card = owner.post(
        "/api/confirmations",
        json={"workspace_id": workspace["id"], "tool": "run_code", "payload": {"code": "output = 1"}},
    )

    assert card.status_code == 422, card.text
    assert "代码" in card.json()["detail"], card.json()


def test_turning_it_on_restores_the_old_behaviour(monkeypatch) -> None:
    """开了之后照旧 —— 开关只决定这项能力在不在,不改变它原有的权限判据。"""
    monkeypatch.setattr(settings, "server_side_code_execution", True)
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()

    saved = owner.post(
        "/api/workflows", json={"workspace_id": workspace["id"], "name": "载荷", "graph": CODE_GRAPH}
    )

    assert saved.status_code == 200, saved.text


def test_ordinary_workflows_are_untouched(monkeypatch) -> None:
    """开关只针对 code 节点,不能顺手把普通工作流也挡了。"""
    monkeypatch.setattr(settings, "server_side_code_execution", False)
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()

    saved = owner.post(
        "/api/workflows",
        json={
            "workspace_id": workspace["id"],
            "name": "普通",
            "graph": {"nodes": [{"id": "start_1", "type": "start", "config": {}}], "edges": []},
        },
    )

    assert saved.status_code == 200, saved.text


def test_the_default_is_off() -> None:
    """默认值本身就是这一步的全部意义 —— 别让它被下一次改动悄悄翻过去。

    断言的是**声明的默认值**,不是 `settings` 上的当前值:测试环境把两个开关都打开了
    (见 conftest 的说明),读当前值只会读到测试环境的选择,什么也保护不了。
    """
    from app.core.config import Settings

    assert Settings.model_fields["server_side_code_execution"].default is False
    assert Settings.model_fields["open_registration"].default is False


@pytest.mark.parametrize("path", ["/api/workflows", "/api/workflows/import"])
def test_every_persist_path_honours_the_switch(monkeypatch, path: str) -> None:
    """落库入口不止一条 —— 开关要挡住全部,而不是最显眼的那条。"""
    monkeypatch.setattr(settings, "server_side_code_execution", False)
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()

    if path.endswith("import"):
        body = {
            "workspace_id": workspace["id"],
            "data": {"format": "openstudio-workflow", "version": 1, "name": "载荷", "graph": CODE_GRAPH},
        }
    else:
        body = {"workspace_id": workspace["id"], "name": "载荷", "graph": CODE_GRAPH}

    assert owner.post(path, json=body).status_code == 403
