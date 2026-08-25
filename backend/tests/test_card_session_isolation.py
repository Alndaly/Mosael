"""选择卡**只在它自己那次对话里出现**。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

确认卡那一侧早就钉住了(tests/test_confirmations.py 的按会话筛选那条),这里补上选择卡 ——
它是新加的,而两者在界面上并排出现,漏一个的现象和漏另一个一模一样:另一次对话里蹦出一句
「你要哪一个」,而看的人根本不知道在说什么。

**选择卡没有"始终允许"这类自动通路**,所以它不会有确认卡那种更糟的第二层风险(一张属于
A 会话的卡被 B 的白名单自动批准)。但看错人这件事本身就够坏了。
"""

from __future__ import annotations

RATCHET = True

from tests.util import fresh_client

QUESTION = [{"question": "选哪个?", "options": [{"label": "甲"}, {"label": "乙"}]}]


def _setup(client) -> tuple[str, str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    a = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
    b = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
    return ws, a, b


def _ask(client, ws: str, session_id: str) -> str:
    return client.post(
        "/api/agent/questions", json={"workspace_id": ws, "session_id": session_id, "questions": QUESTION}
    ).json()["id"]


def _pending(client, session_id: str) -> list[str]:
    return [one["id"] for one in client.get(f"/api/agent/questions?session_id={session_id}").json()]


def test_只出现在自己那次对话里() -> None:
    client = fresh_client()
    ws, a, b = _setup(client)
    mine = _ask(client, ws, a)

    assert _pending(client, a) == [mine]
    assert _pending(client, b) == [], "B 会话看到了 A 的选择卡"


def test_两次对话各问各的_互不串() -> None:
    client = fresh_client()
    ws, a, b = _setup(client)
    qa, qb = _ask(client, ws, a), _ask(client, ws, b)

    assert _pending(client, a) == [qa]
    assert _pending(client, b) == [qb]


def test_答完就从待答里消失() -> None:
    """留着的话,同一个问题会在下一次轮询时又弹一遍。"""
    client = fresh_client()
    ws, a, _ = _setup(client)
    qid = _ask(client, ws, a)

    client.post(f"/api/agent/questions/{qid}/answer", json={"answers": {"选哪个?": ["甲"]}})
    assert _pending(client, a) == []


def test_跳过也从待答里消失() -> None:
    client = fresh_client()
    ws, a, _ = _setup(client)
    qid = _ask(client, ws, a)

    client.post(f"/api/agent/questions/{qid}/dismiss")
    assert _pending(client, a) == []


def test_没有自动回答那条路() -> None:
    """**这是选择卡和确认卡分成两张表的理由。**

    确认卡有「本会话始终允许」(按会话记的白名单,后端在开卡那一刻判定)。选择卡不该有任何
    对应物 —— 自动回答等于让模型自己编一个答案,而它问就是因为不知道。
    """
    import mcp_server
    from app.domain.agent import autopilot

    # ask_user 不在确认卡那套里 —— 进去就会被 auto_allow / bypass 覆盖到。
    assert "ask_user" not in mcp_server.CONFIRMATION_TOOLS
    # 自动放行的判定只认工具名,而问题不是工具调用 —— 它连进那个判定的资格都没有。
    assert not hasattr(autopilot, "auto_answer"), "autopilot 里长出了自动回答"
