"""跨会话记忆与任务计划。

记忆和知识库的差别全在"要不要检索":记忆每轮都注入,所以每一条都是**每轮都要付的成本**,
上限与去重不是洁癖而是预算问题。计划则只有一条硬约束:同时只能有一步在做 —— 否则
"现在在做什么"这个它唯一要回答的问题就没有答案了。
"""

from __future__ import annotations

import pytest

from app.domain.agent import memory as agent_memory
from app.domain.agent import plan as agent_plan
from app.core.db import SessionLocal
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_记忆每轮注入且用户写的排在前面() -> None:
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        agent_memory.remember(db, ws, "智能体记的一条", source="agent")
        agent_memory.remember(db, ws, "用户写的一条", source="user")
        db.commit()
        prompt = agent_memory.memory_prompt(db, ws)
    assert "【长期记忆】" in prompt
    # 用户写的在前:注入被截断时先保住人明确写下的那几条。
    assert prompt.index("用户写的一条") < prompt.index("智能体记的一条")


def test_没有记忆时不留空标题() -> None:
    """空标题等于告诉模型"这里本该有东西",它会开始猜。"""
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        assert agent_memory.memory_prompt(db, ws) == ""


def test_同一条不重复记() -> None:
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        first = agent_memory.remember(db, ws, "成片统一竖屏")
        again = agent_memory.remember(db, ws, "成片统一竖屏")
        db.commit()
        assert first.id == again.id
        assert len(agent_memory.list_memories(db, ws)) == 1


def test_注入总量封顶() -> None:
    """记忆是每轮都付的固定开销,而用户看不到这笔账。宁可漏掉最旧的几条。"""
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        for i in range(60):
            agent_memory.remember(db, ws, f"第 {i} 条约定" + "x" * 400)
        db.commit()
        prompt = agent_memory.memory_prompt(db, ws)
    assert len(prompt) < agent_memory.MAX_PROMPT_CHARS + 500


def test_项目级记忆只在该项目里注入() -> None:
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    other = client.post("/api/projects", json={"workspace_id": ws, "name": "P2"}).json()
    with SessionLocal() as db:
        agent_memory.remember(db, ws, "这个项目的片头是 intro.mp4", project_id=project["id"])
        agent_memory.remember(db, ws, "工作区通用约定")
        db.commit()
        assert "intro.mp4" in agent_memory.memory_prompt(db, ws, project["id"])
        assert "intro.mp4" not in agent_memory.memory_prompt(db, ws, other["id"])
        assert "intro.mp4" not in agent_memory.memory_prompt(db, ws)
        # 工作区级的两边都在
        assert "工作区通用约定" in agent_memory.memory_prompt(db, ws, other["id"])


def test_记忆接口全流程() -> None:
    client = fresh_client()
    ws = _workspace(client)
    created = client.post("/api/agent/memories", json={"workspace_id": ws, "content": "别用红色"}).json()
    assert created["source"] == "user"
    rows = client.get(f"/api/agent/memories?workspace_id={ws}").json()
    assert [row["content"] for row in rows] == ["别用红色"]
    patched = client.patch(f"/api/agent/memories/{created['id']}", json={"content": "别用纯红"}).json()
    assert patched["content"] == "别用纯红"
    assert client.delete(f"/api/agent/memories/{created['id']}").status_code == 204
    assert client.get(f"/api/agent/memories?workspace_id={ws}").json() == []


def test_单条过长被拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    resp = client.post("/api/agent/memories", json={"workspace_id": ws, "content": "x" * 900})
    assert resp.status_code == 422


def test_计划同时只有一步在做() -> None:
    """允许多步并行的话,"现在在做什么"就没有答案了,而这正是这份列表存在的理由。"""
    steps = agent_plan.normalize(
        [
            {"step": "看素材", "status": "done"},
            {"step": "拼时间线", "status": "in_progress"},
            {"step": "导出", "status": "in_progress"},
        ]
    )
    assert [step["status"] for step in steps] == ["done", "in_progress", "pending"]


def test_计划接受纯字符串数组() -> None:
    """模型未必每次都带 status。拒绝一个语义完全清楚的输入,只会让它多烧几轮。"""
    steps = agent_plan.normalize(["先查资料", "再写脚本"])
    assert steps == [
        {"step": "先查资料", "status": "pending"},
        {"step": "再写脚本", "status": "pending"},
    ]


def test_计划非法输入被拒() -> None:
    with pytest.raises(ValueError):
        agent_plan.normalize([])
    with pytest.raises(ValueError):
        agent_plan.normalize("不是数组")


def test_计划落到会话并随详情返回() -> None:
    client = fresh_client()
    ws = _workspace(client)
    session = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()
    assert session["plan"] is None
    updated = client.put(
        f"/api/agent/sessions/{session['id']}/plan",
        json={"steps": [{"step": "第一步", "status": "in_progress"}, "第二步"]},
    ).json()
    assert updated["plan"] == [
        {"step": "第一步", "status": "in_progress"},
        {"step": "第二步", "status": "pending"},
    ]
    assert client.get(f"/api/agent/sessions/{session['id']}").json()["plan"][0]["step"] == "第一步"


def test_空数组清空计划() -> None:
    """做完了要能收起来。没有出口的话,一份做完的计划会一直挂在面板上,
    而"还剩几步"是它唯一要回答的问题。"""
    client = fresh_client()
    ws = _workspace(client)
    session = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()
    client.put(f"/api/agent/sessions/{session['id']}/plan", json={"steps": ["一步"]})
    cleared = client.put(f"/api/agent/sessions/{session['id']}/plan", json={"steps": []}).json()
    assert cleared["plan"] is None
