"""第三方登录:身份映射与端点形态(令牌交换是纯网络调用,不在测试范围)。"""

from __future__ import annotations

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
