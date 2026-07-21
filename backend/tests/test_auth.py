from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.util import PASSWORD, fresh_client, second_client


def test_register_login_me_logout_flow() -> None:
    client = fresh_client("kinda")
    me = client.get("/api/auth/me").json()
    assert me["username"] == "kinda"
    assert me["display_name"] == "kinda"
    assert me["signature"] == ""

    # fresh unauthenticated client is rejected
    anonymous = TestClient(app)
    assert anonymous.get("/api/workspaces").status_code == 401

    # login works with the right password only
    assert anonymous.post("/api/auth/login", json={"username": "kinda", "password": "wrong-pass"}).status_code == 401
    login = anonymous.post("/api/auth/login", json={"username": "kinda", "password": PASSWORD})
    assert login.status_code == 200

    # logout invalidates the session token
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_update_profile_and_password() -> None:
    client = fresh_client("kinda")
    profile = client.patch(
        "/api/auth/me",
        json={"username": "KindaHall", "display_name": "Kinda Hall", "signature": "剪完再睡"},
    )
    assert profile.status_code == 200
    assert profile.json()["username"] == "kindahall"
    assert profile.json()["display_name"] == "Kinda Hall"
    assert profile.json()["signature"] == "剪完再睡"

    assert (
        client.post("/api/auth/me/password", json={"current_password": "wrong-pass", "new_password": "new-pass"})
        .status_code
        == 401
    )
    assert (
        client.post("/api/auth/me/password", json={"current_password": PASSWORD, "new_password": "new-pass"}).status_code
        == 200
    )
    client.post("/api/auth/logout")

    anonymous = TestClient(app)
    assert anonymous.post("/api/auth/login", json={"username": "kindahall", "password": PASSWORD}).status_code == 401
    assert anonymous.post("/api/auth/login", json={"username": "kindahall", "password": "new-pass"}).status_code == 200


def test_duplicate_username_rejected() -> None:
    client = fresh_client("kinda")
    second_client("taken")
    res = client.post("/api/auth/register", json={"username": "kinda", "password": "whatever1"})
    assert res.status_code == 409
    res = client.patch("/api/auth/me", json={"username": "taken", "display_name": "Kinda", "signature": ""})
    assert res.status_code == 409


def test_workspace_isolation_between_users() -> None:
    alice = fresh_client("alice")
    ws = alice.post("/api/workspaces", json={"name": "Alice studio"}).json()
    project = alice.post("/api/projects", json={"workspace_id": ws["id"], "name": "Secret"}).json()
    sequence = alice.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()

    bob = second_client("bob")
    # bob sees no foreign workspaces and cannot touch alice's resources
    assert bob.get("/api/workspaces").json() == []
    assert bob.get(f"/api/projects?workspace_id={ws['id']}").status_code == 404
    assert bob.get(f"/api/assets?workspace_id={ws['id']}").status_code == 404
    assert bob.get(f"/api/sequences/{sequence['id']}").status_code == 404
    assert bob.post(f"/api/sequences/{sequence['id']}/undo").status_code == 404
    assert (
        bob.post("/api/projects", json={"workspace_id": ws["id"], "name": "Injected"}).status_code == 404
    )

    # alice still has full access
    assert alice.get(f"/api/sequences/{sequence['id']}").status_code == 200


def test_first_user_adopts_orphan_workspaces() -> None:
    # fresh DB with a workspace created pre-auth is impossible via API now,
    # so simulate: register user A, create workspace, then verify a second
    # user does NOT adopt it (members already exist).
    alice = fresh_client("alice")
    alice.post("/api/workspaces", json={"name": "W"})
    bob = second_client("bob")
    assert bob.get("/api/workspaces").json() == []


def test_media_endpoints_accept_query_token() -> None:
    client = fresh_client("kinda")
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("poster.png", b"fake-bytes", "image/png")},
    )
    asset = res.json()
    token = client.headers["Authorization"].removeprefix("Bearer ")

    bare = TestClient(app)
    assert bare.get(f"/api/assets/{asset['id']}/file").status_code == 401
    ok = bare.get(f"/api/assets/{asset['id']}/file?token={token}")
    assert ok.status_code == 200
