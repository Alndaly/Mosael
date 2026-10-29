"""手机短信验证码登录:自动建号、60 秒冷却、一次性、号码归一化。"""

from __future__ import annotations

import sqlite3

from cloud.app import create_app
from cloud.config import CloudConfig
from conftest import api, login_phone, request_phone_code, scalar


def test_sms_login_creates_a_phone_only_account_and_reuses_it(client, db_path):
    user = login_phone(client, "13800138000")
    assert user["email"] is None
    assert user["phone"] == "+8613800138000"
    assert user["phone_verified_at"] is not None
    assert user["display_name"] and user["handle"]
    assert scalar(db_path, "SELECT used_at FROM cloud_phone_codes") is not None

    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE cloud_phone_codes SET created_at = '2000-01-01 00:00:00.000000'")
        db.commit()
    again = login_phone(client, "+86 138-0013-8000")
    assert again["id"] == user["id"]
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 1


def test_sms_resend_is_cooled_down_for_sixty_seconds(client):
    request_phone_code(client, "13800138000")
    again = client.post(api("/login/sms/code"), json={"phone": "13800138000"})
    assert again.status_code == 429, again.text
    body = again.json()
    assert body["error"] == "phone_code_cooldown"
    assert "秒" in body["message"]["zh"]
    # 同一条冷却也适用于邮箱入口,两个通道共用 60 秒语义。
    email = client.post(api("/login/code"), json={"email": "someone@example.com"})
    assert email.status_code == 200


def test_sms_code_is_hashed_and_burned_after_use(client, db_path):
    code = request_phone_code(client, "13800138000")
    stored = scalar(db_path, "SELECT code_hash FROM cloud_phone_codes")
    assert stored and len(stored) == 64
    assert code not in stored

    response = client.post(api("/login/sms/verify"), json={"phone": "13800138000", "code": code})
    assert response.status_code == 200, response.text
    reused = client.post(api("/login/sms/verify"), json={"phone": "13800138000", "code": code})
    assert reused.status_code == 400
    assert reused.json()["error"] == "phone_code_used"


def test_sms_wrong_code_is_refused_and_attempt_is_recorded(client, db_path):
    code = request_phone_code(client, "13800138000")
    wrong = "111111" if code != "111111" else "222222"
    response = client.post(api("/login/sms/verify"), json={"phone": "13800138000", "code": wrong})
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "phone_code_invalid"
    assert scalar(db_path, "SELECT attempts FROM cloud_phone_codes") == 1
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_users") == 0


def test_invalid_phone_is_rejected_before_any_sms(client):
    response = client.post(api("/login/sms/code"), json={"phone": "123"})
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "phone_invalid"
    assert client.app.state.sms_sender.sent == []


def test_sms_is_not_configured_when_tencent_credentials_are_missing(tmp_path):
    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False)
    app = create_app(config)
    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)
    try:
        response = client.post(api("/login/sms/code"), json={"phone": "13800138000"})
        assert response.status_code == 503, response.text
        assert response.json()["error"] == "sms_not_configured"
        with sqlite3.connect(config.data_dir / "cloud.db") as db:
            assert db.execute("SELECT COUNT(*) FROM cloud_phone_codes").fetchone()[0] == 0
    finally:
        client.close()
