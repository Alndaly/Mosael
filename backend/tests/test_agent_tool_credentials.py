"""一次工具调用不该在库里留下任何凭据,工具体以**调用方本人**的身份跑。

`AuthSession` 没有过期列。工具通道此前每次调用都铸一个令牌给工具体回连本 API 用(先是永不撤销,
后来改成调用结束就撤)。工具改成进程内直接调领域用例之后,回连没有了,这一份令牌也就不存在了 ——
身份经上下文变量交给工具体(mcp_server.calling_as),落不到库里。

这些用例钉住:调用之后行数不增,工具体认出的正是调用方这个人,调用方自己的会话照样在。
"""

from __future__ import annotations

import mcp_server

from app.core.db import SessionLocal
from app.core.security import find_session
from app.db.models import AuthSession
from tests.util import fresh_client


def _auth_rows() -> int:
    with SessionLocal() as db:
        return db.query(AuthSession).count()


def _probe(monkeypatch) -> list[str]:
    """一个临时工具:记下它跑的那一刻「这次调用是谁」。"""
    seen: list[str] = []

    def probe_caller(workspace_id: str = "") -> dict:
        seen.append(mcp_server._CALLER_ID.get())
        return {}

    monkeypatch.setattr(mcp_server, "probe_caller", probe_caller, raising=False)
    return seen


def test_tool_calls_do_not_accumulate_credentials(monkeypatch) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    before = _auth_rows()

    for _ in range(3):
        response = client.post(
            "/api/agent/tools/list_projects",
            json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
        )
        assert response.status_code == 200, response.text

    assert _auth_rows() == before, "工具调用在 auth_sessions 里留下了行"


def test_the_tool_body_runs_as_the_caller(monkeypatch) -> None:
    client = fresh_client()
    seen = _probe(monkeypatch)

    response = client.post("/api/agent/tools/probe_caller", json={"arguments": {}, "requested_by": "test"})

    assert response.status_code == 200, response.text
    caller_token = client.headers["Authorization"].removeprefix("Bearer ")
    with SessionLocal() as db:
        assert seen == [find_session(db, caller_token).user_id], "工具体认出的不是调用方这个人"
    assert mcp_server._CALLER_ID.get() == "", "调用结束之后身份不该留在上下文里"


def test_the_callers_own_session_survives_the_call(monkeypatch) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()

    client.post(
        "/api/agent/tools/list_projects",
        json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
    )

    assert client.get("/api/workspaces").status_code == 200
