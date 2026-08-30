"""Build and verify the smallest supported pre-upgrade database used by the packaged smoke.

This fixture deliberately owns only facts required by the upgrade contract. ``create_all`` must
build everything else; the historical ``publish_tasks`` table proves that startup migrations add
columns to an existing table rather than succeeding only on a clean install.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def seed(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    database = data_dir / "open-studio.db"
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE publish_tasks (
                id VARCHAR(64) PRIMARY KEY,
                workspace_id VARCHAR(64) NOT NULL,
                account_id VARCHAR(64) NOT NULL,
                asset_id VARCHAR(64) NOT NULL,
                title VARCHAR(300) NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                tags JSON NOT NULL DEFAULT '[]',
                short_title VARCHAR(80) NOT NULL DEFAULT '',
                status VARCHAR(40) NOT NULL DEFAULT 'pending',
                error_message TEXT,
                screenshot_path TEXT,
                job_id VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            INSERT INTO publish_tasks (
                id, workspace_id, account_id, asset_id, status, created_at, updated_at
            ) VALUES (
                'legacy-task', 'legacy-workspace', 'legacy-account', 'legacy-asset',
                'prepared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            """
        )


def verify(data_dir: Path) -> None:
    database = data_dir / "open-studio.db"
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(publish_tasks)")}
        if "options" not in columns:
            raise SystemExit("upgrade failed: publish_tasks.options was not added")
        status, options = db.execute(
            "SELECT status, options FROM publish_tasks WHERE id = 'legacy-task'"
        ).fetchone()
        if status != "cancelled":
            raise SystemExit(f"upgrade failed: prepared task stayed {status!r}")
        if options not in ("{}", {}):
            raise SystemExit(f"upgrade failed: options default is {options!r}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("usage: upgrade_db_fixture.py seed|verify DATA_DIR")
    globals()[sys.argv[1]](Path(sys.argv[2]))
