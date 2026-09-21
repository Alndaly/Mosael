from __future__ import annotations

import sqlite3

from app.core.config import settings
from app.db.migrations import init_db
from app.db.safety import DATABASE_SCHEMA_VERSION
from tests.test_auth import fresh_client


def test_existing_database_is_snapshotted_once_before_schema_upgrade() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "Before upgrade"}).json()
    project = client.post(
        "/api/projects", json={"workspace_id": workspace["id"], "name": "Must survive"}
    ).json()
    snapshots = settings.data_dir / ".maintenance" / "database-snapshots"
    before = set(snapshots.glob("*.sqlite")) if snapshots.exists() else set()
    with sqlite3.connect(settings.db_path) as database:
        database.execute("PRAGMA user_version = 0")
        database.commit()

    init_db()

    created = set(snapshots.glob("*.sqlite")) - before
    assert len(created) == 1
    snapshot = created.pop()
    with sqlite3.connect(snapshot) as database:
        assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert database.execute("select name from projects where id = ?", (project["id"],)).fetchone() == (
            "Must survive",
        )
    with sqlite3.connect(settings.db_path) as database:
        assert database.execute("PRAGMA user_version").fetchone() == (DATABASE_SCHEMA_VERSION,)

    init_db()

    assert set(snapshots.glob("*.sqlite")) - before == {snapshot}


def test_版本号相等但还有迁移要跑时_照样先拍快照(tmp_path) -> None:
    """**这道保险此前一直是关着的。**

    判据原本是 `current_version == DATABASE_SCHEMA_VERSION` 就不拍。而那个常量自 2026-09-04
    起没被 bump 过,其间新增了十四个迁移 —— 含一次 `DROP TABLE` 加搬文件。于是每台已经升到
    v3 的机器,后面所有迁移都在**没有备份**的情况下跑。机制没坏,开关关着。

    靠人记得改一个数才生效的保险,迟早会在它最该生效的那次是关着的。所以判据改成"有没有
    待跑的一次性迁移" —— 这个数不用人记。
    """
    import sqlite3

    from app.db.safety import DATABASE_SCHEMA_VERSION, mark_database_version, snapshot_before_upgrade

    database = tmp_path / "mosael.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE things (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO things VALUES ('keep me')")
    mark_database_version(database, DATABASE_SCHEMA_VERSION)

    # 版本号一样 + 没有待跑的迁移 = 普通重启,不该拍。
    assert snapshot_before_upgrade(database, target_version=DATABASE_SCHEMA_VERSION, pending=0) is None
    # 版本号一样,但确实有迁移要跑 —— 这正是此前漏掉的那一档。
    snapshot = snapshot_before_upgrade(database, target_version=DATABASE_SCHEMA_VERSION, pending=1)
    assert snapshot is not None and snapshot.is_file()
    with sqlite3.connect(snapshot) as copy:
        assert copy.execute("SELECT id FROM things").fetchone() == ("keep me",)


def test_待跑的迁移由记账本回答_不由常量回答() -> None:
    """`MigrationPlan.pending()` 才是那个判据。空计划没有待跑项;真实计划在一个从没迁移过的
    库上,待跑项必须非空 —— 否则线上第一次启动同样不会拍快照。"""
    from app.db.migration_runner import MigrationPhase, MigrationPlan, MigrationStep

    empty = MigrationPlan([])
    assert empty.pending() == ()

    ran: list[str] = []
    plan = MigrationPlan([
        MigrationStep("只跑一次的", MigrationPhase.BEFORE_SCHEMA, lambda: ran.append("once")),
        MigrationStep("每次都跑的", MigrationPhase.AFTER_SCHEMA, lambda: ran.append("always"), once=False),
    ])
    # 对账步骤不算"要改数据形状",不该把快照拖起来。
    assert plan.pending() == ("只跑一次的",)
    plan.run()
    assert plan.pending() == ()
