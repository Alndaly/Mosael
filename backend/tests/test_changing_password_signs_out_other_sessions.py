"""改密码把别处的登录都踢下线,当前这一份留着(SEC-6)。

察觉异常登录的人改密码,预期的是「别处都被踢下线」。此前只挡住了「再用旧密码登录」:已经攥着一份登录令牌的人
(30 天、活跃续期)照样进得来。智能体回合这类服务令牌不动 —— 撤了只会打断正在跑的那一轮。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import find_session, mint_service_session
from tests.util import PASSWORD, fresh_client, user_id


def _login(client, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": "tester", "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _me(client, token: str) -> int:
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code


def test_改密码之后_别处的登录失效_这一份照常用() -> None:
    client = fresh_client()
    current = client.headers["Authorization"].removeprefix("Bearer ")
    elsewhere = _login(client, PASSWORD)
    with SessionLocal() as db:
        service = mint_service_session(db, user_id())

    changed = client.post("/api/auth/me/password", json={"current_password": PASSWORD, "new_password": "new-secret"})

    assert changed.status_code == 200, changed.text
    assert changed.json()["signed_out"] >= 1
    assert _me(client, elsewhere) == 401, "别处的登录还在 —— 偷到的令牌改了密码也照样能用"
    assert _me(client, current) == 200, "改密码的这一份不该被踢出去"
    with SessionLocal() as db:
        assert find_session(db, service) is not None, "服务令牌跟着一次操作走,不打断"
    assert _login(client, "new-secret")


def test_旧密码不对_什么都不撤() -> None:
    client = fresh_client()
    elsewhere = _login(client, PASSWORD)

    refused = client.post("/api/auth/me/password", json={"current_password": "wrong", "new_password": "x-secret"})

    assert refused.status_code == 401
    assert _me(client, elsewhere) == 200
