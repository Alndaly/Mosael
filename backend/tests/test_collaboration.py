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


def test_canvas_comment_preserves_anchor_and_tiptap_document() -> None:
    owner, _mate, workspace, users = _team()
    board = owner.post("/api/boards", json={"workspace_id": workspace["id"]}).json()
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "请 "},
                    {
                        "type": "userMention",
                        "attrs": {"userId": users["mate"], "label": "mate"},
                    },
                    {"type": "text", "text": " 看一下这里"},
                ],
            }
        ],
    }
    anchor = {"kind": "canvas", "x": 320.5, "y": 140.25, "node_id": "image-1"}

    created = owner.post(
        "/api/comments",
        json={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
            "body": "请 @mate 看一下这里",
            "body_document": document,
            "anchor": anchor,
            "mentioned_user_ids": [users["mate"]],
        },
    )

    assert created.status_code == 200, created.text
    assert created.json()["anchor"] == anchor
    assert created.json()["body_document"] == document
    assert owner.get(
        f"/api/boards/{board['id']}", params={"workspace_id": workspace["id"]}
    ).json()["revision"] == board["revision"]
    listed = owner.get(
        "/api/comments",
        params={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
        },
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["anchor"] == anchor
    assert listed.json()[0]["body_document"] == document
    activity = owner.get(
        "/api/activity",
        params={"workspace_id": workspace["id"], "subject_type": "board", "subject_id": board["id"]},
    ).json()
    assert activity[0]["payload"]["anchor"] == anchor


def test_comment_author_can_move_own_canvas_comment() -> None:
    owner, _mate, workspace, _users = _team()
    board = owner.post("/api/boards", json={"workspace_id": workspace["id"]}).json()
    created = owner.post(
        "/api/comments",
        json={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
            "body": "请看这里",
            "anchor": {"kind": "canvas", "x": 100, "y": 120},
        },
    ).json()

    moved = owner.patch(
        f"/api/comments/{created['id']}",
        json={
            "workspace_id": workspace["id"],
            "anchor": {"kind": "canvas", "x": 480.5, "y": 260.25},
        },
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["anchor"] == {"kind": "canvas", "x": 480.5, "y": 260.25, "node_id": None}
    activity = owner.get(
        "/api/activity",
        params={"workspace_id": workspace["id"], "subject_type": "board", "subject_id": board["id"]},
    ).json()
    assert activity[0]["action"] == "comment.moved"
    assert activity[0]["payload"]["anchor"] == {"kind": "canvas", "x": 480.5, "y": 260.25}


def test_team_member_cannot_move_another_authors_comment() -> None:
    owner, mate, workspace, _users = _team()
    board = owner.post("/api/boards", json={"workspace_id": workspace["id"]}).json()
    created = owner.post(
        "/api/comments",
        json={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
            "body": "作者决定放在哪里",
            "anchor": {"kind": "canvas", "x": 100, "y": 120},
        },
    ).json()

    denied = mate.patch(
        f"/api/comments/{created['id']}",
        json={
            "workspace_id": workspace["id"],
            "anchor": {"kind": "canvas", "x": 500, "y": 300},
        },
    )

    assert denied.status_code == 403
    listed = owner.get(
        "/api/comments",
        params={
            "workspace_id": workspace["id"],
            "subject_type": "board",
            "subject_id": board["id"],
        },
    ).json()
    assert listed[0]["anchor"]["x"] == 100
    assert listed[0]["anchor"]["y"] == 120


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
