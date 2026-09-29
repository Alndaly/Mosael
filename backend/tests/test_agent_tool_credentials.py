"""一次工具调用不该在库里留下一个永不过期的全权凭据。

`AuthSession` 没有过期列。智能体的每轮对话曾经都留下一个(见 `host.py` 里那段撤销注释),那条
已经修了 —— 但工具通道又把它按**每次工具调用**的频次长了回来:`/api/agent/tools/{name}` 每次
都铸一个新令牌给工具体回连用,`finally` 里只重置了 contextvar,行没人删。一次十步的任务就是
十个永久凭据,而它们和登录会话是同一张表、同一种权力。

工具体拿到的是一份同一个人、只活这一次调用的令牌,调用结束就撤掉 —— 不用调用方那份,因为交给
sidecar 的服务令牌只准用在工具通道上。这些用例钉住:调用之后行数不增,而绑给工具体的那个令牌确实认得出调用方本人。

用例不让回环真的发出去(整个套件都是这么做的:monkeypatch 掉 `mcp_server` 的 HTTP 助手)。
不这么做的话,请求会打到开发机上**真在跑的**那个后端 —— 测试从此依赖有没有人开着 8800。
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


#: 工具体回连那一刻,它手上的令牌认出的是谁(调用结束令牌就撤了,之后再查不到)。
seen_users: list[str] = []


def _user_id_of(token: str) -> str:
    with SessionLocal() as db:
        return find_session(db, token).user_id


def _capture_token(monkeypatch) -> list[str]:
    """拦下工具体的回连,记下它当时绑着的令牌和那一刻它认出的人。"""
    seen: list[str] = []
    seen_users.clear()

    def fake_get(path: str, params=None):
        token = mcp_server._API_TOKEN.get()
        seen.append(token)
        seen_users.append(_user_id_of(token))
        return []

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    # 工具正逐个改成直接调领域、不再回连;这里用一个临时的「还在回连」的工具,考的是回连这套机制本身,
    # 不随哪个具体工具先迁移而失效。等回连整个删掉,这条测试连同那份短期令牌一起删。
    monkeypatch.setattr(
        mcp_server, "probe_loopback", lambda workspace_id="": mcp_server._get("/api/probe", {"workspace_id": workspace_id}),
        raising=False,
    )
    return seen


def test_tool_calls_do_not_accumulate_credentials(monkeypatch) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _capture_token(monkeypatch)
    before = _auth_rows()

    for _ in range(3):
        response = client.post(
            "/api/agent/tools/probe_loopback",
            json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
        )
        assert response.status_code == 200, response.text

    assert _auth_rows() == before, "每次工具调用都在 auth_sessions 里留下了一行"


def test_the_tool_body_gets_a_credential_that_resolves_to_the_caller(monkeypatch) -> None:
    """行数不增不能靠"把工具调用弄坏"换来:工具体拿到的必须是一个真能认出调用方的令牌。

    它**不是**调用方带进来的那份:交给 sidecar 的服务令牌只准用在工具通道上(core/security.SERVICE_PATH_PREFIXES),
    工具体回连的却是任意 REST。所以是一份同一个人的、只活这一次调用的令牌,调用结束就撤掉。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    seen = _capture_token(monkeypatch)

    response = client.post(
        "/api/agent/tools/probe_loopback",
        json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
    )

    assert response.status_code == 200, response.text
    assert len(seen) == 1 and seen[0], "工具体没有拿到任何令牌"
    caller_token = client.headers["Authorization"].removeprefix("Bearer ")
    assert seen[0] != caller_token, "调用方的凭据不该被原样交给工具体"
    assert seen_users and seen_users[0] == _user_id_of(caller_token), "工具体认出的不是调用方这个人"
    with SessionLocal() as db:
        assert find_session(db, seen[0]) is None, "调用结束之后这份令牌还在"


def test_the_callers_own_session_survives_the_call(monkeypatch) -> None:
    """复用调用方凭据不等于可以动它 —— 调用完人还得是登录着的。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _capture_token(monkeypatch)

    client.post(
        "/api/agent/tools/probe_loopback",
        json={"arguments": {"workspace_id": workspace["id"]}, "requested_by": "test"},
    )

    assert client.get("/api/workspaces").status_code == 200
