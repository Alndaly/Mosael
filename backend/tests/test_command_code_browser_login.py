"""Command Code 的浏览器登录:Studio 把 API Key POST 回本机回环服务。

它和别的订阅计划不同 —— 没有 pi Provider,流程在我们这儿(照它 CLI 的做法):起一个只监听回环的
一次性服务 → 打开 Studio → Studio 把 `{apiKey, state, …}` POST 回来 → 验一下 `/alpha/whoami` →
按 api_key 存进这条连接。

这条测试钉四件事:①回调真的被收下并交出一次;②state 对不上就拒(别让半路来的 POST 塞别人的 Key);
③Key 只交一次;④验不过的 Key 不会被存成"能用"。
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from app.domain.providers import command_code_login
from tests.util import fresh_client


@pytest.fixture(autouse=True)
def _clean_pending():
    command_code_login._store.items.clear()
    yield
    for entry in list(command_code_login._store.items.values()):
        command_code_login._close(entry.server)
    command_code_login._store.items.clear()


def _post_callback(url: str, payload: dict) -> int:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_studio_posts_the_key_back_and_it_is_handed_out_once() -> None:
    started = command_code_login.start("profile-1")
    url = started["url"]
    assert url.startswith(command_code_login.STUDIO_AUTH_URL)
    state = url.split("state=")[1]
    callback = url.split("callback=")[1].split("&")[0]
    # 只监听回环
    assert callback.startswith("http://127.0.0.1:")

    assert _post_callback(callback, {"apiKey": "cmd-abc123", "state": state, "userName": "kinda"}) == 200
    done = command_code_login.poll(started["pending_id"])
    assert done["status"] == "done"
    assert done["api_key"] == "cmd-abc123"
    assert done["user_name"] == "kinda"
    # 一次性:再问就没了
    assert command_code_login.poll(started["pending_id"])["status"] == "expired"


def test_a_callback_with_the_wrong_state_is_refused() -> None:
    started = command_code_login.start("profile-2")
    callback = started["url"].split("callback=")[1].split("&")[0]
    assert _post_callback(callback, {"apiKey": "cmd-evil", "state": "not-the-state"}) == 400
    state = command_code_login.poll(started["pending_id"])
    assert state["status"] == "error"
    assert "state" in state["error"]


def test_the_key_is_scrubbed_before_it_is_used() -> None:
    started = command_code_login.start("profile-3")
    state = started["url"].split("state=")[1]
    callback = started["url"].split("callback=")[1].split("&")[0]
    pasted = f"  {chr(27)}[200~cmd-with-brackets{chr(27)}[201~  "
    assert _post_callback(callback, {"apiKey": pasted, "state": state}) == 200
    assert command_code_login.poll(started["pending_id"])["api_key"] == "cmd-with-brackets"


class _Response:
    def __init__(self, status: int) -> None:
        self.status_code = status


class _Client:
    def __init__(self, status: int) -> None:
        self.status = status
        self.seen: list[dict] = []

    def get(self, url: str, headers: dict) -> _Response:
        self.seen.append({"url": url, "headers": headers})
        return _Response(self.status)


def test_the_key_is_validated_against_whoami() -> None:
    ok = _Client(200)
    command_code_login.validate_key("cmd-good", client=ok)
    assert ok.seen and ok.seen[0]["url"].endswith("/alpha/whoami")
    assert ok.seen[0]["headers"]["Authorization"] == "Bearer cmd-good"

    with pytest.raises(command_code_login.CommandCodeLoginError, match="无效"):
        command_code_login.validate_key("cmd-bad", client=_Client(401))
    with pytest.raises(command_code_login.CommandCodeLoginError):
        command_code_login.validate_key("", client=_Client(200))


def test_the_route_stores_the_key_after_validation(monkeypatch) -> None:
    """整条路由走一遍:发起 → Studio 回调 → 轮询 → 存成这条连接的 api_key。"""
    monkeypatch.setattr(command_code_login, "validate_key", lambda key, client=None: None)
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    profile = client.post(
        "/api/settings/providers",
        json={"workspace_id": workspace["id"], "vendor": "command-code", "name": "Command Code", "auth_type": "api_key"},
    ).json()

    started = client.post(f"/api/settings/providers/{profile['id']}/command-code/login")
    assert started.status_code == 200, started.text
    body = started.json()
    callback = body["url"].split("callback=")[1].split("&")[0]
    state = body["url"].split("state=")[1]

    waiting = client.get(f"/api/settings/providers/{profile['id']}/command-code/login/{body['login_id']}")
    assert waiting.json()["status"] == "waiting"

    assert _post_callback(callback, {"apiKey": "cmd-from-browser", "state": state}) == 200
    done = client.get(f"/api/settings/providers/{profile['id']}/command-code/login/{body['login_id']}")
    assert done.json()["status"] == "done", done.text

    # 存进去的是一把可用的 api_key(库里那一份;接口只回显掩码,不回传明文)。
    from app.core.db import SessionLocal
    from app.db.models import User
    from app.domain.providers import credentials as provider_credentials

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        stored = provider_credentials.get(db, profile["id"], user.id)
        assert stored is not None and stored.api_key == "cmd-from-browser"
        assert provider_credentials.key_hint(stored) != "cmd-from-browser"
