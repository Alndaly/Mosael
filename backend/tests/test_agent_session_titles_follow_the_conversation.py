"""对话的名字照实际聊的内容起(维护者 2026-10-07 对 ADR 0044 的修订,见 domain/agent/titles)。

第一句话发出去时名字先是那一句;第一轮**成功的**回答落库之后,用这段对话自己的模型起一个短名字写回去。人起的名字永远不碰
(改过名的不起;起名回来时人刚改了名,改名赢);起不出来就停在第一句话那里,不重试;只起这一次。
"""

from __future__ import annotations

import threading
import time

from app.ai.sidecar.pi_client import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentSession
from app.domain.agent import host, titles
from tests.test_agent_host import _configured
from tests.util import fresh_client

FIRST = "帮我把宣传片脚本第二段改短一点"


def _session(client) -> str:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": {"kind": "studio"}}).json()["id"]


def _named(session_id: str) -> tuple[str, str]:
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        return session.title, session.title_source


def _until(condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "等不到"
        time.sleep(0.02)


class Namer:
    """顶替那一次起名的模型调用:记下问了什么,可以拦着不放(看起名回来之前是什么样)、可以失败。"""

    def __init__(self, answer: str = "「宣传片脚本第二段改短。」", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.asked: list[list[dict[str, str]]] = []
        self.gate = threading.Event()
        self.gate.set()

    def __call__(self, target, messages, *, workspace_id: str, session_id: str) -> str:
        self.asked.append(messages)
        self.gate.wait(5)
        if self.fail:
            raise RuntimeError("model unreachable")
        return self.answer


def _talk(monkeypatch, namer: Namer, *, configured: bool = True):
    monkeypatch.setattr(host, "run_turn", lambda adapter, *, prompt, **_: TurnResult(text="好的,第二段我改成了三句话。"))
    monkeypatch.setattr(titles, "_ask", namer)
    client = fresh_client()
    if configured:
        _configured(client)
    return client, _session(client)


def test_第一轮答完照聊的内容起名_起好之前是第一句话_只起这一次(monkeypatch) -> None:
    namer = Namer()
    namer.gate.clear()
    client, session = _talk(monkeypatch, namer)

    assert client.post(f"/api/agent/sessions/{session}/messages", json={"content": FIRST}).status_code == 200
    _until(lambda: namer.asked)
    assert _named(session) == (FIRST, "auto"), "起好之前,名字是第一句话"
    namer.gate.set()
    assert host.wait_for_idle_turns()
    assert _named(session) == ("宣传片脚本第二段改短", "generated"), "引号、句号去掉"
    asked = namer.asked[0][-1]["content"]
    assert FIRST in asked and "第二段我改成了三句话" in asked, "看的是这一问一答"
    assert client.get(f"/api/agent/sessions/{session}").json()["title"] == "宣传片脚本第二段改短"

    client.post(f"/api/agent/sessions/{session}/messages", json={"content": "再短一点"})
    assert host.wait_for_idle_turns()
    assert len(namer.asked) == 1, "话题变了也不再改名"


def test_人改过的名字不碰_起名回来时人刚好改了名_改名赢(monkeypatch) -> None:
    namer = Namer()
    namer.gate.clear()
    client, session = _talk(monkeypatch, namer)
    client.post(f"/api/agent/sessions/{session}/messages", json={"content": FIRST})
    _until(lambda: namer.asked)
    assert client.patch(f"/api/agent/sessions/{session}", json={"title": "我起的名字"}).status_code == 200
    namer.gate.set()
    assert host.wait_for_idle_turns()
    assert _named(session) == ("我起的名字", "manual")


def test_一开始就改过名的_第一句话不当名字_也不起名(monkeypatch) -> None:
    namer = Namer()
    client, session = _talk(monkeypatch, namer)
    client.patch(f"/api/agent/sessions/{session}", json={"title": "客户 A 的片子"})
    client.post(f"/api/agent/sessions/{session}/messages", json={"content": FIRST})
    assert host.wait_for_idle_turns()
    assert _named(session) == ("客户 A 的片子", "manual")
    assert namer.asked == []


def test_起不出来就停在第一句话_下一轮也不再试(monkeypatch) -> None:
    namer = Namer(fail=True)
    client, session = _talk(monkeypatch, namer)
    client.post(f"/api/agent/sessions/{session}/messages", json={"content": FIRST})
    assert host.wait_for_idle_turns()
    assert _named(session) == (FIRST, "auto")
    client.post(f"/api/agent/sessions/{session}/messages", json={"content": "再短一点"})
    assert host.wait_for_idle_turns()
    assert len(namer.asked) == 1


def test_回来的是空的_也停在第一句话(monkeypatch) -> None:
    namer = Namer(answer="「」。")
    client, session = _talk(monkeypatch, namer)
    client.post(f"/api/agent/sessions/{session}/messages", json={"content": FIRST})
    assert host.wait_for_idle_turns()
    assert _named(session) == (FIRST, "auto")


def test_没有对话模型就不起(monkeypatch) -> None:
    namer = Namer()
    client, session = _talk(monkeypatch, namer, configured=False)
    client.post(f"/api/agent/sessions/{session}/messages", json={"content": FIRST})
    assert host.wait_for_idle_turns()
    assert namer.asked == []
    assert _named(session) == (FIRST, "auto")


def test_起名的规整() -> None:
    assert titles.clean("标题:「宣传片脚本修改」。\n多余的一行") == "宣传片脚本修改"
    assert titles.clean('Title: "Trim the second paragraph."') == "Trim the second paragraph"
    assert titles.clean("   ") == ""
    assert len(titles.clean("长" * 100)) == 40
