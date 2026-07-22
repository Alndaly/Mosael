from __future__ import annotations

from tests.util import fresh_client, second_client


def _ws(client) -> dict:
    return client.post("/api/workspaces", json={"name": "W"}).json()


def _join(owner, ws_id: str, username: str, role: str = "editor"):
    """邀请制入队:先注册账号,再走 邀请 → 通知 → 接受 全链路。"""
    member = second_client(username)
    r = owner.post(f"/api/workspaces/{ws_id}/invitations", json={"username": username, "role": role})
    assert r.status_code == 200, r.text
    inv = member.get("/api/invitations").json()["invitations"][0]
    assert member.post(f"/api/invitations/{inv['id']}/accept").status_code == 200
    return member


def test_invitation_flow_accept() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    assert ws["role"] == "owner"

    # 未注册用户名不可邀请(不再替人建号)。
    r = owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "ghost", "role": "editor"})
    assert r.status_code == 409

    alice = second_client("alice")
    r = owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "alice", "role": "editor"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    # 受邀人在自己的待处理列表看到邀请(通知中心跨工作区读这个接口);接受后成为成员。
    inv = alice.get("/api/invitations").json()["invitations"][0]
    assert inv["workspace_name"] == "W" and inv["role"] == "editor"
    accepted = alice.post(f"/api/invitations/{inv['id']}/accept").json()
    assert accepted["status"] == "accepted"

    listing = owner.get(f"/api/workspaces/{ws['id']}/members").json()
    assert {mm["username"] for mm in listing["members"]} == {"tester", "alice"}
    wss = alice.get("/api/workspaces").json()
    assert any(w["id"] == ws["id"] and w["role"] == "editor" for w in wss)
    # 重复应答被拒;邀请人收到结果通知。
    assert alice.post(f"/api/invitations/{inv['id']}/accept").status_code == 409
    owner_notif = owner.get(f"/api/notifications?workspace_id={ws['id']}").json()["items"]
    assert any(n["payload"].get("kind") == "invite-result" and n["payload"].get("accepted") for n in owner_notif)


def test_invitation_decline_keeps_nonmember() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    bob = second_client("bob")
    owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "bob", "role": "viewer"})
    inv = bob.get("/api/invitations").json()["invitations"][0]
    assert bob.post(f"/api/invitations/{inv['id']}/decline").json()["status"] == "declined"
    listing = owner.get(f"/api/workspaces/{ws['id']}/members").json()
    assert {mm["username"] for mm in listing["members"]} == {"tester"}
    # 拒绝后可以再次邀请。
    assert owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "bob", "role": "viewer"}).status_code == 200


def test_editor_cannot_manage_members() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    ed = _join(owner, ws["id"], "ed", "editor")
    second_client("bob")
    r = ed.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "bob", "role": "viewer"})
    assert r.status_code == 403


def test_last_owner_cannot_be_demoted_or_removed() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    me = owner.get("/api/auth/me").json()
    assert owner.patch(f"/api/workspaces/{ws['id']}/members/{me['id']}", json={"role": "admin"}).status_code == 409
    assert owner.delete(f"/api/workspaces/{ws['id']}/members/{me['id']}").status_code == 409


def test_perm_override_grants_and_revokes() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    _join(owner, ws["id"], "vi", "viewer")
    m = next(mm for mm in owner.get(f"/api/workspaces/{ws['id']}/members").json()["members"] if mm["username"] == "vi")
    granted = owner.patch(f"/api/workspaces/{ws['id']}/members/{m['user_id']}/perms", json={"perms": {"edit": True}})
    assert granted.status_code == 200 and granted.json()["perms"]["edit"] is True
    revoked = owner.patch(f"/api/workspaces/{ws['id']}/members/{m['user_id']}/perms", json={"perms": {}})
    assert revoked.json()["perms"]["edit"] is False


def test_only_owner_can_grant_owner() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    ad = _join(owner, ws["id"], "ad", "admin")
    ad_id = ad.get("/api/auth/me").json()["id"]
    assert ad.patch(f"/api/workspaces/{ws['id']}/members/{ad_id}", json={"role": "owner"}).status_code == 403
    promoted = owner.patch(f"/api/workspaces/{ws['id']}/members/{ad_id}", json={"role": "owner"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "owner"


def test_rename_and_delete_role_gates() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    vv = _join(owner, ws["id"], "vv", "viewer")
    assert vv.patch(f"/api/workspaces/{ws['id']}", json={"name": "X"}).status_code == 403
    assert vv.delete(f"/api/workspaces/{ws['id']}").status_code == 403
    assert owner.patch(f"/api/workspaces/{ws['id']}", json={"name": "X"}).status_code == 200


def test_self_leave_allowed() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    leaver = _join(owner, ws["id"], "leaver", "editor")
    leaver_id = leaver.get("/api/auth/me").json()["id"]
    assert leaver.delete(f"/api/workspaces/{ws['id']}/members/{leaver_id}").status_code == 204
    assert not any(w["id"] == ws["id"] for w in leaver.get("/api/workspaces").json())
