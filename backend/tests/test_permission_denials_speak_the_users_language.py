"""角色不够时说人话(体检 UM-20)。

此前只读成员在素材库点「重命名」,toast 是开发者原话「Permission denied: edit」;编辑去改成员是
「Insufficient workspace role」。现在按要的那一档说:要几档、找谁调,并跟着界面语言走。
"""

from __future__ import annotations

from tests.util import fresh_client, second_client


def _join(owner, ws: str, username: str, role: str):
    member = second_client(username)
    sent = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": username, "role": role}).json()
    assert member.post(f"/api/invitations/{sent['id']}/accept").status_code == 200
    return member


def test_只读成员做要编辑的事_说要编辑及以上_找谁调() -> None:
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    viewer = _join(owner, ws, "viewer", "viewer")

    zh = viewer.post("/api/projects", json={"workspace_id": ws, "name": "P"}, headers={"Accept-Language": "zh-CN"})
    assert zh.status_code == 403
    assert "「只读」" in zh.json()["detail"] and "「编辑」" in zh.json()["detail"]
    assert "Permission denied" not in zh.json()["detail"]

    en = viewer.post("/api/projects", json={"workspace_id": ws, "name": "P"}, headers={"Accept-Language": "en-US"})
    assert en.status_code == 403 and "Editor or above" in en.json()["detail"]


def test_编辑去管成员_说要管理员或所有者() -> None:
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    editor = _join(owner, ws, "ed", "editor")
    second_client("bob")

    denied = editor.post(
        f"/api/workspaces/{ws}/invitations", json={"username": "bob", "role": "viewer"}, headers={"Accept-Language": "zh-CN"}
    )
    assert denied.status_code == 403
    assert "「管理员」" in denied.json()["detail"] and "Insufficient" not in denied.json()["detail"]

    me = editor.get("/api/auth/me").json()["id"]
    demoted = editor.patch(f"/api/workspaces/{ws}/members/{me}", json={"role": "viewer"}, headers={"Accept-Language": "en-US"})
    assert demoted.status_code == 403
    assert "Admin or Owner" in demoted.json()["detail"] and "Insufficient" not in demoted.json()["detail"]
