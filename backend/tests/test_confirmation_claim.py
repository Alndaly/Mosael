"""An approval must fire exactly once, even if two arrive together.

`_require_pending` read status off the in-memory ORM object and the caller then assigned it —
a check-then-act. Two requests that both loaded the pending row both passed the check and both
ran the executor, so one approval added two tracks, queued two renders, or billed two images.
"""

from __future__ import annotations

import threading

import pytest

from app.core.db import SessionLocal
from app.db.models import ToolConfirmation
from app.domain.agent.confirmations import ConfirmationError, _claim
from tests.util import fresh_client


def _pending_confirmation(workspace_id: str, sequence_id: str) -> str:
    with SessionLocal() as db:
        row = ToolConfirmation(
            workspace_id=workspace_id,
            tool="edit_timeline",
            permission="edit",
            summary="test",
            requested_by="agent",
            status="pending",
            payload={"sequence_id": sequence_id, "operations": [{"kind": "add_track", "track_kind": "video"}]},
        )
        db.add(row)
        db.commit()
        return row.id


@pytest.fixture()
def seeded():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    return client, ws, sequence["id"]


def test_only_one_of_two_racing_claims_wins(seeded) -> None:
    _, ws, seq_id = seeded
    confirmation_id = _pending_confirmation(ws, seq_id)

    ready = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        with SessionLocal() as db:
            row = db.get(ToolConfirmation, confirmation_id)
            ready.wait(timeout=5)  # both hold a "pending" row before either writes
            try:
                _claim(db, row, "approved")
                result = "won"
            except ConfirmationError:
                result = "refused"
            with lock:
                outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(outcomes) == ["refused", "won"], f"both callers proceeded: {outcomes}"


def test_a_settled_confirmation_cannot_be_claimed_again(seeded) -> None:
    _, ws, seq_id = seeded
    confirmation_id = _pending_confirmation(ws, seq_id)

    with SessionLocal() as db:
        row = db.get(ToolConfirmation, confirmation_id)
        _claim(db, row, "approved")

    with SessionLocal() as db:
        row = db.get(ToolConfirmation, confirmation_id)
        with pytest.raises(ConfirmationError):
            _claim(db, row, "approved")


def test_approving_twice_over_the_api_runs_the_tool_once(seeded) -> None:
    client, ws, seq_id = seeded
    before = len(client.get(f"/api/sequences/{seq_id}").json()["tracks"])
    confirmation_id = _pending_confirmation(ws, seq_id)

    first = client.post(f"/api/confirmations/{confirmation_id}/approve")
    assert first.status_code == 200, first.text
    second = client.post(f"/api/confirmations/{confirmation_id}/approve")
    assert second.status_code == 409

    after = len(client.get(f"/api/sequences/{seq_id}").json()["tracks"])
    assert after == before + 1, "the tool ran more than once"


def test_rejecting_an_approved_confirmation_is_refused(seeded) -> None:
    client, ws, seq_id = seeded
    confirmation_id = _pending_confirmation(ws, seq_id)

    assert client.post(f"/api/confirmations/{confirmation_id}/approve").status_code == 200
    assert client.post(f"/api/confirmations/{confirmation_id}/reject").status_code == 409
