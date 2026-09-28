"""第三方登录:身份映射与端点形态(令牌交换是纯网络调用,不在测试范围)。"""

from __future__ import annotations

import httpx

from app.api.routes.oauth import _find_or_create_user
from app.core.db import SessionLocal
from tests.util import fresh_client


def test_providers_empty_without_config() -> None:
    client = fresh_client()
    assert client.get("/api/auth/oauth/providers").json() == {"providers": []}
    # 未配置的提供方:start 直接 404,不产生 pending 槽
    assert client.post("/api/auth/oauth/google/start").status_code == 404


def test_find_or_create_user_binds_identity_and_dedupes_username() -> None:
    fresh_client()  # 初始化干净库
    with SessionLocal() as db:
        first = _find_or_create_user(db, provider="google", subject="sub-1", email="kinda@example.com", display_name="Kinda")
        db.commit()
        assert first.username == "kinda"
        assert first.display_name == "Kinda"

        # 同一身份再来 → 命中同一账号,不新建
        again = _find_or_create_user(db, provider="google", subject="sub-1", email="kinda@example.com", display_name="")
        assert again.id == first.id

        # 邮箱局部名撞车的另一个身份 → 用户名去重加后缀
        second = _find_or_create_user(db, provider="apple", subject="sub-2", email="kinda@icloud.com", display_name="")
        db.commit()
        assert second.id != first.id
        assert second.username == "kinda2"


def test_oauth_user_cannot_password_login() -> None:
    client = fresh_client()
    with SessionLocal() as db:
        user = _find_or_create_user(db, provider="google", subject="sub-9", email="p@example.com", display_name="")
        db.commit()
        username = user.username
    # 第三方账号没有本地口令:任何密码都进不来(401 = 口令不对;422 = 短用户名/口令被 schema 拦下)
    assert client.post("/api/auth/login", json={"username": username, "password": ""}).status_code in (401, 422)
    assert client.post("/api/auth/login", json={"username": username, "password": "guess-anything"}).status_code in (401, 422)


def test_密码账号报的登录方式是空的() -> None:
    client = fresh_client()
    assert client.get("/api/auth/me").json()["oauth_providers"] == []


def test_第三方登录取到的票和_me_是同一个形状并且报得出是谁家的(monkeypatch) -> None:
    """账号菜单据 oauth_providers 写「通过 Google 登录」。取票那一刻落座用的 user 若少了这一格,
    刚登进来的人看到的会是「本地账号」,要重启一次才改口。"""
    from app.api.routes import oauth
    from app.core.config import settings

    client = fresh_client()
    monkeypatch.setattr(settings, "google_client_id", "client")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(oauth, "_exchange_code", lambda *_: {"sub": "g-42", "email": "ada@example.com", "name": "Ada"})

    started = client.post("/api/auth/oauth/google/start").json()
    state = dict(httpx.URL(started["url"]).params)["state"]
    assert client.get("/api/auth/oauth/google/callback", params={"state": state, "code": "c"}).status_code == 200
    ticket = client.get(f"/api/auth/oauth/pending/{started['pending_id']}").json()

    assert ticket["status"] == "done"
    assert ticket["user"]["oauth_providers"] == ["google"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ticket['token']}"}).json()
    assert me == ticket["user"]
