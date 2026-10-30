"""MosaelCloud 管理员角色:默认普通成员、CLI 授予/撤销、最后一名守卫、管理端只认浏览器。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud.cli import main
from cloud.db import Database
from cloud.domain import admin, device_tokens
from cloud.models import CloudUser
from cloud.schema import upgrade_database
from conftest import api, signup


@pytest.fixture
def admin_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUD_DATA_DIR", str(tmp_path))
    for name in ("CLOUD_DATABASE_URL", "CLOUD_CHANNEL_KEY", "CLOUD_UPSTREAM_KEY", "CLOUD_OFFICIAL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    url = f"sqlite:///{tmp_path / 'cloud.db'}"
    upgrade_database(url)
    database = Database(url)
    with database.session() as db:
        db.add(CloudUser(email="alice@example.com", handle="alice", display_name="Alice"))
        db.add(CloudUser(email="bob@example.com", handle="bob", display_name="Bob"))
        db.commit()
    yield database
    database.dispose()


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def role(database, email: str) -> str:
    with database.session() as db:
        return db.scalar(select(CloudUser.role).where(CloudUser.email == email))


def test_cli_grants_and_revokes_but_never_removes_the_last_admin(admin_env, capsys):
    assert role(admin_env, "alice@example.com") == "member"

    code, out, _ = run(capsys, "admin-grant", "--email", "Alice@Example.com")
    assert code == 0 and "已成为" in out
    assert role(admin_env, "alice@example.com") == "admin"

    code, out, _ = run(capsys, "admin-list")
    assert code == 0 and "alice@example.com" in out

    code, _, err = run(capsys, "admin-revoke", "--email", "alice@example.com")
    assert code == 2 and "最后一名" in err
    assert role(admin_env, "alice@example.com") == "admin"

    assert run(capsys, "admin-grant", "--email", "bob@example.com")[0] == 0
    assert run(capsys, "admin-revoke", "--email", "alice@example.com")[0] == 0
    assert role(admin_env, "alice@example.com") == "member"
    assert role(admin_env, "bob@example.com") == "admin"


def test_member_and_admin_are_told_apart_by_the_admin_endpoint(client):
    member = signup(client, email="member@example.com")
    assert member["role"] == "member"
    denied = client.get(api("/admin/me"))
    assert denied.status_code == 403
    assert denied.json()["error"] == "admin_required"

    with client.app.state.db.session() as db:
        user = db.scalar(select(CloudUser).where(CloudUser.email == "member@example.com"))
        admin.grant(db, user)
        db.commit()

    allowed = client.get(api("/admin/me"))
    assert allowed.status_code == 200
    assert allowed.json()["user"]["role"] == "admin"


def test_admin_endpoint_rejects_device_tokens(client):
    signup(client, email="device@example.com")
    with client.app.state.db.session() as db:
        user = db.scalar(select(CloudUser).where(CloudUser.email == "device@example.com"))
        admin.grant(db, user)
        db.commit()
        token, secret = device_tokens.issue(db, user, "host")
        db.commit()

    response = client.get(api("/admin/me"), headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 403
    assert response.json()["error"] == "admin_requires_browser"
