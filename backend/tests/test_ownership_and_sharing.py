"""归属与共享是两件事。

此前它们被压成了一件:把东西放进工作区,既是存储方式,**也是**共享方式 —— 于是没有「放进来但
仍然是我的」这种状态。后果跑出来过:

    editor 列出 owner 的对话           ['owner 的私人对话']
    editor 读 owner 对话里的消息        200
    editor 用 owner 登录的 B 站账号发布  200

`PublishAccount` 存的是某人在平台上的登录态,`BrowserProfile` 存的是某人已登录的浏览器 ——
它们不是"工作区的资产",是某人的身份。而这三张表(加上定时任务)**一张都没有 `user_id`**。
这不是配置错了,是这些东西压根没有「主人」这一栏。

拆开之后一条规则覆盖四类资源,不是四个特例:

  - **归属**:`owner_user_id`,谁建的就是谁的。
  - **共享**:`resource_shares` 里的一行,主人显式放进某个工作区,可以撤回。

**默认按类别定**(见 domain/sharing.DEFAULT_SHARED):身份与私人对话默认私有;定时任务默认共享 ——
它是团队基建,归属是为了可追溯与停摆,不是为了藏起来。把这一条写成一张表而不是一个到处判断的
if,是因为「这一类默认给谁看」正是最容易在第二个调用点被写反的东西。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import BrowserProfile, PublishAccount, User
from tests.util import fresh_client, second_client


def _team(role: str = "editor") -> tuple[TestClient, dict, TestClient]:
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": role})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _seed_publish_account(workspace_id: str, owner_username: str) -> str:
    with SessionLocal() as db:
        account = PublishAccount(
            workspace_id=workspace_id,
            platform="bilibili",
            name=f"{owner_username} 的 B 站",
            owner_user_id=db.query(User).filter(User.username == owner_username).one().id,
        )
        db.add(account)
        db.commit()
        return account.id


# ---------------- 默认私有 ----------------


def test_a_publish_account_is_private_by_default() -> None:
    """某人的平台登录态不是工作区的公共资产。"""
    owner, workspace, mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")

    mine = owner.get(f"/api/publish/accounts?workspace_id={workspace['id']}").json()
    theirs = mate.get(f"/api/publish/accounts?workspace_id={workspace['id']}").json()

    assert account_id in [row["id"] for row in mine]
    assert account_id not in [row["id"] for row in theirs], "同事默认看得见别人的登录账号"


def test_an_agent_session_is_private_by_default() -> None:
    owner, workspace, mate = _team()
    session = owner.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "私人对话"}
    ).json()

    listed = mate.get(f"/api/agent/sessions?workspace_id={workspace['id']}").json()
    assert session["id"] not in [row["id"] for row in listed]

    assert mate.get(f"/api/agent/sessions/{session['id']}/messages").status_code == 404


def test_a_browser_profile_is_private_by_default() -> None:
    owner, workspace, mate = _team()
    made = owner.post("/api/browser/profiles", json={"workspace_id": workspace["id"], "name": "我的登录浏览器"})
    assert made.status_code == 200, made.text

    listed = mate.get(f"/api/browser/profiles?workspace_id={workspace['id']}").json()
    assert made.json()["id"] not in [row["id"] for row in listed]


def test_a_scheduled_task_is_shared_by_default() -> None:
    """定时任务是团队基建 —— 归属是为了可追溯与停摆,不是为了藏起来。

    这一条和上面三条相反,而这个差别是**声明在一张表里**的(DEFAULT_SHARED),不是散在各处的
    判断:「这一类默认给谁看」正是最容易在第二个调用点被写反的东西。
    """
    owner, workspace, mate = _team()
    task = owner.post(
        "/api/scheduled-tasks",
        json={"workspace_id": workspace["id"], "name": "每晚发布", "kind": "noop", "trigger_type": "manual"},
    )
    assert task.status_code == 200, task.text

    listed = mate.get(f"/api/scheduled-tasks?workspace_id={workspace['id']}").json()
    assert task.json()["id"] in [row["id"] for row in listed]


# ---------------- 共享是显式的,而且可撤回 ----------------


def test_sharing_makes_it_visible_to_the_workspace() -> None:
    owner, workspace, mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")

    shared = owner.post(
        f"/api/shares/publish_account/{account_id}", json={"workspace_id": workspace["id"]}
    )
    assert shared.status_code == 200, shared.text

    listed = mate.get(f"/api/publish/accounts?workspace_id={workspace['id']}").json()
    assert account_id in [row["id"] for row in listed]


def test_sharing_can_be_withdrawn() -> None:
    owner, workspace, mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")
    owner.post(f"/api/shares/publish_account/{account_id}", json={"workspace_id": workspace["id"]})

    owner.request(
        "DELETE",
        f"/api/shares/publish_account/{account_id}",
        json={"workspace_id": workspace["id"]},
    )

    listed = mate.get(f"/api/publish/accounts?workspace_id={workspace['id']}").json()
    assert account_id not in [row["id"] for row in listed]


def test_only_the_owner_can_share_it() -> None:
    """共享是主人的授权动作 —— 别人替他做出来的授权不叫授权。"""
    _owner, workspace, mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")

    denied = mate.post(
        f"/api/shares/publish_account/{account_id}", json={"workspace_id": workspace["id"]}
    )
    assert denied.status_code == 403, denied.text


def test_you_cannot_share_into_a_workspace_you_are_not_in() -> None:
    owner, _workspace, _mate = _team()
    other = owner.post("/api/workspaces", json={"name": "别处"}).json()
    stranger = second_client("stranger2")
    account_id = _seed_publish_account(other["id"], "tester")

    denied = stranger.post(
        f"/api/shares/publish_account/{account_id}", json={"workspace_id": other["id"]}
    )
    assert denied.status_code in (403, 404), denied.text


# ---------------- 归属决定的是"能不能用",不只是"看不看得见" ----------------


def test_an_unshared_account_cannot_be_used_to_publish() -> None:
    """看不见还不够 —— 猜到 id 也用不了。"""
    _owner, workspace, mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")

    refused = mate.post(
        "/api/publish/tasks",
        json={"workspace_id": workspace["id"], "account_id": account_id, "asset_id": "whatever"},
    )
    assert refused.status_code in (403, 404), refused.text


# ---------------- 迁移:升级前后行为一致 ----------------


def test_existing_rows_stay_visible_after_the_migration() -> None:
    """老库里的东西今天大家都看得见 —— 升级不该把它们从同事眼前拿走。

    迁移给每一条已存在的记录建一行「共享给它当前所在的工作区」,所以行为完全一致;
    **从此以后新建的默认私有**。
    """
    from app.core.db import _migrate_resource_ownership, engine
    from sqlalchemy import text

    owner, workspace, mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")

    # 把它退回迁移前的形状:有归属、但没有共享行。
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM resource_shares"))

    _migrate_resource_ownership()

    listed = mate.get(f"/api/publish/accounts?workspace_id={workspace['id']}").json()
    assert account_id in [row["id"] for row in listed]


def test_the_migration_is_idempotent() -> None:
    from app.core.db import _migrate_resource_ownership, engine
    from sqlalchemy import text

    owner, workspace, _mate = _team()
    _seed_publish_account(workspace["id"], "tester")
    _migrate_resource_ownership()
    _migrate_resource_ownership()

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM resource_shares")).scalar()
    assert rows == 1, f"跑两次建出了 {rows} 行"


# ---------------- 主人自己始终看得见 ----------------


def test_the_owner_always_sees_their_own_even_without_a_share() -> None:
    owner, workspace, _mate = _team()
    account_id = _seed_publish_account(workspace["id"], "tester")
    listed = owner.get(f"/api/publish/accounts?workspace_id={workspace['id']}").json()
    assert account_id in [row["id"] for row in listed]


def test_a_profile_kept_private_is_still_usable_by_its_owner() -> None:
    owner, workspace, _mate = _team()
    made = owner.post("/api/browser/profiles", json={"workspace_id": workspace["id"], "name": "我的"}).json()
    with SessionLocal() as db:
        assert db.get(BrowserProfile, made["id"]).owner_user_id == _user_id("tester")


# ---------------- 发布账号与它的浏览器档案是一个身份 ----------------


def test_sharing_an_account_shares_its_browser_profile_too() -> None:
    """建账号时顺带建了档案(共用登录分区)—— 只共享一半会得到一个说不通的状态:
    看得见账号,却没有那个已登录的浏览器。"""
    owner, workspace, mate = _team()
    account = owner.post(
        "/api/publish/accounts",
        json={"workspace_id": workspace["id"], "platform": "bilibili", "name": "频道", "config": {}},
    )
    assert account.status_code == 200, account.text
    account_id = account.json()["id"]

    assert mate.get(f"/api/browser/profiles?workspace_id={workspace['id']}").json() == []

    owner.post(f"/api/shares/publish_account/{account_id}", json={"workspace_id": workspace["id"]})

    profiles = mate.get(f"/api/browser/profiles?workspace_id={workspace['id']}").json()
    assert len(profiles) == 1, "共享了账号,同事却看不到它的浏览器档案"

    owner.request(
        "DELETE", f"/api/shares/publish_account/{account_id}", json={"workspace_id": workspace["id"]}
    )
    assert mate.get(f"/api/browser/profiles?workspace_id={workspace['id']}").json() == [], "收回账号后档案还留着"


def test_the_owner_sees_it_flagged_as_mine() -> None:
    owner, workspace, _mate = _team()
    made = owner.post("/api/browser/profiles", json={"workspace_id": workspace["id"], "name": "我的"}).json()
    assert made["is_mine"] is True and made["shared"] is False
