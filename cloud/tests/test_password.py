"""MosaelCloud 密码设置 / 修改:验证码账号可首次设置,已有密码必须验旧密码。"""

from __future__ import annotations

from conftest import PASSWORD, api, login_phone, signup


def test_email_account_can_change_password_with_the_current_one(client):
    user = signup(client, email="password@example.com")
    assert user["has_password"] is True

    wrong = client.post(api("/me/password"), json={"current_password": "wrong", "new_password": "New-Horse-9"})
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "current_password_invalid"

    changed = client.post(
        api("/me/password"),
        json={"current_password": PASSWORD, "new_password": "New-Horse-9"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["user"]["has_password"] is True

    assert client.post(api("/login"), json={"email": "password@example.com", "password": PASSWORD}).status_code == 401
    assert (
        client.post(api("/login"), json={"email": "password@example.com", "password": "New-Horse-9"}).status_code == 200
    )


def test_phone_only_account_is_told_to_link_an_email_first(client):
    user = login_phone(client, "13800138000")
    assert user["has_password"] is False

    response = client.post(api("/me/password"), json={"new_password": "Phone-Horse-9"})
    assert response.status_code == 400
    assert response.json()["error"] == "email_required"

    assert client.get(api("/me")).json()["user"]["has_password"] is False
