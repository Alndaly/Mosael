from __future__ import annotations

from tests.util import fresh_client


def test_project_rename_and_delete() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "Old"}).json()

    renamed = client.patch(f"/api/projects/{project['id']}", json={"name": "New name"}).json()
    assert renamed["name"] == "New name"

    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects?workspace_id={ws['id']}").json() == []


def test_asset_rename_and_delete_blocked_when_in_use() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "A",
              "file_key": "media/a.mp4", "media_info": {"duration": 5}},
    ).json()

    renamed = client.patch(f"/api/assets/{asset['id']}", json={"name": "B-roll"}).json()
    assert renamed["name"] == "B-roll"

    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 5},
    ).json()

    blocked = client.delete(f"/api/assets/{asset['id']}")
    assert blocked.status_code == 422  # in use on the timeline

    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]
    client.delete(f"/api/sequences/{sequence['id']}/clips/{clip['id']}")
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 204


def test_agent_session_rename_and_delete() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()

    renamed = client.patch(f"/api/agent/sessions/{session['id']}", json={"name": "剪辑讨论"}).json()
    assert renamed["title"] == "剪辑讨论"

    assert client.delete(f"/api/agent/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/agent/sessions/{session['id']}").status_code == 404
