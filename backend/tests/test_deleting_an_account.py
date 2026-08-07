"""删掉一个账号,以及跟着他走的那些东西。

**此前没有这条路。** 管理页能授予、能收回部署管理员,却删不掉一个账号 —— 于是"清理掉那个测试
账号"只能去手改数据库。而手改必然漏:`agent_sessions.owner_user_id` 这类列**没有外键**(有意的,
见 db.models),删掉 users 那一行之后它们变成指向不存在的人的孤儿,谁都不会报错。

两条边界,都是"别把别人的东西一起删掉":

  - 他独占的工作区跟着他走(里面只有他自己的东西);
  - 还有别人在的工作区**不跟着走**,拒绝删除并说清是哪几个 —— 那里面有同事的素材、时间线、
    对话。宁可让管理员先去转让,也不要一次点击毁掉别人的工作。

另外和「不能收回最后一个部署管理员」同一条:不能删掉最后一个部署管理员,否则这台部署没人管了。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import AgentSession, AuthSession, User, Workspace, WorkspaceMember
from tests.util import fresh_client, second_client


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _counts(user_id: str) -> dict[str, int]:
    with SessionLocal() as db:
        return {
            "users": db.query(User).filter(User.id == user_id).count(),
            "sessions": db.query(AuthSession).filter(AuthSession.user_id == user_id).count(),
            "memberships": db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).count(),
            "agent_sessions": db.query(AgentSession).filter(AgentSession.owner_user_id == user_id).count(),
        }


def test_an_admin_can_delete_an_account() -> None:
    admin = fresh_client()
    mate = second_client("mate")
    workspace = mate.post("/api/workspaces", json={"name": "他自己的"}).json()
    mate.post("/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "他的对话"})
    mate_id = _user_id("mate")
    assert _counts(mate_id)["agent_sessions"] == 1

    removed = admin.delete(f"/api/admin/users/{mate_id}")

    assert removed.status_code == 204, removed.text
    assert _counts(mate_id) == {"users": 0, "sessions": 0, "memberships": 0, "agent_sessions": 0}


def test_his_own_workspace_goes_with_him() -> None:
    """里面只有他自己的东西 —— 留一个没有成员的工作区,只是留一堆没人看得见的行。"""
    admin = fresh_client()
    mate = second_client("mate")
    workspace = mate.post("/api/workspaces", json={"name": "他自己的"}).json()["id"]

    admin.delete(f"/api/admin/users/{_user_id('mate')}")

    with SessionLocal() as db:
        assert db.get(Workspace, workspace) is None


def test_a_shared_workspace_stops_the_deletion() -> None:
    """还有别人在里面,就不能跟着删 —— 那是同事的素材、时间线、对话。"""
    admin = fresh_client()
    mate = second_client("mate")
    shared = mate.post("/api/workspaces", json={"name": "两个人的"}).json()["id"]
    mate.post(f"/api/workspaces/{shared}/invitations", json={"username": "tester", "role": "editor"})
    invitation = admin.get("/api/invitations").json()["invitations"][0]
    admin.post(f"/api/invitations/{invitation['id']}/accept")

    refused = admin.delete(f"/api/admin/users/{_user_id('mate')}")

    assert refused.status_code == 409, refused.text
    assert "两个人的" in refused.text, "该说清是哪几个工作区挡住了"
    assert _counts(_user_id("mate"))["users"] == 1, "拒绝之后不该删掉半个账号"


def test_the_last_deployment_admin_cannot_be_deleted() -> None:
    """和「不能收回最后一个管理员」同一条 —— 删掉他,这台部署就没人管了。"""
    admin = fresh_client()

    refused = admin.delete(f"/api/admin/users/{_user_id('tester')}")

    assert refused.status_code == 409, refused.text


def test_an_ordinary_member_cannot_delete_anyone() -> None:
    fresh_client()
    mate = second_client("mate")
    second_client("third")

    refused = mate.delete(f"/api/admin/users/{_user_id('third')}")

    assert refused.status_code == 403, refused.text


def test_nothing_of_anyone_elses_is_touched() -> None:
    """删一个人不该动到另一个人的任何东西。"""
    admin = fresh_client()
    mate = second_client("mate")
    keeper = second_client("keeper")
    keeper_ws = keeper.post("/api/workspaces", json={"name": "留着的"}).json()["id"]
    keeper.post("/api/agent/sessions", json={"workspace_id": keeper_ws, "title": "留着的对话"})
    before = _counts(_user_id("keeper"))

    admin.delete(f"/api/admin/users/{_user_id('mate')}")

    assert _counts(_user_id("keeper")) == before
    assert keeper.get("/api/auth/me").status_code == 200, "别人被登出了"


def test_his_credentials_and_defaults_go_too() -> None:
    """钥匙是他的身份,默认模型是他的偏好 —— 人没了,这两样没有任何意义。"""
    from app.db.models import ProviderCredential, ProviderDefault
    from tests.util import add_provider

    admin = fresh_client()
    mate = second_client("mate")
    mate_id = _user_id("mate")
    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"], owner_username="mate",
        )
        db.commit()
    with SessionLocal() as db:
        assert db.query(ProviderCredential).filter(ProviderCredential.owner_user_id == mate_id).count() == 1
        assert db.query(ProviderDefault).filter(ProviderDefault.owner_user_id == mate_id).count() >= 1

    admin.delete(f"/api/admin/users/{mate_id}")

    with SessionLocal() as db:
        assert db.query(ProviderCredential).filter(ProviderCredential.owner_user_id == mate_id).count() == 0
        assert db.query(ProviderDefault).filter(ProviderDefault.owner_user_id == mate_id).count() == 0


def test_deleting_someone_who_is_not_there_is_a_404() -> None:
    admin = fresh_client()

    assert admin.delete("/api/admin/users/nope").status_code == 404
