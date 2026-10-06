"""本机服务第三步(ADR 0041 §6 第 3 步)的加列迁移。老库里已有的行留着,新列落成「没有」—— 和升级前一样;再跑一次什么都不做。

- `_migrate_local_services_share_model_folders`:`shared_models`(共用的模型文件夹),老行是 `[]`;
- `_migrate_local_services_stop_when_idle`:`idle_stop_minutes`(闲置多久自动停),老行按缺省 30。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from tests.util import fresh_client


def _columns(table: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _old_table() -> None:
    """第二步时的那张表(没有第三步的列),和一行「让 Mosael 装」的。"""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE local_services"))
        conn.execute(text(
            "CREATE TABLE local_services (instance_id VARCHAR PRIMARY KEY, service VARCHAR(40) NOT NULL, "
            "mode VARCHAR(16) NOT NULL, directory TEXT NOT NULL, python TEXT NOT NULL, port INTEGER NOT NULL UNIQUE, "
            "listen_lan BOOLEAN NOT NULL, keep_running BOOLEAN NOT NULL, extra_args JSON NOT NULL, "
            "python_minor VARCHAR(16) NOT NULL DEFAULT '', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(text(
            "INSERT INTO local_services VALUES ('i1', 'comfyui', 'managed', '/data/local-services/i1', '', 8189, 0, 0, "
            "'[]', '3.13', '2026-10-06 00:00:00', '2026-10-06 00:00:00')"))


def test_老库的本机服务补上_shared_models_老行没有共用的() -> None:
    from app.db.migrations import _migrate_local_services_share_model_folders

    fresh_client()
    _old_table()
    assert "shared_models" not in _columns("local_services")
    _migrate_local_services_share_model_folders()
    with engine.connect() as conn:
        mode, minor, shared = conn.execute(text("SELECT mode, python_minor, shared_models FROM local_services")).one()
    assert (mode, minor, json.loads(shared)) == ("managed", "3.13", [])
    _migrate_local_services_share_model_folders()  # 再跑一次不报 duplicate column


def test_老库的本机服务补上_idle_stop_minutes_老行按缺省_30_分钟() -> None:
    from app.db.migrations import _migrate_local_services_stop_when_idle

    fresh_client()
    _old_table()
    assert "idle_stop_minutes" not in _columns("local_services")
    _migrate_local_services_stop_when_idle()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT mode, idle_stop_minutes FROM local_services")).one() == ("managed", 30)
    _migrate_local_services_stop_when_idle()


def test_没有本机服务那张表的老库_不建半张() -> None:
    from app.db.migrations import _migrate_local_services_share_model_folders, _migrate_local_services_stop_when_idle

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE local_services"))
    _migrate_local_services_share_model_folders()
    _migrate_local_services_stop_when_idle()
    assert _columns("local_services") == set()
