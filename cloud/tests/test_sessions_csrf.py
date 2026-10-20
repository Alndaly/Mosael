"""会话与 CSRF:HttpOnly + Secure + SameSite 的 cookie、不可猜的令牌、同源校验。"""

from __future__ import annotations

import hashlib
import sqlite3

from fastapi.testclient import TestClient

from cloud.config import CloudConfig
from conftest import PASSWORD, api, build_app, scalar, signup, signed_in


def cookie_header(response) -> str:
    return response.headers["set-cookie"]


def session_token(client) -> str:
    found = client.cookies.get("mosael_cloud_session")
    assert found, "登录后没有会话 cookie"
    return found


def test_session_cookie_is_httponly_samesite_lax_and_scoped(client):
    signed_in(client)
    response = client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
    header = cookie_header(response)
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Path=/api/cloud/v1" in header
    # 本地测试走 http,cookie_secure=False;Secure 那一条在下面单独验。
    assert "Secure" not in header


def test_secure_is_on_when_configured(tmp_path):
    config = CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=True,
    )
    app = build_app(config)
    client = TestClient(app)
    try:
        signup(client)
        response = client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
        assert "Secure" in cookie_header(response)
    finally:
        client.close()


def test_session_token_is_unpredictable_and_only_its_digest_is_stored(client, db_path):
    # 注册即登录,所以 signup 给的这一枚就是第一个会话 —— 库里此刻只有这一行。
    signup(client)
    first = session_token(client)
    assert len(first) >= 43, len(first)
    stored = scalar(db_path, "SELECT token_hash FROM cloud_sessions")
    assert stored == hashlib.sha256(first.encode()).hexdigest()
    assert first not in str(stored)
    # 原始令牌不该出现在库里的任何一张表。
    with sqlite3.connect(db_path) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            dump = "\n".join(str(row) for row in connection.execute(f"SELECT * FROM {table}"))
            assert first not in dump, f"原始会话令牌出现在 {table}"

    client.post(api("/logout"))
    client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
    assert session_token(client) != first


def test_logout_revokes_only_the_presented_session(client, app):
    other = TestClient(app)
    try:
        signed_in(client)
        signed_in(other, email="bob@example.com")
        assert client.post(api("/logout")).status_code == 204
        assert client.get(api("/me")).status_code == 401
        assert other.get(api("/me")).status_code == 200
    finally:
        other.close()


def test_expired_session_is_rejected(client, db_path):
    signed_in(client)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE cloud_sessions SET expires_at = '2000-01-01 00:00:00.000000'")
        connection.commit()
    response = client.get(api("/me"))
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"


def test_cross_site_login_is_refused_and_sets_no_cookie(client):
    response = client.post(
        api("/login"),
        json={"email": "alice@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "cross_site_request"
    assert response.json()["message"]["zh"] and response.json()["message"]["en"]
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_same_origin_login_is_allowed(client):
    signup(client)
    response = client.post(
        api("/login"),
        json={"email": "alice@example.com", "password": PASSWORD},
        headers={"Origin": "https://mosael.test"},
    )
    assert response.status_code == 200


def test_browser_fetch_metadata_marks_cross_site(client):
    response = client.post(
        api("/signup"),
        json={"email": "alice@example.com", "password": PASSWORD},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "cross_site_request"


def test_referer_is_checked_when_origin_is_absent(client):
    response = client.post(
        api("/signup"),
        json={"email": "alice@example.com", "password": PASSWORD},
        headers={"Referer": "https://evil.example/steal"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "cross_site_request"


def test_cross_site_logout_leaves_the_session_alive(client):
    signed_in(client)
    refused = client.post(api("/logout"), headers={"Origin": "https://evil.example"})
    assert refused.status_code == 403
    assert client.get(api("/me")).status_code == 200


def test_device_endpoints_do_not_depend_on_cookies(client):
    """桌面端没有浏览器 Origin,也不该被会话 cookie 的 CSRF 规则挡住。"""
    response = client.post(
        api("/device/code"),
        json={"device_name": "Mac"},
        headers={"Origin": "https://evil.example"},
    )
    # 这道闸只保护 cookie 认证的浏览器端点;设备码入口是给本机进程的。
    assert response.status_code == 200
