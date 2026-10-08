"""棘轮:**加了一次性迁移,`DATABASE_SCHEMA_VERSION` 就要加一** —— 老版本靠它拒绝打开新版本迁过的库。

老版本手里只有一个判据:库的 `user_version` 比它认得的大就拒绝启动(db/safety.snapshot_before_upgrade)。它认不出
新加的迁移名,也不该去认。所以新版本每改一次数据的形状,这个数就得往上走一格;此前它从 2026-09-22 起停在 4,
其间加了几十步迁移,用 v1.9.3 打开 main 迁过的库:`init_db` 照常通过,智能体页随即 `no such column: agent_sessions.project_id`。

快照在 `tests/schema_version.json`:这个数**当时**认得的那几步一次性迁移。多出新的一步而数没动 → 红;数动了而快照
没跟上 → 红(跑 `python -m tests.freeze_migration_bodies`,它连指纹一起写)。
"""

from __future__ import annotations

# 进 docs/CONVENTIONS.md 的棘轮清单(scripts/sync-ratchet-docs.py 生成)。
RATCHET = True

import json
import pathlib
import sqlite3

import pytest

from app.db import migrations
from app.db.migrations import migration_plan
from app.db.safety import DATABASE_SCHEMA_VERSION, DatabaseVersionTooNew

SNAPSHOT = pathlib.Path(__file__).parent / "schema_version.json"


def once_steps() -> list[str]:
    return sorted(step.name for step in migration_plan().steps if step.once)


def test_a_new_one_time_migration_comes_with_a_new_schema_version() -> None:
    recorded = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if DATABASE_SCHEMA_VERSION == recorded["version"]:
        added = sorted(set(once_steps()) - set(recorded["steps"]))
        assert not added, (
            "加了一次性迁移而 DATABASE_SCHEMA_VERSION 没动 —— 老版本会照常打开迁过的库,读到它认不得的形状就坏:\n  "
            + "\n  ".join(added)
            + "\n把 app/db/safety.DATABASE_SCHEMA_VERSION 加一,再跑 `python -m tests.freeze_migration_bodies`。"
        )
        return
    assert DATABASE_SCHEMA_VERSION == recorded["version"] + 1, (
        f"DATABASE_SCHEMA_VERSION 是 {DATABASE_SCHEMA_VERSION},快照记的是 {recorded['version']}:一次只往上加一。"
    )
    raise AssertionError("DATABASE_SCHEMA_VERSION 加过了,快照还没跟上:跑 `python -m tests.freeze_migration_bodies`。")


def test_an_older_build_refuses_a_database_this_build_migrated(monkeypatch) -> None:
    """一个只认得上一个版本号的构建,打开这一版迁过的库时拒绝启动,而不是照常跑。"""
    from app.core.config import settings
    from tests.util import fresh_client

    fresh_client()  # init_db 跑过:库是这一版的形状,user_version 是这一版的数
    with sqlite3.connect(settings.db_path) as database:
        assert database.execute("PRAGMA user_version").fetchone() == (DATABASE_SCHEMA_VERSION,)
    monkeypatch.setattr(migrations, "DATABASE_SCHEMA_VERSION", DATABASE_SCHEMA_VERSION - 1)
    with pytest.raises(DatabaseVersionTooNew):
        migrations.init_db()
