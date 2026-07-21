"""Queue by default, steer on purpose.

These are two different things and only one of them can be the default. Queuing waits for the
whole reason-act loop to finish and then runs as its own turn — what a follow-up almost always
means. Steering cuts into the running loop and changes what the agent does next, which is
powerful and wrong to apply to every message someone happens to send early.

Every mid-turn message used to be steered, so several questions merged into one answer and
the earlier ones read as ignored.
"""

from __future__ import annotations

import time

from app.ai.agent import host
from app.ai.agent.adapters import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession
from tests.util import fresh_client


def _slow_turn(*args, **kwargs):
    time.sleep(0.8)
    return TurnResult(text="ok")


def _session(client):
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    return client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]


def _wait_idle(session_id: str, seconds: float = 8) -> str:
    deadline = time.time() + seconds
    while time.time() < deadline:
        with SessionLocal() as db:
            status = db.get(AgentSession, session_id).status
        if status != "running":
            return status
        time.sleep(0.05)
    return "running"


def test_a_mid_turn_message_is_queued_not_steered(monkeypatch) -> None:
    """The default must not touch the running turn."""
    steers: list[str] = []
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": steers.append(text) or True)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})

    assert steers == [], "the queued message was pushed into the running turn"
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{sid}/queue").json()] == ["two"]
    assert _wait_idle(sid) == "idle"


def test_a_queued_message_runs_as_its_own_turn_when_the_first_ends(monkeypatch) -> None:
    """The point of queuing: it gets answered on its own terms, not merged into the answer
    that was already in flight."""
    prompts: list[str] = []

    def record(*args, **kwargs):
        prompts.append(kwargs.get("prompt") or args[0] if args else kwargs.get("prompt"))
        time.sleep(0.3)
        return TurnResult(text="ok")

    monkeypatch.setattr(host, "run_turn", lambda *a, **kw: (prompts.append(kw["prompt"]), time.sleep(0.2), TurnResult(text="ok"))[-1])

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "three"})

    assert _wait_idle(sid) == "idle"
    assert prompts == ["one", "two", "three"], prompts
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []


def test_a_queued_message_keeps_hidden_context(monkeypatch) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(
        host,
        "run_turn",
        lambda *a, **kw: (prompts.append(kw["prompt"]), time.sleep(0.2), TurnResult(text="ok"))[-1],
    )

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "two", "context": "当前工作流 workflow_id=w1"},
    )

    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()
    assert [m["content"] for m in queued] == ["two"]
    assert _wait_idle(sid) == "idle"
    assert prompts == ["one", "当前工作流 workflow_id=w1\n\n用户消息:\ntwo"], prompts


def test_steering_is_opt_in_per_message(monkeypatch) -> None:
    steers: list[str] = []
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": steers.append(text) or True)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "改成竖屏", "context": "当前工作流 workflow_id=w1"},
    )
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    res = client.post(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}/steer")

    assert res.status_code == 200 and res.json() == {"steered": True}
    assert steers == ["当前工作流 workflow_id=w1\n\n用户消息:\n改成竖屏"]
    # It left the queue: steering it and then running it again would answer it twice.
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []
    assert _wait_idle(sid) == "idle"


def test_steering_when_the_turn_already_ended_leaves_it_queued(monkeypatch) -> None:
    """Reporting a failure the user cannot act on is worse than letting it run on its own."""
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": False)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    res = client.post(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}/steer")

    assert res.status_code == 200 and res.json() == {"steered": False}
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{sid}/queue").json()] == ["two"]
    assert _wait_idle(sid) == "idle"


def test_a_queued_message_can_be_withdrawn(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", _slow_turn)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    assert client.delete(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}").status_code == 200
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []
    assert _wait_idle(sid) == "idle"
    with SessionLocal() as db:
        assert db.get(AgentMessage, queued[0]["id"]) is None


def test_the_message_being_answered_is_not_in_the_queue(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []
    assert _wait_idle(sid) == "idle"


def test_nothing_is_queued_when_idle() -> None:
    client = fresh_client()
    sid = _session(client)
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []


def test_the_transcript_interleaves_questions_and_answers(monkeypatch) -> None:
    """A queued message must land in the transcript where it was SENT, not where it was typed.

    Messages are ordered by created_at, and a queued one is stamped the moment the user hits
    enter — long before the agent gets to it. Left at that timestamp it sorts ahead of the
    previous turn's answer, and the conversation reads as every question in a row followed by
    every answer in a row, which is exactly what it looked like.
    """
    monkeypatch.setattr(
        host,
        "run_turn",
        lambda *a, **kw: (time.sleep(0.2), TurnResult(text=f"答:{kw['prompt']}"))[-1],
    )

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "一"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "二"})
    assert _wait_idle(sid) == "idle"

    transcript = [(m["role"], m["content"]) for m in client.get(f"/api/agent/sessions/{sid}/messages").json()]

    assert transcript == [
        ("user", "一"),
        ("assistant", "答:一"),
        ("user", "二"),
        ("assistant", "答:二"),
    ], transcript


def test_a_steered_message_also_lands_at_the_moment_it_was_sent(monkeypatch) -> None:
    """Same rule for the other path: it joins the conversation when it is cut in."""
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": True)

    client = fresh_client()
    sid = _session(client)
    first = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "一"}).json()
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "改一下"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()
    client.post(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}/steer")

    with SessionLocal() as db:
        steered = db.get(AgentMessage, queued[0]["id"])
        original = db.get(AgentMessage, first["id"])
        assert steered.created_at >= original.created_at
        assert not (steered.payload or {}).get("queued")
    assert _wait_idle(sid) == "idle"
