"""连接和钥匙都归创建它们的人,但分别保存、分别管理生命周期。

跑出来的现状(第 4 步动手前):

    owner 建供应商档案            200   密钥存在 provider_profiles.api_key
    viewer 列供应商               200   看得见这条连接
    viewer acquire 明文凭据       200   ← OAuth 档案时这里回的是明文
    viewer 改/删                  403   ← 第 1 步已收成部署管理员专属
    库里的档案                    owner_user_id: <无此列>

于是有两个方向相反的毛病挤在同一张表里:

  - **没人拥有这把钥匙**:能发起一轮对话的人就能 acquire 到它的明文;
  - **普通人没法带自己的钥匙**:配供应商是部署管理员专属,所有人共用管理员那一把 ——
    订阅制账号(Claude Pro/Max)被多人共用,花的也是同一个人的钱。

拆开的依据是这两件事回答的问题不同:

    ProviderProfile     这个人怎么连到这家供应商(端点、模型目录、定价)
    ProviderCredential  这个人在这条连接上使用的钥匙或 OAuth 身份

解析规则:**只选择自己的连接,再装配自己在该连接上的凭据;不跨用户回退**。

密钥列从 `provider_profiles` **搬走**而不是并存 —— 搬走之后 `ProviderProfile` 上没有
`.api_key` 可读,任何漏改的读取点会当场炸掉,而不是悄悄读到别人的钥匙。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import ProviderProfile, User
from tests.util import fresh_client, second_client


def _deployment_admin_and_member() -> tuple[TestClient, TestClient]:
    """第一个注册的账号是部署管理员(见第 1 步);mate 是普通成员。"""
    admin = fresh_client()
    workspace = admin.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    admin.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return admin, mate


def _connection(admin: TestClient, name: str = "OpenAI") -> str:
    """为当前用户建一条**连接**(不带钥匙)。"""
    made = admin.post("/api/settings/providers", json={"name": name, "vendor": "openai", "config": {}})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


# ---------------- 钥匙是人的 ----------------


def test_an_ordinary_member_can_bring_their_own_key() -> None:
    """配自己的钥匙不需要部署管理员 —— 连接现在也归他自己(见 test_connections_belong_to_a_person)。"""
    _admin, mate = _deployment_admin_and_member()
    profile_id = _connection(mate)

    saved = mate.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-MATE-1234"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["key_hint"] == "…1234"
    assert saved.json()["is_mine"] is True


def test_my_key_is_not_readable_by_anyone_else() -> None:
    admin, mate = _deployment_admin_and_member()
    profile_id = _connection(mate)
    saved = mate.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-MATE-1234"})
    assert saved.status_code == 200

    listed = admin.get("/api/settings/providers").json()
    assert all(row["id"] != profile_id for row in listed), "别人的连接不该出现在我的列表里"

    acquired = admin.post(f"/api/agent/provider-credentials/{profile_id}/acquire")
    assert acquired.status_code == 404, acquired.text


def test_deleting_my_key_leaves_the_connection_alone() -> None:
    """撤回钥匙 ≠ 删掉连接:端点、模型行都还在,只是这条连接暂时没钥匙可用。"""
    _admin, mate = _deployment_admin_and_member()
    profile_id = _connection(mate)
    mate.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-MATE-1234"})

    assert mate.delete(f"/api/settings/providers/{profile_id}/credential").status_code == 204
    rows = mate.get("/api/settings/providers").json()
    assert len(rows) == 1 and rows[0]["key_hint"] == "", "连接被一起删掉了"


def test_i_cannot_change_someone_elses_connection() -> None:
    """连接归人之后这条更强了:改不了,连"它存在"都不该知道 —— 所以是 404 不是 403。"""
    admin, mate = _deployment_admin_and_member()
    profile_id = _connection(admin)
    denied = mate.patch(f"/api/settings/providers/{profile_id}", json={"name": "改个名"})
    assert denied.status_code == 404, denied.text


# ---------------- 解析顺序:他自己那把,没有就是没有 ----------------


def test_each_person_uses_their_own_key() -> None:
    """两个人各配各的连接、各配各的钥匙,取到的必须是自己那把。"""
    from app.domain import provider_credentials

    admin, mate = _deployment_admin_and_member()
    theirs = _connection(admin)
    mine = _connection(mate)
    admin.put(f"/api/settings/providers/{theirs}/credential", json={"api_key": "sk-ADMIN"})
    mate.put(f"/api/settings/providers/{mine}/credential", json={"api_key": "sk-MATE"})

    with SessionLocal() as db:
        resolved = provider_credentials.resolve_connection(db, db.get(ProviderProfile, mine), _user_id("mate"))
        assert resolved is not None and resolved.api_key == "sk-MATE"
        # 别人那条连接就算硬拿到 id,钥匙也不是他的。
        others = provider_credentials.resolve_connection(db, db.get(ProviderProfile, theirs), _user_id("mate"))
        assert others is None or not others.api_key


def test_default_resolution_never_selects_another_users_earlier_connection() -> None:
    """同一 vendor 下按创建时间选默认项时,必须先按 owner 过滤。

    否则管理员较早创建的连接会被所有人先选中；随后凭据装配又正确地拒绝跨用户读取，最终让
    已经配置好自己连接的普通成员得到 None。
    """
    from app.domain import providers

    admin, mate = _deployment_admin_and_member()
    theirs = _connection(admin, "管理员较早创建的")
    mine = _connection(mate, "成员自己的")
    admin.put(f"/api/settings/providers/{theirs}/credential", json={"api_key": "sk-ADMIN"})
    mate.put(f"/api/settings/providers/{mine}/credential", json={"api_key": "sk-MATE"})

    with SessionLocal() as db:
        resolved = providers.resolve_connection(db, "openai", user_id=_user_id("mate"))

    assert resolved is not None
    assert resolved.id == mine
    assert resolved.api_key == "sk-MATE"


def test_without_any_key_it_says_so_instead_of_silently_using_someone_elses() -> None:
    admin, mate = _deployment_admin_and_member()
    profile_id = _connection(admin)
    admin.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-ADMIN"})

    # 走一条真实的用钱路径:文案生成会解析对话供应商。
    refused = mate.post(
        "/api/publish/copy",
        json={"workspace_id": mate.get("/api/workspaces").json()[0]["id"], "brief": "写个标题"},
    )
    assert refused.status_code in (403, 422), refused.text
    assert "密钥" in refused.text or "配置" in refused.text, refused.text


def test_there_is_no_such_thing_as_a_shared_key() -> None:
    """**没有回退。** 曾经有过一个 `shared` 位(部署管理员放一把大家都能用的),删掉了:它没有
    任何界面(等于隐藏状态),而且回退到别人的钥匙正是这张表要消灭的东西。"""
    from app.db.models import ProviderCredential
    from app.domain import provider_credentials

    admin, _mate = _deployment_admin_and_member()
    profile_id = _connection(admin)
    admin.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-ADMIN"})

    assert "shared" not in set(ProviderCredential.__table__.columns.keys())
    with SessionLocal() as db:
        assert provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), _user_id("mate")) is None


# ---------------- 搬走,而不是并存 ----------------


def test_the_profile_table_no_longer_holds_secrets() -> None:
    """密钥列从 provider_profiles 搬走 —— 留着它就等于留着一条能读到别人钥匙的路。"""
    columns = set(ProviderProfile.__table__.columns.keys())
    assert "api_key" not in columns
    assert "oauth_credential" not in columns


def test_the_migration_hands_existing_keys_to_the_deployment_admin() -> None:
    """升级前所有人共用档案上那把钥匙。迁移把它归到**最早那位部署管理员**名下 —— 有主人,
    而且只有他能用;别人各配各的(没有"共享钥匙"这回事)。"""
    from sqlalchemy import text

    from app.core.db import engine
    from app.db.migrations import _migrate_provider_credentials

    admin, mate = _deployment_admin_and_member()
    profile_id = _connection(admin)

    # 退回迁移前的形状:钥匙在档案行上,没有任何凭据行。
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM provider_credentials"))
        conn.execute(text("ALTER TABLE provider_profiles ADD COLUMN api_key VARCHAR(500) DEFAULT ''"))
        conn.execute(text("UPDATE provider_profiles SET api_key = 'sk-LEGACY' WHERE id = :i"), {"i": profile_id})

    _migrate_provider_credentials()

    from app.domain import provider_credentials

    with SessionLocal() as db:
        mine = provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), _user_id("tester"))
        assert mine is not None and mine.api_key == "sk-LEGACY", "老钥匙没有归到管理员名下"
        assert provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), _user_id("mate")) is None
    with engine.begin() as conn:
        assert "api_key" not in {row[1] for row in conn.execute(text("PRAGMA table_info(provider_profiles)"))}


def test_the_migration_adds_missing_columns_to_an_existing_credential_table() -> None:
    """装过中途版本的库:`provider_credentials` 已经存在,但少几列。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 真实的升级路径上撞过这个:
    `table provider_credentials has no column named model_catalog`,后端起不来。
    """
    from sqlalchemy import text

    from app.core.db import engine
    from app.db.migrations import _migrate_provider_credentials

    admin, _mate = _deployment_admin_and_member()
    profile_id = _connection(admin)

    # 退回那个形状:凭据表少两列,钥匙还在档案行上。
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE provider_credentials"))
        conn.execute(
            text(
                "CREATE TABLE provider_credentials ("
                "profile_id VARCHAR(64) NOT NULL, owner_user_id VARCHAR(64) NOT NULL, "
                "api_key VARCHAR(500) NOT NULL DEFAULT '', oauth_credential JSON, "
                "secrets JSON NOT NULL DEFAULT '{}', credential_version INTEGER NOT NULL DEFAULT 0, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (profile_id, owner_user_id))"
            )
        )
        conn.execute(text("ALTER TABLE provider_profiles ADD COLUMN api_key VARCHAR(500) DEFAULT ''"))
        conn.execute(text("UPDATE provider_profiles SET api_key = 'sk-LEGACY' WHERE id = :i"), {"i": profile_id})

    _migrate_provider_credentials()  # 不该抛

    from app.domain import provider_credentials

    with SessionLocal() as db:
        resolved = provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), _user_id("tester"))
        assert resolved is not None and resolved.api_key == "sk-LEGACY"
