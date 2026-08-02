"""一次工具调用不该在库里留下一个永不过期的全权凭据。

`AuthSession` 没有过期列。智能体的每轮对话曾经都留下一个(见 `host.py` 里那段撤销注释),那条
已经修了 —— 但工具通道又把它按**每次工具调用**的频次长了回来:`/api/agent/tools/{name}` 每次
都铸一个新令牌给工具体回连用,`finally` 里只重置了 contextvar,行没人删。一次十步的任务就是
十个永久凭据,而它们和登录会话是同一张表、同一种权力。

工具体需要的是「调用方自己的凭据」—— 那个凭据**已经在请求头里**了,再铸一个只是多一份没人
回收的密钥。这些用例钉住:调用之后行数不增,而绑给工具体的那个令牌确实认得出调用方本人。

用例不让回环真的发出去(整个套件都是这么做的:monkeypatch 掉 `mcp_server` 的 HTTP 助手)。
不这么做的话,请求会打到开发机上**真在跑的**那个后端 —— 测试从此依赖有没有人开着 8800。
"""

from __future__ import annotations

import mcp_server

from app.core.db import SessionLocal
from app.db.models import AuthSession
from tests.util import fresh_client


def _auth_rows() -> int:
    with SessionLocal() as db:
        return db.query(AuthSession).count()


def _capture_token(monkeypatch) -> list[str]:
    """拦下工具体的回连,记下它当时绑着的令牌。"""
    seen: list[str] = []

    def fake_get(path: str, params=None):
        seen.append(mcp_server._API_TOKEN.get())
        return []

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    return seen


def test_tool_calls_do_not_accumulate_credentials(monkeypatch) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _capture_token(monkeypatch)
    before = _auth_rows()

    for _ in range(3):
        response = client.post(
            "/api/agent/tools/list_projects",
            json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
        )
        assert response.status_code == 200, response.text

    assert _auth_rows() == before, "每次工具调用都在 auth_sessions 里留下了一行"


def test_the_tool_body_gets_a_credential_that_resolves_to_the_caller(monkeypatch) -> None:
    """行数不增不能靠"把工具调用弄坏"换来:工具体拿到的必须是一个真能认出调用方的令牌。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    seen = _capture_token(monkeypatch)

    response = client.post(
        "/api/agent/tools/list_projects",
        json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
    )

    assert response.status_code == 200, response.text
    assert len(seen) == 1 and seen[0], "工具体没有拿到任何令牌"
    caller_token = client.headers["Authorization"].removeprefix("Bearer ")
    assert seen[0] == caller_token, "工具体拿的不是调用方自己的凭据"
    with SessionLocal() as db:
        assert db.get(AuthSession, seen[0]) is not None, "这个令牌在库里不存在,回连会 401"


def test_the_callers_own_session_survives_the_call(monkeypatch) -> None:
    """复用调用方凭据不等于可以动它 —— 调用完人还得是登录着的。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _capture_token(monkeypatch)

    client.post(
        "/api/agent/tools/list_projects",
        json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
    )

    assert client.get("/api/workspaces").status_code == 200
