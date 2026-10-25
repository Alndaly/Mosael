"""ADR 0081 P3:回放证据落本机、可读、可清、删会话即删。"""

from __future__ import annotations

import base64
import io

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import AgentMessage
from app.domain.agent import replay as replay_store
from tests.util import fresh_client


def _png(width: int = 24, height: int = 16) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _session(client) -> str:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post(
        "/api/agent/sessions",
        json={"home": {"kind": "studio"}, "workspace_id": workspace, "title": "Replay"},
    ).json()["id"]


def test_evidence_is_stored_locally_and_served_through_the_session() -> None:
    client = fresh_client()
    session_id = _session(client)
    png = _png()
    result = replay_store.store_action_replay(
        session_id=session_id,
        replay_id="card-1",
        replay={
            "at": "2026-10-25T10:00:00Z",
            "action": {"kind": "type", "text": "hello"},
            "before": {"image": base64.b64encode(png).decode(), "width": 24, "height": 16},
            "after": {"image": base64.b64encode(png).decode(), "width": 24, "height": 16},
        },
        result={"windowNumber": 7, "pid": 42, "point": {"x": 10, "y": 20}},
    )
    assert result["replay"]["session_id"] == session_id
    assert result["replay"]["action"]["text"] == "hello"
    path = replay_store.image_path(session_id, "card-1", "before")
    assert path.is_file()
    assert path.is_relative_to(settings.data_dir)

    response = client.get(f"/api/agent/sessions/{session_id}/replay/card-1/before.png")
    assert response.status_code == 200
    assert response.content == png


def test_clear_removes_files_and_metadata() -> None:
    client = fresh_client()
    session_id = _session(client)
    replay_store.store_action_replay(
        session_id=session_id,
        replay_id="card-1",
        replay={
            "action": {"kind": "click"},
            "before": {"image": base64.b64encode(_png()).decode()},
            "after": {"image": base64.b64encode(_png()).decode()},
        },
        result={"windowNumber": 7},
    )
    with SessionLocal() as db:
        db.add(AgentMessage(
            session_id=session_id,
            role="assistant",
            content="",
            payload={"timeline": [{"type": "tool", "tool": {
                "id": "t1", "name": "computer_desktop_click", "status": "done",
                "result": {"windowNumber": 7, "replay": {"session_id": session_id, "replay_id": "card-1"}},
            }}]},
        ))
        db.commit()

    assert client.delete(f"/api/agent/sessions/{session_id}/replay").status_code == 204
    assert not replay_store.session_dir(session_id).exists()
    assert client.get(f"/api/agent/sessions/{session_id}/replay/card-1/before.png").status_code == 404
    with SessionLocal() as db:
        message = db.query(AgentMessage).filter(AgentMessage.session_id == session_id).one()
        assert "replay" not in message.payload["timeline"][0]["tool"]["result"]


def test_deleting_the_session_deletes_replay_files() -> None:
    client = fresh_client()
    session_id = _session(client)
    replay_store.store_action_replay(
        session_id=session_id,
        replay_id="card-1",
        replay={"action": {"kind": "click"}, "before": {"image": base64.b64encode(_png()).decode()}},
        result={"windowNumber": 7},
    )
    assert replay_store.session_dir(session_id).exists()
    assert client.delete(f"/api/agent/sessions/{session_id}").status_code == 204
    assert not replay_store.session_dir(session_id).exists()
