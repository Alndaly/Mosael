"""Messages queued behind a running answer, and withdrawing one.

A counter saying "1 queued" is not a queue — you cannot see what is in it or take it back.
The interesting part is the withdrawal: the message was already handed to pi, so deleting the
row leaves the model still acting on it. pi can clear its queue but not remove one entry, so
the remaining messages are re-declared.
"""

from __future__ import annotations

import time

from app.ai.agent import host
from app.ai.agent.adapters import TurnResult
from tests.util import fresh_client


def _slow_turn(*args, **kwargs):
    time.sleep(1.5)
    return TurnResult(text="ok")


def _session(client):
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    return client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]


def test_a_queued_message_is_listed_but_the_answered_one_is_not(monkeypatch) -> None:
    """The turn's own prompt is not queued — it is what is being answered right now."""
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": True)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "three"})

    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    assert [m["content"] for m in queued] == ["two", "three"]


def test_nothing_is_queued_when_no_turn_is_running() -> None:
    client = fresh_client()
    sid = _session(client)
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []


def test_withdrawing_resends_the_rest_to_the_model(monkeypatch) -> None:
    """Deleting the row is not enough: pi already holds the message."""
    declared: list[list[str]] = []
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": True)
    monkeypatch.setattr(host, "set_turn_queue", lambda sid, prompts: declared.append(list(prompts)) or True)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "three"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    res = client.delete(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}")

    assert res.status_code == 200, res.text
    assert declared == [["three"]], declared
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{sid}/queue").json()] == ["three"]


def test_the_message_being_answered_cannot_be_withdrawn(monkeypatch) -> None:
    """It is already in the model's hands and half-answered; pretending otherwise would show
    a cancel that does nothing."""
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": True)

    client = fresh_client()
    sid = _session(client)
    first = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"}).json()
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})

    res = client.delete(f"/api/agent/sessions/{sid}/queue/{first['id']}")

    assert res.status_code == 409
    assert "撤回" in res.json()["detail"]


def test_withdrawing_an_unknown_message_is_refused() -> None:
    client = fresh_client()
    sid = _session(client)
    assert client.delete(f"/api/agent/sessions/{sid}/queue/nope").status_code == 409
