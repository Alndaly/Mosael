from __future__ import annotations

from tests.util import fresh_client, second_client


def _ws(client) -> dict:
    return client.post("/api/workspaces", json={"name": "W"}).json()


def test_add_member_creates_account_and_lists() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    assert ws["role"] == "owner"

    r = owner.post(f"/api/workspaces/{ws['id']}/members", json={"username": "alice", "password": "pass1234", "role": "editor"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["role"] == "editor" and m["perms"]["edit"] and not m["perms"]["members"]

    listing = owner.get(f"/api/workspaces/{ws['id']}/members").json()
    assert listing["my_role"] == "owner"
    assert {mm["username"] for mm in listing["members"]} == {"tester", "alice"}
    assert "members" in listing["perm_keys"] and "editor" in listing["role_defaults"]

    # The new account can log in and sees the workspace with its role.
    alice = second_client("alice")
    wss = alice.get("/api/workspaces").json()
    assert any(w["id"] == ws["id"] and w["role"] == "editor" for w in wss)


def test_editor_cannot_manage_members() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    owner.post(f"/api/workspaces/{ws['id']}/members", json={"username": "ed", "password": "pass1234", "role": "editor"})
    ed = second_client("ed")
    r = ed.post(f"/api/workspaces/{ws['id']}/members", json={"username": "bob", "password": "pass1234", "role": "viewer"})
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
    m = owner.post(f"/api/workspaces/{ws['id']}/members", json={"username": "vi", "password": "pass1234", "role": "viewer"}).json()
    granted = owner.patch(f"/api/workspaces/{ws['id']}/members/{m['user_id']}/perms", json={"perms": {"edit": True}})
    assert granted.status_code == 200 and granted.json()["perms"]["edit"] is True
    revoked = owner.patch(f"/api/workspaces/{ws['id']}/members/{m['user_id']}/perms", json={"perms": {}})
    assert revoked.json()["perms"]["edit"] is False


def test_only_owner_can_grant_owner() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    owner.post(f"/api/workspaces/{ws['id']}/members", json={"username": "ad", "password": "pass1234", "role": "admin"})
    ad = second_client("ad")
    ad_id = ad.get("/api/auth/me").json()["id"]
    assert ad.patch(f"/api/workspaces/{ws['id']}/members/{ad_id}", json={"role": "owner"}).status_code == 403
    promoted = owner.patch(f"/api/workspaces/{ws['id']}/members/{ad_id}", json={"role": "owner"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "owner"


def test_rename_and_delete_role_gates() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    owner.post(f"/api/workspaces/{ws['id']}/members", json={"username": "vv", "password": "pass1234", "role": "viewer"})
    vv = second_client("vv")
    assert vv.patch(f"/api/workspaces/{ws['id']}", json={"name": "X"}).status_code == 403
    assert vv.delete(f"/api/workspaces/{ws['id']}").status_code == 403
    assert owner.patch(f"/api/workspaces/{ws['id']}", json={"name": "X"}).status_code == 200


def test_self_leave_allowed() -> None:
    owner = fresh_client()
    ws = _ws(owner)
    owner.post(f"/api/workspaces/{ws['id']}/members", json={"username": "leaver", "password": "pass1234", "role": "editor"})
    leaver = second_client("leaver")
    leaver_id = leaver.get("/api/auth/me").json()["id"]
    assert leaver.delete(f"/api/workspaces/{ws['id']}/members/{leaver_id}").status_code == 204
    assert not any(w["id"] == ws["id"] for w in leaver.get("/api/workspaces").json())
