"""密钥不该明文落盘。

跑在真实库上的体检(动手前):

    provider_credentials.api_key            demo
    provider_credentials.oauth_credential   {"type":"oauth","access":"eyJhbGciOiJFUzI1NiIsImtpZCI…
    feishu_bots.app_secret                  ijutISpYv0dgu5xjhphqqfZ5wuTcGzge
    plugin_credentials.value                <插件自己的 API Key>
    publish_accounts.config                 <平台登录态>

一个库文件 = 所有人的钥匙。而库文件**很容易离开这台机器**:备份、iCloud/Time Machine、磁盘镜像、
更名迁移留下的 `.stale`、发给支持人员的一份拷贝。这正是加密要挡的那类泄露。

**它挡不住什么也得说清**:拿得到主机、能读进程环境的人照样解得开 —— 密钥必须能被这个进程读到。
所以这不是"加了密就安全了",而是把「库文件泄露」和「主机被拿下」分成两件事。

密钥**不放在库里**(放在同一个文件里等于把钥匙和锁放进同一个抽屉),按顺序取:

    OPEN_STUDIO_SECRET_KEY   环境变量 —— 服务端部署的答案(systemd/docker/k8s secret)
                             桌面版由 Electron 从系统钥匙串取出后传进来
    <数据目录>/secret.key     0600 的文件 —— 裸跑 uvicorn 时的兜底,只挡"库文件单独泄露"
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import os

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.core import secrets_at_rest
from app.db.models import ProviderCredential, User
from tests.util import fresh_client


def _raw(table: str, column: str, **where) -> str | None:
    """绕过 ORM 直接看盘上存的字节 —— 加密与否只有这一层看得见。"""
    clause = " AND ".join(f"{k} = :{k}" for k in where)
    with engine.begin() as conn:
        return conn.execute(text(f"SELECT {column} FROM {table} WHERE {clause}"), where).scalar()


def _profile(client) -> str:
    made = client.post(
        "/api/settings/providers", json={"name": "OpenAI", "vendor": "openai", "config": {"api_key": "sk-PLAINTEXT-1234"}}
    )
    assert made.status_code == 200, made.text
    return made.json()["id"]


# ---------------- 盘上是密文 ----------------


def test_an_api_key_is_not_readable_in_the_database_file() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _profile(client)

    stored = _raw("provider_credentials", "api_key", profile_id=profile_id)
    assert stored, "没存进去"
    assert "sk-PLAINTEXT-1234" not in str(stored), f"密钥在盘上是明文:{stored!r}"


def test_it_round_trips_through_the_orm() -> None:
    """加密不能只是"看不懂了" —— 读回来必须是原文,否则等于把密钥弄丢了。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _profile(client)

    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        row = db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id})
        assert row.api_key == "sk-PLAINTEXT-1234"


def test_the_oauth_credential_is_encrypted_too() -> None:
    """订阅计划的 access/refresh 是长期凭据,比 API Key 更值钱。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _profile(client)
    credential = {"type": "oauth", "access": "eyJACCESS", "refresh": "REFRESH-TOKEN"}

    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        row = db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id})
        row.oauth_credential = credential
        db.commit()

    stored = str(_raw("provider_credentials", "oauth_credential", profile_id=profile_id))
    assert "REFRESH-TOKEN" not in stored, f"刷新令牌在盘上是明文:{stored[:80]}"

    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        assert db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id}).oauth_credential == credential


def test_every_secret_bearing_column_is_encrypted() -> None:
    """棘轮:哪些列装秘密,写在一处;新加一个装秘密的列而没加密,这里直接红。"""
    from app.db.models import Base

    unprotected: list[str] = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if (table.name, column.name) not in secrets_at_rest.ENCRYPTED_COLUMNS:
                continue
            if not isinstance(column.type, (secrets_at_rest.EncryptedText, secrets_at_rest.EncryptedJSON)):
                unprotected.append(f"{table.name}.{column.name}")
    assert not unprotected, f"这些列登记为装秘密,却没用加密类型:{unprotected}"


# ---------------- 主密钥不在库里 ----------------


def test_the_master_key_never_lands_in_the_database() -> None:
    """钥匙和锁放进同一个抽屉等于没锁。"""
    key = secrets_at_rest.master_key()
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
        for table in tables:
            columns = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
            for column in columns:
                found = conn.execute(
                    text(f"SELECT 1 FROM {table} WHERE CAST({column} AS TEXT) LIKE :k LIMIT 1"),
                    {"k": f"%{key.decode()}%"},
                ).scalar()
                assert not found, f"主密钥出现在 {table}.{column}"


def test_the_environment_wins_over_the_key_file(monkeypatch, tmp_path) -> None:
    """服务端部署把密钥交给编排系统(systemd/docker secret),而不是让它躺在数据目录里。"""
    from cryptography.fernet import Fernet

    supplied = Fernet.generate_key()
    monkeypatch.setenv("OPEN_STUDIO_SECRET_KEY", supplied.decode())
    secrets_at_rest.master_key.cache_clear()
    try:
        assert secrets_at_rest.master_key() == supplied
    finally:
        secrets_at_rest.master_key.cache_clear()


def test_the_key_file_is_not_world_readable() -> None:
    """兜底的密钥文件只挡"库文件单独泄露" —— 至少别让同机别的用户直接读走。"""
    path = secrets_at_rest.key_path()
    secrets_at_rest.master_key.cache_clear()
    secrets_at_rest.master_key()
    assert path.is_file()
    assert oct(path.stat().st_mode)[-3:] == "600", oct(path.stat().st_mode)


# ---------------- 解不开的时候 ----------------


def test_an_unreadable_secret_reads_as_absent_instead_of_garbage(monkeypatch) -> None:
    """密钥换了或丢了 → 那份凭据读成「没配置」,而不是把密文当密钥发给供应商。

    **fail closed**:用户会看到"请先配置密钥",而不是一次看不懂的 401,更不是把一段密文
    发到别人的端点上。
    """
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _profile(client)

    from cryptography.fernet import Fernet

    monkeypatch.setenv("OPEN_STUDIO_SECRET_KEY", Fernet.generate_key().decode())
    secrets_at_rest.master_key.cache_clear()
    try:
        with SessionLocal() as db:
            me = db.query(User).order_by(User.created_at).first()
            row = db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id})
            assert row.api_key == ""
    finally:
        secrets_at_rest.master_key.cache_clear()


# ---------------- 迁移 ----------------


def test_the_migration_encrypts_what_is_already_there() -> None:
    """老库里躺着的明文得被就地加密 —— 升级之后盘上不该还留着看得懂的密钥。"""
    from app.db.migrations import _migrate_encrypt_secrets

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _profile(client)

    # 退回加密前的形状:直接写明文进去。
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE provider_credentials SET api_key = :v WHERE profile_id = :p"),
            {"v": "sk-LEGACY-PLAINTEXT", "p": profile_id},
        )

    _migrate_encrypt_secrets()

    stored = str(_raw("provider_credentials", "api_key", profile_id=profile_id))
    assert "sk-LEGACY-PLAINTEXT" not in stored, "迁移没有加密老数据"
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        assert db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id}).api_key == "sk-LEGACY-PLAINTEXT"


def test_the_migration_is_idempotent() -> None:
    """跑两次不该把密文再加密一层。"""
    from app.db.migrations import _migrate_encrypt_secrets

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _profile(client)

    _migrate_encrypt_secrets()
    _migrate_encrypt_secrets()

    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        assert db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id}).api_key == "sk-PLAINTEXT-1234"
