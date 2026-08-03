"""部署管理员:谁对**这个后端实例**负责。

此前这件事没有对应物。`ensure_instance_admin` 用「在**任意**工作区里是 owner/admin 且在那里持有
该权限」去近似它 —— 而任何登录用户都能新建工作区并在里面是 owner,所以那个近似是**自助的**:

    viewer 改实例级网络设置                   403
    他自己新建一个工作区之后再改一次           200

它守着的是网络代理、插件启用、TTS 解释器路径、模型下载 —— 都是「这台服务器怎么对外、跑什么」。
把它变成数据(`users.is_deployment_admin`)之后,判据不再能被自己造出来。

引导:库里第一个账号自动持有(自托管软件的通行做法,而且仓库里已有同一条理由的先例 ——
`_adopt_orphan_workspaces`)。之后只能由部署管理员授予。

**这不是「机器主人」**:共享部署里跑这个后端的人未必是任何一个用户。这个身份说的是谁对这个
部署负责,不是谁拥有这台机器(ADR 0008)。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import User
from tests.util import fresh_client, second_client

INSTANCE_WRITE = ("/api/settings/network", {"proxy_url": "", "no_proxy": ""})


def _user(username: str) -> User:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one()


def _join(owner: TestClient, workspace_id: str, username: str, role: str) -> TestClient:
    mate = second_client(username)
    owner.post(f"/api/workspaces/{workspace_id}/invitations", json={"username": username, "role": role})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return mate


# ---------------- 谁是部署管理员 ----------------


def test_the_bootstrap_account_is_the_deployment_admin() -> None:
    fresh_client()
    assert _user("tester").is_deployment_admin is True


def test_later_accounts_are_not() -> None:
    fresh_client()
    second_client("mate")
    assert _user("mate").is_deployment_admin is False


# ---------------- 自助升级这条路被封了 ----------------


def test_building_your_own_workspace_no_longer_grants_instance_settings() -> None:
    """本轮之前这条链是通的 —— 这条用例就是那条链的墓碑。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = _join(owner, workspace["id"], "mate", "viewer")

    path, body = INSTANCE_WRITE
    assert mate.put(path, json=body).status_code == 403

    mate.post("/api/workspaces", json={"name": "我自己的"})  # 在这里他是 owner

    assert mate.put(path, json=body).status_code == 403, "自助升级又通了"


def test_even_an_admin_of_a_workspace_is_not_a_deployment_admin() -> None:
    """工作区里的 admin 管的是那个工作区,不是这台服务器。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = _join(owner, workspace["id"], "mate", "admin")

    path, body = INSTANCE_WRITE
    assert mate.put(path, json=body).status_code == 403


def test_the_deployment_admin_is_not_locked_out() -> None:
    """单机安装里那个人就是引导账号 —— 他必须一切照旧。"""
    owner = fresh_client()
    path, body = INSTANCE_WRITE
    assert owner.put(path, json=body).status_code == 200


# ---------------- 授予与收回 ----------------


def test_a_deployment_admin_can_grant_it() -> None:
    owner = fresh_client()
    second_client("mate")
    mate_id = _user("mate").id

    granted = owner.post(f"/api/auth/users/{mate_id}/deployment-admin", json={"granted": True})

    assert granted.status_code == 200, granted.text
    assert _user("mate").is_deployment_admin is True


def test_a_granted_admin_can_then_change_instance_settings() -> None:
    owner = fresh_client()
    mate = second_client("mate")
    path, body = INSTANCE_WRITE
    assert mate.put(path, json=body).status_code == 403

    owner.post(f"/api/auth/users/{_user('mate').id}/deployment-admin", json={"granted": True})

    assert mate.put(path, json=body).status_code == 200


def test_an_ordinary_user_cannot_grant_it_to_themselves() -> None:
    """这是整条判据的关键 —— 能自己给自己发,就又回到自助了。"""
    fresh_client()
    mate = second_client("mate")

    denied = mate.post(f"/api/auth/users/{_user('mate').id}/deployment-admin", json={"granted": True})

    assert denied.status_code == 403, denied.text
    assert _user("mate").is_deployment_admin is False


def test_it_can_be_revoked() -> None:
    owner = fresh_client()
    second_client("mate")
    mate_id = _user("mate").id
    owner.post(f"/api/auth/users/{mate_id}/deployment-admin", json={"granted": True})

    owner.post(f"/api/auth/users/{mate_id}/deployment-admin", json={"granted": False})

    assert _user("mate").is_deployment_admin is False


def test_the_last_deployment_admin_cannot_be_removed() -> None:
    """没有部署管理员的部署改不了任何实例配置,也发不出邀请码 —— 那是一个砖头。"""
    owner = fresh_client()
    owner_id = _user("tester").id

    denied = owner.post(f"/api/auth/users/{owner_id}/deployment-admin", json={"granted": False})

    assert denied.status_code == 409, denied.text
    assert _user("tester").is_deployment_admin is True


# ---------------- 与第 0 步接上 ----------------


def test_issuing_registration_invites_now_reads_the_column() -> None:
    """第 0 步用「最早创建的账号」当过渡判据,现在换成这一列 —— 语义不变。"""
    owner = fresh_client()
    second_client("mate")
    owner.post(f"/api/auth/users/{_user('mate').id}/deployment-admin", json={"granted": True})

    from app.main import app

    granted_admin = TestClient(app)
    granted_admin.post("/api/auth/login", json={"username": "mate", "password": "pass1234"})
    token = granted_admin.post("/api/auth/login", json={"username": "mate", "password": "pass1234"}).json()["token"]
    granted_admin.headers["Authorization"] = f"Bearer {token}"

    assert granted_admin.post("/api/auth/invites", json={}).status_code == 200
