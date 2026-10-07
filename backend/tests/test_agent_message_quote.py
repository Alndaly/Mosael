"""消息带着一段笔记摘录(笔记页的选区)发出去:落进 payload,气泡下面画一行可点的摘录,回看历史时也在。

模型读到的选区走隐藏上下文(context);这里存的是**给界面画的那一份** —— 哪篇笔记、标题、选中的原文、位置。
不存的话,事后翻对话只看得到一句「把这段改得口语一些」,不知道「这段」是哪段。
"""

from __future__ import annotations

import threading

import pytest

from app.ai.sidecar.pi_client import TurnResult
from app.domain.agent import host
from tests.test_agent_host import _configured
from tests.util import fresh_client

QUOTE = {"kind": "note", "note_id": "n1", "title": "宣传片周报", "text": "周二把脚本第二稿写完", "start": 42}


def _session(client) -> str:
    _configured(client)
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace}).json()["id"]


def test_带着摘录发出去_落进消息_回看时还在(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", lambda adapter, *, prompt, **_: TurnResult(text="好"))
    client = fresh_client()
    session_id = _session(client)

    sent = client.post(f"/api/agent/sessions/{session_id}/messages", json={
        "content": "把这段改得口语一些", "context": "用户选中了这一段……", "quote": QUOTE,
    })
    assert sent.status_code == 200, sent.text
    assert host.wait_for_idle_turns()

    user = client.get(f"/api/agent/sessions/{session_id}/messages").json()[0]
    assert user["role"] == "user"
    assert user["payload"]["quote"] == QUOTE
    assert user["content"] == "把这段改得口语一些", "摘录不拼进正文 —— 正文是用户说的那句话"


def test_排队的那条也带着摘录(monkeypatch) -> None:
    """一轮还在跑时发的消息先排队,稍后才跑 —— 摘录得跟着那条消息存下,而不是只在直发那条路上存。"""
    release = threading.Event()

    def slow_turn(adapter, *, prompt, **_):
        release.wait(5)
        return TurnResult(text="好")

    monkeypatch.setattr(host, "run_turn", slow_turn)
    client = fresh_client()
    session_id = _session(client)
    client.post(f"/api/agent/sessions/{session_id}/messages", json={"content": "先做这个"})

    queued = client.post(f"/api/agent/sessions/{session_id}/messages", json={"content": "再看看这段", "quote": QUOTE})
    assert queued.status_code == 200, queued.text
    assert queued.json()["payload"].get("queued") is True
    assert queued.json()["payload"]["quote"] == QUOTE
    release.set()
    assert host.wait_for_idle_turns()


@pytest.mark.parametrize("quote", [
    {**QUOTE, "kind": "asset"},
    {**QUOTE, "text": ""},
    {**QUOTE, "text": "字" * 2001},
    {**QUOTE, "note_id": ""},
])
def test_说不清的摘录不收(quote: dict) -> None:
    client = fresh_client()
    session_id = _session(client)
    refused = client.post(f"/api/agent/sessions/{session_id}/messages", json={"content": "看看", "quote": quote})
    assert refused.status_code == 422
