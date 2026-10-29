"""设备令牌(ADR 0088 第 1 步):会话换令牌、令牌认人、吊销、库里只存哈希、cookie 进不了网关。"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import api, build_app, login, rows, scalar, signed_in


def issue(client: TestClient, name: str = "Alice 的 MacBook") -> dict:
    response = client.post(api("/device-tokens"), json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def test_a_signed_in_session_exchanges_for_a_token_that_the_gateway_recognises(client):
    signed_in(client)
    issued = issue(client)
    secret = issued["secret"]
    assert secret.startswith("mct_") and len(secret) >= 4 + 43
    assert issued["token"]["name"] == "Alice 的 MacBook"
    assert "token_hash" not in issued["token"]

    # 网关不认 cookie:去掉会话,只带令牌也能认出是谁。
    client.cookies.clear()
    me = client.get(api("/gateway/me"), headers=bearer(secret))
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == "alice@example.com"
    assert me.json()["device"]["id"] == issued["token"]["id"]
    assert me.json()["device"]["last_used_at"] is not None


def test_only_the_digest_is_stored(client, db_path):
    signed_in(client)
    secret = issue(client)["secret"]
    stored = scalar(db_path, "SELECT token_hash FROM cloud_device_tokens")
    assert stored == hashlib.sha256(secret.encode()).hexdigest()
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    assert secret not in dump


def test_issuing_needs_a_session(client):
    response = client.post(api("/device-tokens"), json={"name": "x"})
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"


def test_the_gateway_ignores_browser_sessions_and_bad_tokens(client):
    signed_in(client)
    assert client.get(api("/gateway/me")).status_code == 401
    for header in ("Bearer mct_not-a-real-token", "Bearer ", "Basic abc", "mct_x"):
        response = client.get(api("/gateway/me"), headers={"Authorization": header})
        assert response.status_code == 401, header
        assert response.json()["error"] == "device_token_invalid"


def test_device_name_is_validated(client):
    signed_in(client)
    for name in ("   ", "x" * 81):
        response = client.post(api("/device-tokens"), json={"name": name})
        assert response.status_code == 400, name
        assert response.json()["error"] == "device_name_invalid"


def test_list_and_revoke_from_the_account(client):
    signed_in(client)
    first = issue(client, "Mac")
    second = issue(client, "PC")
    listed = client.get(api("/device-tokens")).json()["tokens"]
    assert [token["name"] for token in listed] == ["PC", "Mac"]
    assert all("secret" not in token for token in listed)

    assert client.delete(api(f"/device-tokens/{first['token']['id']}")).status_code == 204
    assert client.get(api("/gateway/me"), headers=bearer(first["secret"])).status_code == 401
    assert client.get(api("/gateway/me"), headers=bearer(second["secret"])).status_code == 200


def test_a_device_can_revoke_itself(client):
    signed_in(client)
    secret = issue(client)["secret"]
    client.cookies.clear()
    assert client.delete(api("/device-tokens/current"), headers=bearer(secret)).status_code == 204
    assert client.get(api("/gateway/me"), headers=bearer(secret)).status_code == 401


def test_someone_elses_token_id_is_not_found(config, sender):
    app = build_app(config, sender)
    alice, bob = TestClient(app), TestClient(app)
    try:
        signed_in(alice)
        token_id = issue(alice)["token"]["id"]
        signed_in(bob, email="bob@example.com")
        response = bob.delete(api(f"/device-tokens/{token_id}"))
        assert response.status_code == 404
        assert response.json()["error"] == "device_token_not_found"
        assert len(alice.get(api("/device-tokens")).json()["tokens"]) == 1
    finally:
        alice.close()
        bob.close()


def test_deleting_the_account_revokes_its_tokens(client, db_path):
    signed_in(client)
    secret = issue(client)["secret"]
    assert client.delete(api("/me")).status_code == 204
    assert rows(db_path, "SELECT id FROM cloud_device_tokens") == []
    assert client.get(api("/gateway/me"), headers=bearer(secret)).status_code == 401


def test_last_used_is_refreshed_at_minute_granularity(client, app):
    from cloud.domain import device_tokens

    signed_in(client)
    secret = issue(client)["secret"]
    with app.state.db.session() as db:
        token = device_tokens.authenticate(db, secret)
        first = token.last_used_at
        assert device_tokens.authenticate(db, secret, at=first + timedelta(seconds=30)).last_used_at == first
        later = first + timedelta(minutes=2)
        assert device_tokens.authenticate(db, secret, at=later).last_used_at == later


def test_account_endpoints_accept_the_token_and_never_fall_back_to_the_cookie(client):
    signed_in(client)
    secret = issue(client)["secret"]
    # 只带令牌:账号接口认得出是谁。
    client.cookies.clear()
    assert client.get(api("/me"), headers=bearer(secret)).json()["user"]["email"] == "alice@example.com"
    # 带着一枚失效的令牌,即使 cookie 还有效,也按令牌失效回 —— 桌面端靠这一句清掉本地登录。
    login(client)
    response = client.get(api("/me"), headers=bearer("mct_revoked"))
    assert response.status_code == 401
    assert response.json()["error"] == "device_token_invalid"


def test_public_reads_treat_a_bad_token_as_a_guest(client):
    response = client.get(api("/shares"), headers=bearer("mct_revoked"))
    assert response.status_code == 200


def test_a_browser_session_cannot_revoke_a_current_device(client):
    signed_in(client)
    issue(client)
    response = client.delete(api("/device-tokens/current"))
    assert response.status_code == 401
    assert response.json()["error"] == "device_token_invalid"
