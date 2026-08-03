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


def test_the_role_is_the_whole_answer() -> None:
    """成员这一栏只剩角色 —— 接口不再返回 perms,也没有逐位设置的路由(ADR 0008 D4)。

    留着一个没人配的矩阵,只会让人以为它在起作用;而它记录的恰恰是"某人被单独关掉了某项能力"
    这种最容易被误读的信息。
    """
    owner = fresh_client()
    ws = _ws(owner)
    mate = _join(owner, ws["id"], "mate", "editor")
    info = owner.get(f"/api/workspaces/{ws['id']}/members").json()

    assert set(info) == {"members", "my_role"}, info
    for member in info["members"]:
        assert set(member) >= {"user_id", "username", "role"}
        assert "perms" not in member

    me = mate.get("/api/auth/me").json()
    gone = owner.patch(f"/api/workspaces/{ws['id']}/members/{me['id']}/perms", json={"perms": {"edit": False}})
    assert gone.status_code == 404, gone.text

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
