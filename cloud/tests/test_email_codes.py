"""邮箱验证码:注册必须验码、只存哈希、一次性、冷却 / 限流、登录两条路、枚举防护。

这些用例**不连外网**:正常路径用 `conftest.RecordingSender`(记下收件人和码),失败路径用
一个指向本机关闭端口的真实 SMTP sender —— 连接被立刻拒绝,不产生任何外部流量。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import CloudConfig
from cloud.models import now
from conftest import (
    PASSWORD,
    api,
    login_code,
    request_login_code,
    request_signup_code,
    scalar,
    signup,
)

WRONG_CODE = "000000"


def db_execute(db_path, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(sql, params)
        connection.commit()


def signup_without_code(client, email: str = "new@example.com", password: str = PASSWORD):
    return client.post(api("/signup"), json={"email": email, "password": password})


def a_different_code(code: str) -> str:
    return "111111" if code != "111111" else "222222"


# ---------------------------------------------------------------- ① 注册必须验码


def test_signup_without_a_code_is_refused_with_a_clear_message(client, db_path):
    response = signup_without_code(client)
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"] == "email_code_required"
    assert body["message"]["zh"] and body["message"]["en"]
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0


def test_signup_with_a_wrong_code_is_refused(client, db_path):
    code = request_signup_code(client, "new@example.com")
    response = client.post(
        api("/signup"),
        json={"email": "new@example.com", "code": a_different_code(code), "password": PASSWORD},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "email_code_invalid"
    assert response.json()["message"]["zh"] and response.json()["message"]["en"]
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0
    # 失败一次会记进 attempts,方便"5 次作废"。
    assert scalar(db_path, "SELECT attempts FROM cloud_email_codes") == 1


def test_signup_with_an_expired_code_is_refused(client, db_path):
    code = request_signup_code(client, "new@example.com")
    db_execute(db_path, "UPDATE cloud_email_codes SET expires_at = '2000-01-01 00:00:00.000000'")
    response = client.post(
        api("/signup"),
        json={"email": "new@example.com", "code": code, "password": PASSWORD},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "email_code_expired"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0


def test_signup_with_a_used_code_is_refused(client, db_path):
    code = request_signup_code(client, "new@example.com")
    db_execute(db_path, "UPDATE cloud_email_codes SET used_at = '2000-01-01 00:00:00.000000'")
    response = client.post(
        api("/signup"),
        json={"email": "new@example.com", "code": code, "password": PASSWORD},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "email_code_used"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0

def test_successful_signup_marks_the_email_verified_and_burns_the_code(client, db_path):
    user = signup(client, email="verified@example.com")
    assert user["email_verified_at"] is not None, "注册成功必须写 email_verified_at"
    assert scalar(db_path, "SELECT used_at FROM cloud_email_codes") is not None
    # 密码仍然落成 argon2id,不是明文。
    assert scalar(db_path, "SELECT password_hash FROM cloud_users").startswith("$argon2id$")


# ---------------------------------------------------------------- ② 码只存哈希


def test_codes_are_stored_as_hashes_never_as_plaintext(client, db_path):
    code = request_signup_code(client, "hash@example.com")
    assert re.fullmatch(r"\d{6}", code), code

    stored = scalar(db_path, "SELECT code_hash FROM cloud_email_codes")
    assert stored and len(stored) == 64, stored
    assert stored != code and code not in stored

    # 整张库的任何一行都不该出现这 6 位明文。
    with sqlite3.connect(db_path) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        dump = "\n".join(
            str(row) for table in tables for row in connection.execute(f"SELECT * FROM {table}")
        )
    assert code not in dump


# ---------------------------------------------------------------- ③ 一次性 / 冷却 / 限流


def test_resend_is_cooled_down_for_sixty_seconds(client):
    request_signup_code(client, "cooldown@example.com")
    again = client.post(api("/signup/code"), json={"email": "cooldown@example.com"})
    assert again.status_code == 429, again.text
    body = again.json()
    assert body["error"] == "email_code_cooldown"
    assert body["message"]["zh"] and body["message"]["en"]
    # 明确告诉用户"稍后再试",并且带上秒数。
    assert "秒" in body["message"]["zh"] and any(character.isdigit() for character in body["message"]["zh"])


def test_per_email_hourly_limit_is_enforced(client, db_path):
    email = "limited@example.com"
    old = (now() - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
    for index in range(5):
        db_execute(
            db_path,
            "INSERT INTO cloud_email_codes (id, email, purpose, code_hash, attempts, created_at, expires_at, request_ip) "
            "VALUES (?, ?, 'signup', ?, 0, ?, '2999-01-01 00:00:00.000000', '')",
            (f"row-{index}", email, "0" * 64, old),
        )
    response = client.post(api("/signup/code"), json={"email": email})
    assert response.status_code == 429, response.text
    assert response.json()["error"] == "too_many_requests"
    assert response.json()["message"]["zh"] and response.json()["message"]["en"]


def test_per_ip_hourly_limit_is_enforced(client, db_path):
    old = (now() - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
    for index in range(20):
        db_execute(
            db_path,
            "INSERT INTO cloud_email_codes (id, email, purpose, code_hash, attempts, created_at, expires_at, request_ip) "
            "VALUES (?, ?, 'signup', ?, 0, ?, '2999-01-01 00:00:00.000000', 'testclient')",
            (f"ip-row-{index}", f"someone-{index}@example.com", "0" * 64, old),
        )
    response = client.post(api("/signup/code"), json={"email": "fresh@example.com"})
    assert response.status_code == 429, response.text
    assert response.json()["error"] == "too_many_requests"


def test_five_wrong_attempts_burn_the_code(client, db_path):
    code = request_signup_code(client, "attempts@example.com")
    for _ in range(5):
        response = client.post(
            api("/signup"),
            json={"email": "attempts@example.com", "code": a_different_code(code), "password": PASSWORD},
        )
        assert response.status_code == 400, response.text
    # 第 6 次即使拿对的码也不再认。
    response = client.post(
        api("/signup"),
        json={"email": "attempts@example.com", "code": code, "password": PASSWORD},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "email_code_attempts_exhausted"


# ---------------------------------------------------------------- ④ 登录两条路


def test_password_login_and_code_login_open_the_same_kind_of_session(client, db_path):
    signup(client, email="both@example.com")

    password_login = client.post(api("/login"), json={"email": "both@example.com", "password": PASSWORD})
    assert password_login.status_code == 200, password_login.text
    assert "HttpOnly" in password_login.headers["set-cookie"]
    assert client.get(api("/me")).json()["user"]["email"] == "both@example.com"
    assert client.post(api("/logout")).status_code == 204

    user = login_code(client, email="both@example.com")
    assert user["email"] == "both@example.com"
    checked = client.get(api("/me"))
    assert checked.status_code == 200
    assert checked.json()["user"]["email_verified_at"] is not None
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 1


def test_a_login_code_only_works_once(client):
    signup(client, email="once@example.com")
    code = request_login_code(client, email="once@example.com")
    first = client.post(api("/login/code/verify"), json={"email": "once@example.com", "code": code})
    assert first.status_code == 200, first.text
    client.post(api("/logout"))
    second = client.post(api("/login/code/verify"), json={"email": "once@example.com", "code": code})
    assert second.status_code == 400, second.text
    assert second.json()["error"] == "email_code_used"


def test_code_login_for_an_unknown_email_does_not_create_an_account(client, db_path):
    response = client.post(
        api("/login/code/verify"), json={"email": "nobody@example.com", "code": "123456"}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "email_code_invalid"
    assert client.get(api("/me")).status_code == 401
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0


# ---------------------------------------------------------------- ⑤ 未配置发信 / 日志


def test_unconfigured_smtp_returns_a_clear_error(tmp_path, caplog):
    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False)
    assert not config.smtp_configured
    app = create_app(config)  # 不注入假 sender:走真实的 SMTP sender
    client = TestClient(app)
    try:
        with caplog.at_level(logging.DEBUG, logger="cloud"):
            response = client.post(api("/signup/code"), json={"email": "mail@example.com"})
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["error"] == "mail_not_configured"
        assert "管理员" in body["message"]["zh"]
        assert "administrator" in body["message"]["en"].lower()
        # 未注册邮箱发登录码也回同一句:没配置发信不能变成账号探测器。
        unknown = client.post(api("/login/code"), json={"email": "nobody@example.com"})
        assert unknown.status_code == 503, unknown.text
        assert unknown.json() == body
        # 没有配置就不该在库里留一条永远收不到的码。
        assert scalar(config.data_dir / "cloud.db", "SELECT COUNT(*) FROM cloud_email_codes") == 0
    finally:
        client.close()


def test_failed_delivery_reports_an_error_and_leaves_no_code_behind(tmp_path, caplog):
    config = CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
        smtp_host="127.0.0.1",
        smtp_port=1,
        smtp_tls="none",
    )
    app = create_app(config)  # 真实 sender,连接本机关闭端口 → 立即拒绝
    client = TestClient(app)
    try:
        with caplog.at_level(logging.DEBUG, logger="cloud"):
            response = client.post(api("/signup/code"), json={"email": "mail@example.com"})
        assert response.status_code == 502, response.text
        assert response.json()["error"] == "email_send_failed"
        assert scalar(config.data_dir / "cloud.db", "SELECT COUNT(*) FROM cloud_email_codes") == 0
    finally:
        client.close()


def test_logs_only_ever_show_a_masked_address_and_never_the_code(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="cloud"):
        code = request_signup_code(client, "masked@example.com")
    assert code not in caplog.text, caplog.text
    assert "masked@example.com" not in caplog.text
    assert "m***@example.com" in caplog.text
    assert not re.search(r"\b\d{6}\b", caplog.text), caplog.text


# ---------------------------------------------------------------- ⑥ 枚举防护


def test_login_code_request_looks_identical_for_known_and_unknown_emails(client):
    signup(client, email="known@example.com")
    sender = client.app.state.code_sender

    known = client.post(api("/login/code"), json={"email": "known@example.com"})
    unknown = client.post(api("/login/code"), json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"sent": True}
    assert sender.codes("known@example.com", "login")
    assert sender.codes("nobody@example.com", "login") == []


def test_signup_code_for_an_existing_email_is_refused(client):
    signup(client, email="taken@example.com")
    response = client.post(api("/signup/code"), json={"email": "taken@example.com"})
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "email_taken"


# ---------------------------------------------------------------- 发信配置


def test_smtp_host_can_carry_the_port_and_derives_a_safe_tls_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUD_SMTP_HOST", "localhost:1025")
    monkeypatch.delenv("CLOUD_SMTP_TLS", raising=False)
    monkeypatch.delenv("CLOUD_SMTP_USERNAME", raising=False)
    config = CloudConfig.from_env()
    assert config.smtp_host == "localhost"
    assert config.smtp_port == 1025
    # 无认证的本地 Mailpit 默认不 STARTTLS —— 否则连不上。
    assert config.smtp_tls == "none"
    assert config.smtp_configured

    monkeypatch.setenv("CLOUD_SMTP_USERNAME", "user")
    monkeypatch.setenv("CLOUD_SMTP_PASSWORD", "secret")
    authenticated = CloudConfig.from_env()
    assert authenticated.smtp_tls == "starttls"
