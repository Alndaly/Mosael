"""一个链接把人拉进工作区(ADR 0054,维护者 2026-10-09 按推荐拍板 D48–D52)。

此前拉一个同事进来要走五步:部署管理员发注册邀请码 → 对方注册、被要求先建一个自己的工作区 → 对方把用户名带外告诉
工作区管理员 → 工作区管理员按用户名邀请 → 对方接受。两种身份、两次带外传话、两个页面。现在:

- 工作区管理员发一张链接(选角色),7 天有效、用一次就作废、能撤回(D49);
- 已有账号的人打开就直接加入、切过去(D51);还没账号的人凭它注册,注册完直接是那个工作区的成员;
- 「能顺带注册」是部署那道门的事:部署管理员发的自带,工作区管理员发的要部署开放注册或者请部署管理员放行(D48);
- 此前的注册邀请码并进来,成了「不带工作区的邀请」,老码照样用到过期(D50);
- 部署配了网页地址,链接就带一个网页版(D52)。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import InviteLink, Notification, WorkspaceMember, now
from app.domain import deployment
from app.main import app
from tests.util import fresh_client, second_client, user_id

PASSWORD = "whatever123"


def _accept(client: TestClient, owner: TestClient, ws: str, username: str, role: str) -> None:
    sent = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": username, "role": role}).json()
    assert client.post(f"/api/invitations/{sent['id']}/accept").status_code == 200


def _set_open(value: bool) -> None:
    with SessionLocal() as db:
        deployment.set_open_registration(db, value)
        db.commit()


@pytest.fixture
def team():
    """部署管理员 tester 建了工作区「内容组」;wsadmin 是那里的管理员(不是部署管理员),viewer 是只读成员。
    建完人之后关掉自助注册 —— 这是邀请链接要解决的那种部署。"""
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "内容组"}).json()["id"]
    wsadmin = second_client("wsadmin")
    _accept(wsadmin, owner, ws, "wsadmin", "admin")
    viewer = second_client("looker")
    _accept(viewer, owner, ws, "looker", "viewer")
    outsider = second_client("outsider")
    late = second_client("late")
    _set_open(False)
    return SimpleNamespace(owner=owner, ws=ws, wsadmin=wsadmin, viewer=viewer, outsider=outsider, late=late)


def _issue(client: TestClient, ws: str, role: str = "editor") -> dict:
    issued = client.post(f"/api/workspaces/{ws}/invite-links", json={"role": role})
    assert issued.status_code == 200, issued.text
    return issued.json()


def _preview(code: str) -> dict:
    res = TestClient(app).post("/api/auth/invite-links/preview", json={"code": code})
    assert res.status_code == 200, res.text
    return res.json()


def _register(username: str, code: str) -> tuple[TestClient, object]:
    client = TestClient(app, headers={"Accept-Language": "zh-CN"})
    res = client.post("/api/auth/register", json={"username": username, "password": PASSWORD, "invite_code": code})
    if res.status_code == 200:
        client.headers["Authorization"] = f"Bearer {res.json()['token']}"
    return client, res


def _role(ws: str, username: str) -> str | None:
    with SessionLocal() as db:
        member = db.get(WorkspaceMember, {"workspace_id": ws, "user_id": user_id(username)})
        return member.role if member is not None else None


# ---------------- 已有账号的人:打开就加入(D51) ----------------


def test_an_existing_account_joins_directly_and_the_link_is_used_up(team) -> None:
    issued = _issue(team.wsadmin, team.ws, "editor")
    assert issued["link"]["state"] == "open" and issued["link"]["role"] == "editor"
    preview = _preview(issued["code"])
    assert preview == {"workspace_name": "内容组", "inviter_name": "wsadmin", "role": "editor", "state": "open",
                       "allows_signup": False}

    joined = team.outsider.post("/api/invite-links/redeem", json={"code": issued["code"]})
    assert joined.status_code == 200, joined.text
    assert joined.json() == {"workspace_id": team.ws, "workspace_name": "内容组", "role": "editor",
                             "owner_name": "tester", "already_member": False}
    assert _role(team.ws, "outsider") == "editor"
    # 同一个人再点一次:幂等,还是那个工作区(注册时已经凭它进来的人,界面照样调这一下);仍算「凭它加入的」,能撤销。
    again = team.outsider.post("/api/invite-links/redeem", json={"code": issued["code"]})
    assert again.status_code == 200 and again.json()["already_member"] is False
    assert _role(team.ws, "outsider") == "editor"

    # 一次性:别人再用就不行了,说清是哪件事。
    used = team.late.post("/api/invite-links/redeem", json={"code": issued["code"]}, headers={"Accept-Language": "zh-CN"})
    assert used.status_code == 409 and "已经有人用过了" in used.json()["detail"]
    assert _preview(issued["code"])["state"] == "used"

    # 发链接的人收到「X 通过邀请链接加入了」。
    with SessionLocal() as db:
        notes = [row for row in db.query(Notification).filter_by(user_id=user_id("wsadmin"))
                 if (row.payload or {}).get("kind") == "invite-link-used"]
    assert len(notes) == 1 and "outsider" in notes[0].title


def test_already_a_member_does_not_use_up_the_link(team) -> None:
    issued = _issue(team.wsadmin, team.ws, "admin")
    res = team.viewer.post("/api/invite-links/redeem", json={"code": issued["code"]})
    assert res.status_code == 200 and res.json()["already_member"] is True and res.json()["role"] == "viewer"
    assert _role(team.ws, "looker") == "viewer", "链接不会把已有成员的角色改掉"
    assert _preview(issued["code"])["state"] == "open", "没用掉 —— 还能转给真正要它的人"


def test_undo_is_leaving_the_workspace(team) -> None:
    issued = _issue(team.wsadmin, team.ws)
    team.outsider.post("/api/invite-links/redeem", json={"code": issued["code"]})
    me = team.outsider.get("/api/auth/me").json()["id"]
    assert team.outsider.delete(f"/api/workspaces/{team.ws}/members/{me}").status_code == 204
    assert _role(team.ws, "outsider") is None


# ---------------- 还没账号的人:谁能放他进部署(D48) ----------------


def test_a_workspace_admins_link_cannot_sign_people_up_on_an_invite_only_deployment(team) -> None:
    issued = _issue(team.wsadmin, team.ws)
    assert issued["link"]["allows_signup"] is False
    _client, res = _register("newbie", issued["code"])
    assert res.status_code == 403 and "只收受邀的人" in res.json()["detail"]
    assert _preview(issued["code"])["state"] == "open", "没注册成,链接也没用掉"


def test_a_deployment_admins_link_signs_up_straight_into_the_workspace(team) -> None:
    issued = _issue(team.owner, team.ws, "viewer")
    assert issued["link"]["allows_signup"] is True
    client, res = _register("newbie", issued["code"])
    assert res.status_code == 200, res.text
    assert _role(team.ws, "newbie") == "viewer", "注册完直接是成员 —— 不经过「先建一个自己的工作区」"
    assert [one["id"] for one in client.get("/api/workspaces").json()] == [team.ws]
    redeemed = client.post("/api/invite-links/redeem", json={"code": issued["code"]})
    assert redeemed.status_code == 200 and redeemed.json() == {
        "workspace_id": team.ws, "workspace_name": "内容组", "role": "viewer", "owner_name": "tester", "already_member": False,
    }, "界面登录之后照样兑现一下:回的是同一个工作区,而不是「已经有人用过了」"


def test_open_registration_lets_any_link_sign_people_up(team) -> None:
    issued = _issue(team.wsadmin, team.ws)
    _set_open(True)
    assert _preview(issued["code"])["allows_signup"] is True
    _client, res = _register("newbie", issued["code"])
    assert res.status_code == 200, res.text
    assert _role(team.ws, "newbie") == "editor"


def test_the_deployment_admin_can_let_a_workspace_link_sign_people_up(team) -> None:
    issued = _issue(team.wsadmin, team.ws)
    link_id = issued["link"]["id"]
    requested = team.wsadmin.post(f"/api/workspaces/{team.ws}/invite-links/{link_id}/request-signup")
    assert requested.status_code == 200 and requested.json()["signup_requested"] is True
    team.wsadmin.post(f"/api/workspaces/{team.ws}/invite-links/{link_id}/request-signup")  # 再点一次不重复通知
    with SessionLocal() as db:
        asks = [row for row in db.query(Notification).filter_by(user_id=user_id("tester"))
                if (row.payload or {}).get("kind") == "invite-link-signup"]
    assert len(asks) == 1 and asks[0].link == "#/admin"

    assert team.wsadmin.get("/api/admin/invite-links/awaiting-signup").status_code == 403
    awaiting = team.owner.get("/api/admin/invite-links/awaiting-signup").json()
    assert [row["id"] for row in awaiting] == [link_id]
    approved = team.owner.post(f"/api/admin/invite-links/{link_id}/approve-signup")
    assert approved.status_code == 200 and approved.json()["allows_signup"] is True
    assert team.owner.get("/api/admin/invite-links/awaiting-signup").json() == []

    _client, res = _register("newbie", issued["code"])
    assert res.status_code == 200, res.text
    assert _role(team.ws, "newbie") == "editor"


# ---------------- 谁能发、能撤、过期(D49) ----------------


def test_only_people_who_can_invite_can_issue_or_revoke(team) -> None:
    assert team.viewer.post(f"/api/workspaces/{team.ws}/invite-links", json={"role": "editor"}).status_code == 403
    assert team.outsider.post(f"/api/workspaces/{team.ws}/invite-links", json={"role": "editor"}).status_code == 404
    assert team.wsadmin.post(f"/api/workspaces/{team.ws}/invite-links", json={"role": "owner"}).status_code == 422, \
        "所有者不经链接给"
    from app.db.models import User
    from app.domain import members

    with SessionLocal() as db:
        with pytest.raises(members.MemberError) as refused:
            members.issue_invite_link(db, db.get(User, user_id("tester")), workspace_id=team.ws, role="owner")
        assert refused.value.key == "memberErr_linkRole", "领域里同一道:不只靠接口那层的格式校验"

    issued = _issue(team.wsadmin, team.ws)
    listed = team.owner.get(f"/api/workspaces/{team.ws}/invite-links").json()
    assert [(row["id"], row["code_hint"], row["created_by_name"]) for row in listed] == [
        (issued["link"]["id"], issued["code"][-4:], "wsadmin")
    ]
    other = team.owner.post("/api/workspaces", json={"name": "别的"}).json()["id"]
    assert team.owner.delete(f"/api/workspaces/{other}/invite-links/{issued['link']['id']}").status_code == 409, \
        "别的工作区撤不了这一张"
    assert team.viewer.delete(f"/api/workspaces/{team.ws}/invite-links/{issued['link']['id']}").status_code == 403
    assert team.wsadmin.delete(f"/api/workspaces/{team.ws}/invite-links/{issued['link']['id']}").status_code == 204
    assert team.owner.get(f"/api/workspaces/{team.ws}/invite-links").json() == []
    revoked = team.outsider.post("/api/invite-links/redeem", json={"code": issued["code"]},
                                 headers={"Accept-Language": "zh-CN"})
    assert revoked.status_code == 409 and "撤回" in revoked.json()["detail"]


def test_a_link_lasts_seven_days(team) -> None:
    issued = _issue(team.wsadmin, team.ws)
    with SessionLocal() as db:
        link = db.get(InviteLink, issued["link"]["id"])
        assert timedelta(days=6, hours=23) < link.expires_at - now() <= timedelta(days=7)
        link.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert _preview(issued["code"])["state"] == "expired"
    res = team.outsider.post("/api/invite-links/redeem", json={"code": issued["code"]}, headers={"Accept-Language": "zh-CN"})
    assert res.status_code == 409 and "7 天" in res.json()["detail"]
    assert team.owner.get(f"/api/workspaces/{team.ws}/invite-links").json() == [], "过期的不再列着"


def test_unknown_codes_and_signup_only_links(team) -> None:
    assert TestClient(app).post("/api/auth/invite-links/preview", json={"code": "not-a-real-code"}).status_code == 404
    assert team.outsider.post("/api/invite-links/redeem", json={"code": "not-a-real-code"}).status_code == 409
    signup_only = team.owner.post("/api/admin/invite-links", json={"note": "给新同事"}).json()
    res = team.outsider.post("/api/invite-links/redeem", json={"code": signup_only["code"]}, headers={"Accept-Language": "zh-CN"})
    assert res.status_code == 409 and "注册用的" in res.json()["detail"]


def test_the_code_is_only_stored_as_a_hash(team) -> None:
    issued = _issue(team.wsadmin, team.ws)
    with engine.begin() as conn:
        rows = [dict(row) for row in conn.execute(text("SELECT * FROM invite_links")).mappings()]
    assert rows and all(issued["code"] not in str(value) for row in rows for value in row.values())
    assert rows[0]["code_hint"] == issued["code"][-4:]


# ---------------- 网页地址(D52) ----------------


def test_the_web_address_rides_along_when_the_deployment_has_one(team) -> None:
    assert _issue(team.wsadmin, team.ws)["web_url"] == "", "桌面单机:没有网页版,只给深链"
    assert team.wsadmin.put("/api/admin/web-url", json={"url": "https://studio.example.com/"}).status_code == 403
    bad = team.owner.put("/api/admin/web-url", json={"url": "studio.example.com"})
    assert bad.status_code == 422
    saved = team.owner.put("/api/admin/web-url", json={"url": " https://studio.example.com/ "})
    assert saved.status_code == 200 and saved.json() == {"url": "https://studio.example.com"}
    assert TestClient(app).get("/api/auth/bootstrap").json()["web_url"] == "https://studio.example.com"
    assert _issue(team.wsadmin, team.ws)["web_url"] == "https://studio.example.com"


# ---------------- 升级(D50 与孤儿行) ----------------


def test_old_registration_codes_become_links_without_a_workspace_and_keep_working(team) -> None:
    """升级前发出去的注册邀请码:搬进邀请链接(只存哈希),照样用到过期;用过的标成用过;旧表删掉。"""
    from app.db.migrations import _migrate_registration_invites_become_invite_links as migrate

    stamp = now()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE registration_invites (code VARCHAR(64) PRIMARY KEY, created_by VARCHAR(64) NOT NULL,"
                          " note VARCHAR(120) NOT NULL DEFAULT '', used_by VARCHAR(64), created_at DATETIME NOT NULL,"
                          " expires_at DATETIME NOT NULL)"))
        for code, used_by, expires in (("oldcode-open-1234", None, stamp + timedelta(days=3)),
                                       ("oldcode-used-5678", user_id("wsadmin"), stamp + timedelta(days=3)),
                                       ("oldcode-late-9012", None, stamp - timedelta(days=1))):
            conn.execute(text("INSERT INTO registration_invites VALUES (:c, :by, '给老同事', :used, :created, :exp)"),
                         {"c": code, "by": user_id("tester"), "used": used_by, "created": stamp, "exp": expires})
    migrate()
    migrate()  # 幂等:旧表已经没了

    with engine.begin() as conn:
        assert "registration_invites" not in {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master"))}
    listed = {row["code_hint"]: row for row in team.owner.get("/api/admin/invite-links").json()}
    assert {hint: row["state"] for hint, row in listed.items()} == {"1234": "open", "5678": "used", "9012": "expired"}
    assert all(row["workspace_id"] is None and row["note"] == "给老同事" for row in listed.values())

    client, res = _register("oldfriend", "oldcode-open-1234")
    assert res.status_code == 200, res.text
    assert client.get("/api/workspaces").json() == [], "不带工作区:注册完自己建一个,或者再被人拉进去"
    _client, late = _register("toolate", "oldcode-late-9012")
    assert late.status_code == 403


def test_an_old_deployment_config_gets_the_web_address_column(team) -> None:
    """老库的 deployment_config 没有 web_url:迁移补上这一列(空串 = 没有网页版),原有的设置不动;重跑什么都不做。"""
    from app.db.migrations import _migrate_deployments_know_their_web_address as migrate

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config DROP COLUMN web_url"))
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(deployment_config)"))}
        assert "web_url" not in columns
    migrate()
    migrate()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT open_registration, web_url FROM deployment_config")).all()
    assert rows and all(web_url == "" for _open, web_url in rows)
    assert all(bool(open_) is False for open_, _web in rows), "原有的设置(这里是关掉了自助注册)不动"


def test_orphan_invitations_and_notifications_are_cleaned_up(team) -> None:
    """维护者库里有 2026-07-22 留下的两行孤儿:受邀人已不在的待处理邀请、收件人已不在的通知。
    团队页的「发出去的邀请」碰上它照样画得出来(连表连不上的那行不出现),迁移把它们清掉,外键核对干净。"""
    from app.db.migrations import _drop_invitations_and_notifications_of_people_who_are_gone as clean

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("INSERT INTO workspace_invitations (id, workspace_id, inviter_id, invitee_id, role, status, created_at)"
                          " VALUES ('orphan-inv', :ws, :by, 'gone-user', 'editor', 'pending', '2026-07-22 10:00:00')"),
                     {"ws": team.ws, "by": user_id("tester")})
        conn.execute(text("INSERT INTO notifications (id, workspace_id, user_id, type, title, body, payload, created_at)"
                          " VALUES ('orphan-note', :ws, 'gone-user', 'team', '邀请', '', '{}', '2026-07-22 10:00:00')"),
                     {"ws": team.ws})

    listed = team.owner.get(f"/api/workspaces/{team.ws}/invitations")
    assert listed.status_code == 200 and all(row["id"] != "orphan-inv" for row in listed.json()["invitations"])

    clean()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM workspace_invitations WHERE id = 'orphan-inv'")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM notifications WHERE id = 'orphan-note'")).scalar() == 0
        violations = conn.execute(text("PRAGMA foreign_key_check")).all()
    assert not [row for row in violations if row[0] in ("workspace_invitations", "notifications")]
