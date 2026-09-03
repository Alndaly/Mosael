from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import settings
from app.db.migrations import init_db
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
        assert database.execute("PRAGMA user_version").fetchone() == (1,)

    init_db()

    assert set(snapshots.glob("*.sqlite")) - before == {snapshot}
