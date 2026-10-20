"""账号本身:注册、登录、/me、登出、删号;密码只以 argon2id 哈希落盘。"""

from __future__ import annotations

import argon2
import pytest

from conftest import PASSWORD, api, scalar, signup, signed_in


def test_signup_login_me_logout_round_trip(client, db_path):
    user = signup(client)
    assert user["email"] == "alice@example.com"
    # 注册这一步现在会验邮箱验证码,成功即视为已验证。
    assert user["email_verified_at"] is not None
    assert "password" not in str(user) and "hash" not in str(user)

    response = client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert "mosael_cloud_session=" in response.headers["set-cookie"]
    # 登录只发 cookie,不在 body 里发令牌(localStorage 那一套不用)。
    assert "token" not in response.json()

    me = client.get(api("/me"))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "alice@example.com"

    out = client.post(api("/logout"))
    assert out.status_code == 204
    assert client.get(api("/me")).status_code == 401


def test_password_is_stored_as_an_argon2_hash_we_can_verify_but_not_reverse(client, db_path):
    signup(client)
    stored = scalar(db_path, "SELECT password_hash FROM cloud_users")
    assert stored and stored.startswith("$argon2id$"), stored
    assert PASSWORD not in stored
    # 成熟库能验回去 —— 这正是"哈希对"的证明;从哈希推不回明文是 argon2 的前提。
    argon2.PasswordHasher().verify(stored, PASSWORD)
    with pytest.raises(argon2.exceptions.VerificationError):
        argon2.PasswordHasher().verify(stored, "not-the-password")


def test_duplicate_email_is_refused_case_insensitively(client):
    signup(client, email="Alice@Example.com")
    response = client.post(api("/signup"), json={"email": "alice@example.com", "password": PASSWORD})
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "email_taken"
    assert body["message"]["zh"] and body["message"]["en"]


def test_invalid_email_and_short_password_have_human_messages(client):
    bad_email = client.post(api("/signup"), json={"email": "not-an-email", "password": PASSWORD})
    assert bad_email.status_code == 422
    assert bad_email.json()["error"] == "invalid_request"
    assert bad_email.json()["message"]["zh"] and bad_email.json()["message"]["en"]

    short = client.post(api("/signup"), json={"email": "bob@example.com", "password": "1234567"})
    assert short.status_code == 400
    assert short.json()["error"] == "password_too_short"
    assert short.json()["message"]["zh"] and short.json()["message"]["en"]


def test_wrong_password_and_unknown_email_look_the_same(client):
    signup(client)
    wrong = client.post(api("/login"), json={"email": "alice@example.com", "password": "Wrong-Password-1"})
    unknown = client.post(api("/login"), json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"] == "invalid_credentials"
    assert wrong.json()["message"]["zh"] and wrong.json()["message"]["en"]


def test_not_authenticated_is_bilingual(client):
    response = client.get(api("/me"))
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"
    assert response.json()["message"]["zh"] and response.json()["message"]["en"]


def test_delete_account_removes_sessions_and_device_credentials(client, db_path):
    signed_in(client)
    code = client.post(api("/device/code"), json={"device_name": "Mac"}).json()
    client.post(api("/device/approve"), json={"user_code": code["user_code"]})
    issued = client.post(api("/device/token"), json={"device_code": code["device_code"]})
    assert issued.status_code == 200, issued.text
    token = issued.json()["credential"]["token"]
    assert client.get(api("/device/me"), headers={"Authorization": f"Bearer {token}"}).status_code == 200

    deleted = client.delete(api("/me"))
    assert deleted.status_code == 204
    assert client.get(api("/me")).status_code == 401
    assert client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD}).status_code == 401
    assert client.get(api("/device/me"), headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_devices") == 0


def test_sessions_are_removed_on_logout_but_other_sessions_survive(client, app):
    from fastapi.testclient import TestClient

    other = TestClient(app)
    try:
        signed_in(client)
        signed_in(other, email="bob@example.com")
        assert client.post(api("/logout")).status_code == 204
        assert client.get(api("/me")).status_code == 401
        assert other.get(api("/me")).status_code == 200
    finally:
        other.close()


@pytest.mark.parametrize("email", ["alice@example.com", "ALICE@EXAMPLE.COM"])
def test_email_is_normalized_and_the_same_account_logs_in(client, email):
    signup(client, email="Alice@Example.com")
    response = client.post(api("/login"), json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "alice@example.com"
