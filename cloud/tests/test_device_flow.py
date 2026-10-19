"""设备码绑定:桌面端拿到码 → 已登录的官网确认 → 桌面端换到一次性云端凭据。"""

from __future__ import annotations

import hashlib
import re
import sqlite3

from fastapi.testclient import TestClient

from conftest import PASSWORD, api, device_code, scalar, signed_in


def _pending(desktop, code: dict):
    return desktop.post(api("/device/token"), json={"device_code": code["device_code"]})


def _approve(web, user_code: str):
    return web.post(api("/device/approve"), json={"user_code": user_code})


def _relogin(client, email: str) -> None:
    response = client.post(api("/login"), json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_device_flow_end_to_end(client, app, db_path):
    desktop = client
    web = TestClient(app)
    try:
        code = device_code(desktop, "MacBook Pro")
        assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", code["user_code"]), code["user_code"]
        assert len(code["device_code"]) >= 43
        assert code["expires_in"] == 600
        assert code["interval"] == 5
        assert code["verification_uri"].startswith("https://mosael.test/")
        assert code["verification_uri_complete"].endswith(code["user_code"])

        pending = _pending(desktop, code)
        assert pending.status_code == 428
        assert pending.json()["error"] == "authorization_pending"

        signed_in(web)
        assert _approve(web, code["user_code"].lower().replace("-", "")).status_code == 204

        issued = _pending(desktop, code)
        assert issued.status_code == 200, issued.text
        body = issued.json()
        assert body["status"] == "approved"
        credential = body["credential"]
        assert credential["device_id"]
        assert len(credential["token"]) >= 43
        assert credential["account"]["email"] == "alice@example.com"
        # 云端凭据只以哈希落盘。
        stored = scalar(db_path, "SELECT token_hash FROM cloud_devices")
        assert stored == hashlib.sha256(credential["token"].encode()).hexdigest()
        with sqlite3.connect(db_path) as connection:
            dump = "\n".join(
                str(row) for row in connection.execute("SELECT * FROM cloud_devices")
            )
        assert credential["token"] not in dump

        # 一次性。
        again = _pending(desktop, code)
        assert again.status_code == 410
        assert again.json()["error"] == "device_code_used"

        # 桌面端拿着凭据问"我是谁"。
        identity = desktop.get(
            api("/device/me"), headers={"Authorization": f"Bearer {credential['token']}"}
        )
        assert identity.status_code == 200
        assert identity.json()["account"]["email"] == "alice@example.com"
        assert identity.json()["device"]["id"] == credential["device_id"]

        devices = web.get(api("/devices"))
        assert devices.status_code == 200
        listed = devices.json()["devices"]
        assert [one["id"] for one in listed] == [credential["device_id"]]
        assert listed[0]["name"] == "MacBook Pro"

        # 云端撤销 → 同一枚凭据立刻失效。
        assert web.delete(api(f"/device/{credential['device_id']}")).status_code == 204
        assert desktop.get(
            api("/device/me"), headers={"Authorization": f"Bearer {credential['token']}"}
        ).status_code == 401
        assert web.get(api("/devices")).json()["devices"] == []
    finally:
        web.close()


def test_unknown_expired_and_used_codes_fail_with_distinct_codes(client, app, db_path):
    desktop = client
    web = TestClient(app)
    try:
        unknown = desktop.post(api("/device/token"), json={"device_code": "not-a-real-device-code"})
        assert unknown.status_code == 404
        assert unknown.json()["error"] == "device_code_invalid"

        stale = device_code(desktop)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE cloud_device_codes SET expires_at = '2000-01-01 00:00:00.000000' WHERE user_code = ?",
                (stale["user_code"],),
            )
            connection.commit()
        expired = _pending(desktop, stale)
        assert expired.status_code == 410
        assert expired.json()["error"] == "device_code_expired"

        signed_in(web)
        expired_approve = _approve(web, stale["user_code"])
        assert expired_approve.status_code == 410
        assert expired_approve.json()["error"] == "device_code_expired"
    finally:
        web.close()


def test_approve_requires_a_signed_in_user(client):
    code = device_code(client)
    response = _approve(client, code["user_code"])
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"


def test_approve_rejects_unknown_and_malformed_codes(client):
    signed_in(client)
    for value in ("ZZZZ-ZZZZ", "!!!!"):
        response = _approve(client, value)
        assert response.status_code == 404, value
        assert response.json()["error"] == "user_code_invalid"
    # 空串是"请求形状不对",不是"码不存在" —— 两种失败要分得开。
    empty = _approve(client, "")
    assert empty.status_code == 422
    assert empty.json()["error"] == "invalid_request"


def test_one_device_code_can_only_be_claimed_by_one_account(client, app):
    desktop = client
    first = TestClient(app)
    second = TestClient(app)
    try:
        code = device_code(desktop)
        signed_in(first, email="first@example.com")
        signed_in(second, email="second@example.com")
        assert _approve(first, code["user_code"]).status_code == 204
        # 同一个人再点一次是幂等的。
        assert _approve(first, code["user_code"]).status_code == 204
        taken = _approve(second, code["user_code"])
        assert taken.status_code == 409
        assert taken.json()["error"] == "user_code_used"
        # 换到的是第一个人的账号。
        issued = _pending(desktop, code)
        assert issued.json()["credential"]["account"]["email"] == "first@example.com"
    finally:
        first.close()
        second.close()


def test_device_token_must_be_a_bearer_token(client):
    for headers in ({}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic abc"}):
        response = client.get(api("/device/me"), headers=headers)
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_device_token"


def test_revoking_someone_elses_device_is_a_404(client, app):
    desktop = client
    first = TestClient(app)
    second = TestClient(app)
    try:
        code = device_code(desktop)
        signed_in(first, email="first@example.com")
        _approve(first, code["user_code"])
        issued = _pending(desktop, code).json()["credential"]

        signed_in(second, email="second@example.com")
        response = second.delete(api(f"/device/{issued['device_id']}"))
        assert response.status_code == 404
        # 主人还能用。
        assert desktop.get(
            api("/device/me"), headers={"Authorization": f"Bearer {issued['token']}"}
        ).status_code == 200
    finally:
        first.close()
        second.close()
