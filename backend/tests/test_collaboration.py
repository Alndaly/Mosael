from __future__ import annotations

from tests.util import fresh_client, second_client


def _team():
    owner = fresh_client("owner")
    workspace = owner.post("/api/workspaces", json={"name": "团队"}).json()
    mate = second_client("mate")
    owner.post(
        f"/api/workspaces/{workspace['id']}/invitations",
        json={"username": "mate", "role": "editor"},
    )
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    members = owner.get(f"/api/workspaces/{workspace['id']}/members").json()["members"]
    return owner, mate, workspace, {one["username"]: one["user_id"] for one in members}


def test_activity_exposes_actor_and_board_revision() -> None:
    owner, _mate, workspace, users = _team()
    board = owner.post("/api/boards", json={"workspace_id": workspace["id"], "name": "提案"}).json()
    owner.patch(
        f"/api/boards/{board['id']}",
        json={"workspace_id": workspace["id"], "base_revision": 1, "name": "正式提案"},
    )
    events = owner.get("/api/activity", params={"workspace_id": workspace["id"]}).json()
    assert [event["action"] for event in events[:2]] == ["board.renamed", "board.created"]
    assert events[0]["actor_id"] == users["owner"]
    assert events[0]["actor"]["username"] == "owner"
    assert events[0]["payload"] == {"base_revision": 1, "revision": 2}


def test_comment_mentions_member_and_delivers_notification() -> None:
    owner, mate, workspace, users = _team()
    board = owner.post("/api/boards", json={"workspace_id": workspace["id"]}).json()
    created = owner.post(
        "/api/comments",
        json={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
            "body": "@mate 请看一下构图",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["author"]["username"] == "owner"
    assert created.json()["mentioned_user_ids"] == [users["mate"]]
    notice = mate.get("/api/notifications", params={"workspace_id": workspace["id"]}).json()
    assert notice["items"][0]["type"] == "team"
    assert notice["items"][0]["payload"]["comment_id"] == created.json()["id"]


def test_review_can_only_be_decided_by_assigned_reviewer() -> None:
    owner, mate, workspace, users = _team()
    board = owner.post("/api/boards", json={"workspace_id": workspace["id"]}).json()
    review = owner.post(
        "/api/reviews",
        json={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
            "reviewer_id": users["mate"],
            "note": "请确认可以交付",
        },
    ).json()
    denied = owner.post(f"/api/reviews/{review['id']}/decision", json={"status": "approved"})
    assert denied.status_code == 403
    approved = mate.post(
        f"/api/reviews/{review['id']}/decision",
        json={"status": "approved", "note": "可以交付"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewer"]["username"] == "mate"

    actions = [
        one["action"]
        for one in owner.get(
            "/api/activity",
            params={"workspace_id": workspace["id"], "subject_type": "board", "subject_id": board["id"]},
        ).json()
    ]
    assert "review.requested" in actions
    assert "review.approved" in actions
