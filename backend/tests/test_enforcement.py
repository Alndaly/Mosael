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


def test_perm_override_grants_edit_to_viewer() -> None:
    owner, ws, viewer = _setup("viewer")
    me = viewer.get("/api/auth/me").json()
    owner.patch(f"/api/workspaces/{ws['id']}/members/{me['id']}/perms", json={"perms": {"edit": True}})
    # With `edit` granted, the same viewer can now create a project.
    assert viewer.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).status_code == 200


def test_finer_perm_override_gates_a_single_capability() -> None:
    owner, ws, editor = _setup("editor")
    me = editor.get("/api/auth/me").json()
    body = {"workspace_id": ws["id"], "name": "t", "kind": "noop", "trigger_type": "manual"}
    # Editor has `schedule` by default → the perm gate lets it through (domain may 422, never 403).
    assert editor.post("/api/scheduled-tasks", json=body).status_code != 403

    # Revoke just `schedule` from this editor → blocked, but `edit` is untouched.
    owner.patch(f"/api/workspaces/{ws['id']}/members/{me['id']}/perms", json={"perms": {"schedule": False}})
    assert editor.post("/api/scheduled-tasks", json=body).status_code == 403
    assert editor.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).status_code == 200


def test_viewer_can_run_retrieval_test() -> None:
    # A read-only POST (KB retrieval test) stays open to viewers.
    owner, ws, viewer = _setup("viewer")
    ds = owner.post("/api/kb/datasets", json={"workspace_id": ws["id"], "name": "D"}).json()
    r = viewer.post(f"/api/kb/datasets/{ds['id']}/retrieval-test", json={"query": "hello"})
    assert r.status_code == 200, r.text
