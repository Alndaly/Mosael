"""桌面端只把 Cloud 绑定**存下来**:新表 + 一条本地接口。

两套身份隔离在这里再钉一次:写绑定不会新增/修改本地 `users`,不会换掉本地登录态,也不会把云端
凭据放进任何会交给渲染层的响应里。云端 token 落盘走现有的落盘加密(`EncryptedText`)。
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import CloudBinding, User
from app.domain import cloud_binding
from tests.util import fresh_client

CLOUD_URL = "https://cloud.example/api/cloud/v1"
DEVICE_TOKEN = "cloud-device-token-9f2a7c1e-do-not-log"


class FakeCloud:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, payload: dict):
        self.calls.append((path, payload))
        found = self.responses.pop(0)
        if isinstance(found, BaseException):
            raise found
        return found


def bindable(monkeypatch, responses):
    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL)
    fake = FakeCloud(responses)
    monkeypatch.setattr(cloud_binding, "post_json", fake)
    return fake


def code_body(device_code: str = "desktop-device-code") -> dict:
    return {
        "device_code": device_code,
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://mosael.com/en/account",
        "verification_uri_complete": "https://mosael.com/en/account?user_code=ABCD-EFGH",
        "expires_in": 600,
        "interval": 5,
    }


def credential_body() -> dict:
    return {
        "status": "approved",
        "credential": {
            "device_id": "cloud-device-1",
            "token": DEVICE_TOKEN,
            "account": {"id": "cloud-user-1", "email": "alice@example.com"},
        },
    }


def me(client) -> dict:
    response = client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return response.json()


def local_state() -> tuple[int, str, str]:
    with SessionLocal() as db:
        users = db.query(User).all()
        return len(users), users[0].id, users[0].password_hash


def test_binding_start_and_complete_stores_the_credential_encrypted(monkeypatch):
    client = fresh_client()
    before_count, local_id, before_hash = local_state()
    fake = bindable(monkeypatch, [(200, code_body()), (428, {"error": "authorization_pending"}), (200, credential_body())])

    start = client.post("/api/cloud/binding/start", json={"device_name": "MacBook Pro"})
    assert start.status_code == 200, start.text
    assert start.json()["user_code"] == "ABCD-EFGH"
    assert start.json()["device_code"] == "desktop-device-code"
    assert start.json()["verification_uri"].startswith("https://mosael.com/")
    assert fake.calls[0] == ("/device/code", {"device_name": "MacBook Pro"})

    pending = client.post("/api/cloud/binding/complete", json={"device_code": "desktop-device-code"})
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"
    assert client.get("/api/cloud/binding").json()["bound"] is False

    done = client.post("/api/cloud/binding/complete", json={"device_code": "desktop-device-code"})
    assert done.status_code == 200, done.text
    assert done.json() == {"status": "approved", "email": "alice@example.com", "device_id": "cloud-device-1"}
    assert "token" not in done.text

    status = client.get("/api/cloud/binding")
    assert status.status_code == 200
    assert status.json()["bound"] is True
    assert status.json()["email"] == "alice@example.com"
    assert status.json()["device_id"] == "cloud-device-1"
    assert "token" not in status.text

    # 盘上是密文;ORM 读回来是原文(加密能反向)。
    with sqlite3.connect(settings.db_path) as connection:
        stored = connection.execute("SELECT token FROM cloud_bindings").fetchone()[0]
    assert DEVICE_TOKEN not in stored
    with SessionLocal() as db:
        row = db.get(CloudBinding, local_id)
        assert row.token == DEVICE_TOKEN
        assert row.cloud_user_id == "cloud-user-1"
        assert row.email == "alice@example.com"

    # 本地身份一行都没动。
    assert local_state() == (before_count, local_id, before_hash)
    assert me(client)["username"] == "tester"
    with SessionLocal() as db:
        assert db.query(User).filter(User.username == "alice@example.com").count() == 0


def test_cloud_token_is_not_logged(monkeypatch, caplog):
    client = fresh_client()
    bindable(monkeypatch, [(200, code_body()), (200, credential_body())])
    with caplog.at_level(logging.DEBUG):
        client.post("/api/cloud/binding/start", json={"device_name": "Mac"})
        client.post("/api/cloud/binding/complete", json={"device_code": "desktop-device-code"})
    assert DEVICE_TOKEN not in caplog.text


def test_an_already_bound_user_must_unbind_first(monkeypatch):
    client = fresh_client()
    bindable(monkeypatch, [(200, code_body()), (200, credential_body())])
    client.post("/api/cloud/binding/start", json={})
    assert client.post("/api/cloud/binding/complete", json={"device_code": "desktop-device-code"}).status_code == 200

    again = client.post("/api/cloud/binding/complete", json={"device_code": "another-code"})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "cloud_already_bound"


def test_unbind_removes_only_the_binding(monkeypatch):
    client = fresh_client()
    fake = bindable(monkeypatch, [(200, code_body()), (200, credential_body())])
    before = me(client)
    client.post("/api/cloud/binding/start", json={})
    client.post("/api/cloud/binding/complete", json={"device_code": "desktop-device-code"})

    removed = client.delete("/api/cloud/binding")
    assert removed.status_code == 200
    assert removed.json() == {"removed": True}
    assert client.get("/api/cloud/binding").json()["bound"] is False
    with SessionLocal() as db:
        assert db.get(CloudBinding, before["id"]) is None
    assert me(client)["username"] == before["username"]
    # 解绑不碰云端:本地删掉就够了,云端撤销在官网那一侧。
    assert [path for path, _ in fake.calls] == ["/device/code", "/device/token"]


def test_start_without_a_configured_cloud_url_says_so(monkeypatch):
    client = fresh_client()
    monkeypatch.setattr(settings, "cloud_url", "")
    response = client.post("/api/cloud/binding/start", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "cloud_not_configured"


def test_cloud_unreachable_is_not_a_local_identity_failure(monkeypatch):
    client = fresh_client()
    bindable(monkeypatch, [cloud_binding.CloudUnavailable("connection refused")])
    before = me(client)
    response = client.post("/api/cloud/binding/start", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "cloud_unreachable"
    assert me(client) == before


def test_cloud_rejections_do_not_create_a_binding(monkeypatch):
    client = fresh_client()
    bindable(monkeypatch, [(410, {"error": "device_code_expired", "message": {"en": "expired", "zh": "已过期"}})])
    response = client.post("/api/cloud/binding/complete", json={"device_code": "stale"})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "device_code_expired"
    assert client.get("/api/cloud/binding").json()["bound"] is False


def test_binding_endpoints_require_a_local_login():
    client = fresh_client()
    client.post("/api/auth/logout")
    for method, path in (
        ("post", "/api/cloud/binding/start"),
        ("post", "/api/cloud/binding/complete"),
        ("get", "/api/cloud/binding"),
        ("delete", "/api/cloud/binding"),
    ):
        response = getattr(client, method)(path, json={}) if method == "post" else getattr(client, method)(path)
        assert response.status_code == 401, (method, path)


@pytest.mark.parametrize("status", [401, 404, 410, 500])
def test_cloud_failure_statuses_are_kept_where_they_make_sense(monkeypatch, status):
    client = fresh_client()
    bindable(monkeypatch, [(status, {"error": "some_cloud_error", "message": {"en": "no", "zh": "不行"}})])
    response = client.post("/api/cloud/binding/complete", json={"device_code": "x"})
    assert response.status_code == (status if status != 500 else 502)
    assert response.json()["detail"]["code"] in {"some_cloud_error", "cloud_unavailable"}


def test_the_cloud_bindings_migration_creates_the_table_and_is_idempotent():
    """新表由 create-all 建;这条显式迁移负责给"表还不存在"的库补上,并且**再跑一次什么都不做**。"""
    from app.db.migrations import _migrate_cloud_bindings_table

    fresh_client()
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("DROP TABLE cloud_bindings")
        connection.commit()

    _migrate_cloud_bindings_table()
    with sqlite3.connect(settings.db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_bindings)")}
    assert columns == {"user_id", "cloud_user_id", "email", "device_id", "token", "created_at"}

    # 再跑一次:checkfirst,不报错、不重建、不清数据。
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute(
            "INSERT INTO cloud_bindings (user_id, cloud_user_id, email, device_id, token, created_at) "
            "VALUES ('keep-me', 'cloud', 'a@example.com', 'device', 'ciphertext', '2026-01-01 00:00:00')"
        )
        connection.commit()
    _migrate_cloud_bindings_table()
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cloud_bindings").fetchone()[0] == 1
