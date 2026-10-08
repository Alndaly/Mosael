"""「本会话始终允许」加一条,由后端在库里那一份上合并(智能体那一路 AGENT-16)。

此前界面读出整份白名单、加一条、PATCH 整份:几个工具调用同时等批时,两张卡几乎同时点「始终允许」,两次读到的是同一份,
后写的盖掉先写的 —— 用户点过的那一条丢了,下一张同样的卡照样来问。
"""

from __future__ import annotations

import threading

from app.core.db import SessionLocal
from app.db.models import AgentSession
from tests.test_agent_queue import _session
from tests.util import fresh_client


def test_同时加两条_两条都在() -> None:
    client = fresh_client()
    sid = _session(client)
    barrier = threading.Barrier(2)
    answers: list[int] = []

    def add(tool: str, permission: str) -> None:
        barrier.wait()
        answers.append(client.post(f"/api/agent/sessions/{sid}/allowances", json={"tool": tool, "permission": permission}).status_code)

    threads = [threading.Thread(target=add, args=one) for one in (("edit_note", "edit"), ("render_sequence", "render-cost"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert answers == [200, 200]
    with SessionLocal() as db:
        tools = {entry["tool"]: entry["permission"] for entry in db.get(AgentSession, sid).auto_allow_tools}
    assert tools == {"edit_note": "edit", "render_sequence": "render-cost"}, f"丢了一条:{tools}"


def test_加一条和整份替换同一套校验() -> None:
    client = fresh_client()
    sid = _session(client)
    assert client.post(f"/api/agent/sessions/{sid}/allowances", json={"tool": "run_host_code", "permission": "external"}).status_code == 422
    assert client.post(f"/api/agent/sessions/{sid}/allowances", json={"tool": "create_skill", "permission": "edit"}).status_code == 422
    first = client.post(f"/api/agent/sessions/{sid}/allowances", json={"tool": "run_workflow", "permission": "edit"})
    assert first.status_code == 200
    higher = client.post(f"/api/agent/sessions/{sid}/allowances", json={"tool": "run_workflow", "permission": "ai-cost"}).json()
    assert higher["auto_allow_tools"] == [{"tool": "run_workflow", "permission": "ai-cost"}], "同一个工具取最高那一档"
