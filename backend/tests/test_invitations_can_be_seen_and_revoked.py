"""发出去的邀请看得见、撤得回;邀请码填错时说是码的问题(体检 UM-07、UM-09)。

此前工作区邀请发出去就看不见了,邀错了人只能等对方拒绝;注册邀请码发出去也撤不回。手里有码、码却用不了的人
被告知「这个部署不开放自助注册,请向管理员要一个邀请码」—— 和完全没填一模一样。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import Notification
from app.domain import deployment
from app.main import app
from tests.util import fresh_client, second_client


def _invite_notices(invitation_id: str) -> int:
    with SessionLocal() as db:
        return sum(1 for one in db.query(Notification).all() if (one.payload or {}).get("invitation_id") == invitation_id)


def test_工作区发出去的邀请列在团队页_能撤回_对方那张卡和通知一起没了() -> None:
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = second_client("mate")
    sent = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "viewer"}).json()

    listed = owner.get(f"/api/workspaces/{ws}/invitations").json()["invitations"]
    assert [(one["id"], one["role"], one["status"]) for one in listed] == [(sent["id"], "viewer", "pending")]
    assert _invite_notices(sent["id"]) == 1

    assert owner.delete(f"/api/workspaces/{ws}/invitations/{sent['id']}").status_code == 204
    assert owner.get(f"/api/workspaces/{ws}/invitations").json()["invitations"] == []
    assert mate.get("/api/invitations").json()["invitations"] == [], "对方通知里那张「接受 / 拒绝」卡要跟着没了"
    assert _invite_notices(sent["id"]) == 0
    assert mate.post(f"/api/invitations/{sent['id']}/accept").status_code == 409
    assert owner.delete(f"/api/workspaces/{ws}/invitations/{sent['id']}").status_code == 409, "撤回过的不能再撤一次"
    # 撤回之后可以重新邀请(换个角色)。
    assert owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "editor"}).status_code == 200


def test_看和撤回邀请与发邀请同一道闸() -> None:
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    editor = second_client("ed")
    sent = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "ed", "role": "editor"}).json()
    assert editor.post(f"/api/invitations/{sent['id']}/accept").status_code == 200
    second_client("bob")
    pending = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "bob", "role": "viewer"}).json()

    assert editor.get(f"/api/workspaces/{ws}/invitations").status_code == 403
    assert editor.delete(f"/api/workspaces/{ws}/invitations/{pending['id']}").status_code == 403
    other = owner.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    assert owner.delete(f"/api/workspaces/{other}/invitations/{pending['id']}").status_code == 409, "别的工作区的邀请撤不了"
    assert [one["id"] for one in owner.get(f"/api/workspaces/{ws}/invitations").json()["invitations"]] == [pending["id"]]


def test_邀请码填了却用不了_说是码的问题_没填才说去要一个() -> None:
    owner = fresh_client()
    with SessionLocal() as db:
        deployment.set_open_registration(db, False)
        db.commit()
    client = TestClient(app, headers={"Accept-Language": "zh-CN"})

    blank = client.post("/api/auth/register", json={"username": "a1", "password": "whatever123"})
    assert blank.status_code == 403 and "请向管理员要一个邀请码" in blank.json()["detail"]
    wrong = client.post("/api/auth/register", json={"username": "a1", "password": "whatever123", "invite_code": "deadbeef"})
    assert wrong.status_code == 403 and "这个邀请码用不了" in wrong.json()["detail"]

    code = owner.post("/api/auth/invites", json={"note": "给 a1"}).json()["code"]
    assert owner.delete(f"/api/auth/invites/{code}").status_code == 204
    revoked = client.post("/api/auth/register", json={"username": "a1", "password": "whatever123", "invite_code": code})
    assert revoked.status_code == 403 and "这个邀请码用不了" in revoked.json()["detail"]
    assert owner.delete(f"/api/auth/invites/{code}").status_code == 404


def test_用过的邀请码作废不了_只有部署管理员能作废() -> None:
    owner = fresh_client()
    member = second_client("member")
    with SessionLocal() as db:
        deployment.set_open_registration(db, False)
        db.commit()
    used = owner.post("/api/auth/invites", json={}).json()["code"]
    mate = TestClient(app)
    assert mate.post("/api/auth/register", json={"username": "mate", "password": "whatever123", "invite_code": used}).status_code == 200
    assert owner.delete(f"/api/auth/invites/{used}").status_code == 409

    fresh = owner.post("/api/auth/invites", json={}).json()["code"]
    assert member.delete(f"/api/auth/invites/{fresh}").status_code == 403
    assert any(row["code"] == fresh for row in owner.get("/api/auth/invites").json())
