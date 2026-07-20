"""A sequence belongs to a project, and that project has to be one you can reach."""

from __future__ import annotations

from tests.util import fresh_client, second_client


def test_a_sequence_cannot_be_planted_in_another_workspaces_project() -> None:
    """workspace_id was authorised and project_id was not, while the listing route filters only
    on project_id — so this put attacker-controlled rows inside a victim's project."""
    victim = fresh_client()
    victim_ws = victim.post("/api/workspaces", json={"name": "V"}).json()["id"]
    victim_project = victim.post("/api/projects", json={"workspace_id": victim_ws, "name": "P"}).json()

    attacker = second_client()
    attacker_ws = attacker.post("/api/workspaces", json={"name": "A"}).json()["id"]

    res = attacker.post(
        "/api/sequences",
        json={"workspace_id": attacker_ws, "project_id": victim_project["id"], "name": "planted"},
    )
    assert res.status_code == 404, res.text

    listing = victim.get(f"/api/projects/{victim_project['id']}/sequences").json()
    assert [s["name"] for s in listing] == []


def test_creating_a_sequence_in_your_own_project_still_works() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()

    res = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"})
    assert res.status_code == 200, res.text

    # active_sequence_id was assigned before flush, so the id was still None and it never stuck.
    projects = client.get("/api/projects", params={"workspace_id": ws}).json()
    refreshed = next(p for p in projects if p["id"] == project["id"])
    assert refreshed.get("active_sequence_id") == res.json()["id"]
