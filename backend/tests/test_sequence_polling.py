"""The editor's poll should not re-send a sequence that has not changed."""

from __future__ import annotations

from tests.util import fresh_client


def _seeded():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    track = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in track["tracks"] if t["kind"] == "subtitle")
    return client, project["id"], sequence["id"], track_id


def test_an_unchanged_poll_gets_304_and_no_body() -> None:
    client, project_id, _, _ = _seeded()
    url = f"/api/projects/{project_id}/sequences"

    first = client.get(url)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"

    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""


def test_an_edit_changes_the_etag_so_the_poll_gets_fresh_data() -> None:
    client, project_id, seq_id, track_id = _seeded()
    url = f"/api/projects/{project_id}/sequences"
    etag = client.get(url).headers["etag"]

    client.post(
        f"/api/sequences/{seq_id}/text-clips",
        json={"track_id": track_id, "text": "new", "timeline_start": 0.0, "duration": 1.0},
    )

    res = client.get(url, headers={"If-None-Match": etag})
    assert res.status_code == 200, "a stale validator must not be honoured"
    assert res.headers["etag"] != etag
    assert b"new" in res.content
