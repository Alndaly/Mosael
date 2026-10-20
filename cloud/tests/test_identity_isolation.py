"""两套身份体系互不污染。

MosaelCloud 的账号表叫 `cloud_users`,不叫 `users`;它不认识本地服务端的 `users` / `workspaces` /
`auth_sessions`。这里用两个真实的 SQLite 文件把这条边界钉住:一个假装是本地后端库,一个是 Cloud 库。
Cloud 的注册、登录、删号只能动后者。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import CloudConfig
from conftest import PASSWORD, api, build_app, scalar, signup


def make_local_database(path: Path) -> None:
    """本地服务端身份的最小形状(照 backend/app/db/model_slices/identity.py 的两张表)。"""
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                id VARCHAR(64) PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                password_hash VARCHAR(240) NOT NULL DEFAULT '',
                display_name VARCHAR(120) NOT NULL DEFAULT ''
            );
            CREATE TABLE workspaces (id VARCHAR(64) PRIMARY KEY, name VARCHAR(160) NOT NULL);
            CREATE TABLE auth_sessions (token VARCHAR(80) PRIMARY KEY, user_id VARCHAR(64) NOT NULL);
            INSERT INTO users (id, username, password_hash, display_name)
                VALUES ('local-user-1', 'alice', 'pbkdf2$240000$deadbeef$cafe', 'Alice');
            INSERT INTO workspaces (id, name) VALUES ('local-ws-1', 'Alice workspace');
            INSERT INTO auth_sessions (token, user_id) VALUES ('local-session-token-1', 'local-user-1');
            """
        )


def local_snapshot(path: Path) -> dict[str, list[tuple]]:
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("users", "workspaces", "auth_sessions")
        }


def test_cloud_has_its_own_tables_and_no_local_identity_columns(tmp_path):
    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False)
    create_app(config)
    with sqlite3.connect(tmp_path / "cloud.db") as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"cloud_users", "cloud_sessions"} <= tables
        assert not ({"users", "workspaces", "auth_sessions", "workspace_members"} & tables)

        columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_users)")}
        # 身份的三列属于 Cloud 自己;本地账号的用户名 / 工作区列一个都不许过来。
        assert columns == {
            "id",
            "email",
            "password_hash",
            "email_verified_at",
            "created_at",
            "display_name",
            "handle",
            "avatar_seed",
        }
        assert not ({"username", "workspace_id", "local_user_id"} & columns)


def test_cloud_signup_and_login_never_touch_the_local_database(tmp_path):
    local = tmp_path / "local" / "mosael.db"
    local.parent.mkdir()
    make_local_database(local)
    before = local_snapshot(local)

    config = CloudConfig(data_dir=tmp_path / "cloud", public_url="https://mosael.test", cookie_secure=False)
    config.data_dir.mkdir()
    app = build_app(config)
    client = TestClient(app)
    try:
        user = signup(client, email="alice@example.com")
        assert user["id"] != "local-user-1"
        client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
        client.delete(api("/me"))
    finally:
        client.close()

    assert local_snapshot(local) == before
    # Cloud 自己的库里没有本地账号的任何痕迹。
    with sqlite3.connect(config.data_dir / "cloud.db") as connection:
        dump = "\n".join(
            str(row)
            for table in ("cloud_users", "cloud_sessions")
            for row in connection.execute(f"SELECT * FROM {table}")
        )
    assert "local-user-1" not in dump
    assert "pbkdf2$240000$deadbeef$cafe" not in dump
    assert "local-ws-1" not in dump
    assert "alice" not in dump


def test_a_local_account_can_exist_before_cloud_registration_and_stays_put(tmp_path):
    """反方向:本地先有人,Cloud 再注册 / 登录 —— 本地一行都不动。"""
    local = tmp_path / "local.db"
    make_local_database(local)
    before = local_snapshot(local)

    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False)
    app = build_app(config)
    client = TestClient(app)
    try:
        signup(client, email="alice@example.com")
        assert client.get(api("/me")).status_code == 200  # 注册即登录
        client.post(api("/logout"))
        client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
        assert client.get(api("/me")).status_code == 200
    finally:
        client.close()
    assert local_snapshot(local) == before


def test_cloud_uses_its_own_ids_not_local_ones(tmp_path):
    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False)
    app = build_app(config)
    client = TestClient(app)
    try:
        user = signup(client)
        assert len(user["id"]) == 32
        assert user["id"] != "local-user-1"
        assert scalar(config.data_dir / "cloud.db", "SELECT COUNT(*) FROM cloud_users") == 1
    finally:
        client.close()
