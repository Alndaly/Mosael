"""第三方登录(Google / Apple)要把回调页上的确认码填回应用,令牌才交出去(D56 / SEC-11)。

此前发起登录和完成登录没有绑在一起:谁都能开一次登录、拿到一条真的授权链接转给别人;对方点开、用自己的账号登录,
会话就落进发起人那一次登录里,被发起人轮询取走。现在回调页只显示一个确认码,令牌只交给在**发起的那个应用里**填对了码的人;
轮询从不交出令牌。
"""

from __future__ import annotations

import re

import httpx
import pytest

from app.core.db import SessionLocal
from app.db.models import OAuthIdentity
from tests.util import fresh_client


@pytest.fixture
def google(monkeypatch):
    from app.api.routes import oauth
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_client_id", "client")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(oauth, "_exchange_code", lambda *_: {"sub": "g-7", "email": "bo@example.com", "name": "Bo"})


def _start(client) -> tuple[str, str]:
    started = client.post("/api/auth/oauth/google/start").json()
    return started["pending_id"], dict(httpx.URL(started["url"]).params)["state"]


def _callback(client, state: str) -> str:
    """提供方回调(被登录的那个人的浏览器)。返回回调页上的确认码。"""
    page = client.get("/api/auth/oauth/google/callback", params={"state": state, "code": "c"})
    assert page.status_code == 200, page.text
    return re.search(r"data-confirm-code[^>]*>([A-Z0-9-]+)<", page.text).group(1)


def _identities() -> int:
    with SessionLocal() as db:
        return db.query(OAuthIdentity).count()


def test_回调之后轮询只说等确认_不交令牌(google) -> None:
    client = fresh_client()
    pending, state = _start(client)
    _callback(client, state)

    polled = client.get(f"/api/auth/oauth/pending/{pending}").json()

    assert polled == {"status": "confirm"}, "轮询交出了令牌:谁开的这次登录,谁就能取走别人的会话"
    assert _identities() == 0, "确认之前不该建号"


def test_填对回调页上的码才登进去_大小写和连字符不计较(google) -> None:
    client = fresh_client()
    pending, state = _start(client)
    code = _callback(client, state)

    done = client.post(f"/api/auth/oauth/pending/{pending}/confirm", json={"code": code.lower().replace("-", " ")}).json()

    assert done["status"] == "done" and done["token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {done['token']}"}).json()["display_name"] == "Bo"
    assert client.post(f"/api/auth/oauth/pending/{pending}/confirm", json={"code": code}).json() == {"status": "expired"}, \
        "一次性:取过一次就没了"


def test_发起人拿不到别人的会话_猜码猜满就作废(google) -> None:
    """钓鱼:发起人把授权链接转给别人,对方登录完,码在对方的浏览器里。发起人只能猜。"""
    attacker = fresh_client()
    pending, state = _start(attacker)
    _callback(attacker, state)  # 被钓鱼的人完成了登录;码只显示在他的浏览器里

    answers = [attacker.post(f"/api/auth/oauth/pending/{pending}/confirm", json={"code": "AAAAAA"}).json() for _ in range(5)]

    assert [one["status"] for one in answers] == ["wrong_code"] * 4 + ["error"]
    assert [one.get("attempts_left") for one in answers[:4]] == [4, 3, 2, 1]
    assert attacker.get(f"/api/auth/oauth/pending/{pending}").json() == {"status": "expired"}
    assert all("token" not in one for one in answers)
    assert _identities() == 0, "被钓鱼的人在这台部署上被建了号"


def test_回调页写明确认码和不是自己点的就关掉(google) -> None:
    client = fresh_client()
    _, state = _start(client)
    page = client.get("/api/auth/oauth/google/callback", params={"state": state, "code": "c"}, headers={"Accept-Language": "en"})
    assert re.search(r"data-confirm-code[^>]*>[A-Z0-9]{3}-[A-Z0-9]{3}<", page.text)
    assert "close this page" in page.text
