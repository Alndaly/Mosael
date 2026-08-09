from __future__ import annotations

from tests.util import fresh_client, second_client


def _setup(role: str):
    """Owner workspace with a second member at `role`; returns (owner, ws, member_client)."""
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "mate", "role": role})
    inv = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{inv['id']}/accept")
    return owner, ws, mate


def test_viewer_is_read_only() -> None:
    owner, ws, viewer = _setup("viewer")
    # Read is allowed.
    assert viewer.get(f"/api/projects?workspace_id={ws['id']}").status_code == 200
    # Any mutation is blocked by the write gate.
    assert viewer.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).status_code == 403


def test_editor_can_edit_content() -> None:
    owner, ws, editor = _setup("editor")
    r = editor.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"})
    assert r.status_code == 200, r.text


def test_viewer_blocked_from_timeline_ops() -> None:
    owner, ws, viewer = _setup("viewer")
    proj = owner.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    seq = owner.post("/api/sequences", json={"workspace_id": ws["id"], "project_id": proj["id"], "name": "S"}).json()
    # A viewer may open the sequence...
    assert viewer.get(f"/api/sequences/{seq['id']}").status_code == 200
    # ...but not insert a text clip (a mutation).
    body = {"track_id": seq["tracks"][0]["id"], "timeline_start": 0, "text": "hi", "duration": 2}
    assert viewer.post(f"/api/sequences/{seq['id']}/text-clips", json=body).status_code == 403


def test_promoting_a_viewer_is_how_you_grant_writing() -> None:
    """逐位覆盖退场之后,「让这个人能改东西」的唯一办法是给他 editor(ADR 0008 D4)。

    此前是 `PATCH .../perms {"edit": true}` —— 一个 viewer 被单独打开 edit,于是他在名单上显示
    「查看者」却能改内容。少一种能让名单说谎的状态。
    """
    owner, ws, viewer = _setup("viewer")
    me = viewer.get("/api/auth/me").json()
    assert viewer.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).status_code == 403

    owner.patch(f"/api/workspaces/{ws['id']}/members/{me['id']}", json={"role": "editor"})

    assert viewer.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).status_code == 200


def test_an_editor_gets_the_whole_content_tier_at_once() -> None:
    """内容这一档不再拆成 upload / edit / delete / export / schedule 逐位配。

    它们之间的区分在这个产品里想不出真实场景 —— 能建定时任务却不能建项目,是什么角色?
    """
    _owner, ws, editor = _setup("editor")
    task = {"workspace_id": ws["id"], "name": "t", "kind": "noop", "trigger_type": "manual"}

    assert editor.post("/api/scheduled-tasks", json=task).status_code != 403
    assert editor.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).status_code == 200

