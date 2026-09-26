"""Build and verify the smallest supported pre-upgrade database used by the packaged smoke.

This fixture deliberately owns only facts required by the upgrade contract. ``create_all`` must
build everything else; historical publish-task and board shapes prove that startup migrations
upgrade both table schemas and JSON data rather than succeeding only on a clean install.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def seed(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    database = data_dir / "mosael.db"
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

            CREATE TABLE boards (
                id VARCHAR(64) PRIMARY KEY,
                workspace_id VARCHAR(64) NOT NULL,
                name VARCHAR(180) NOT NULL,
                canvas JSON NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            INSERT INTO boards (id, workspace_id, name, canvas, created_at, updated_at)
            VALUES (
                'legacy-board', 'legacy-workspace', 'Legacy board',
                '{"items":[{"id":"image-1","kind":"image","x":0,"y":0,"text":"old prompt","job_id":"job-1"},{"id":"note-1","kind":"note","x":0,"y":300,"text":"hello"},{"id":"tool-1","kind":"action","x":300,"y":300,"form":{"producer":"node:translate","config":{"target_lang":"en"},"bindings":{"text":[{"from":"note-1"}]}}}],"edges":[{"id":"e1","source":"note-1","target":"tool-1"}]}',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            """
        )


def verify(data_dir: Path) -> None:
    database = data_dir / "mosael.db"
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
        canvas = db.execute("SELECT canvas FROM boards WHERE id = 'legacy-board'").fetchone()[0]
        board = json.loads(canvas) if isinstance(canvas, str) else canvas
        item = board["items"][0]
        if item.get("run") != {"status": "running", "job_id": "job-1"}:
            raise SystemExit(f"upgrade failed: board run state is {item.get('run')!r}")
        if item.get("form") != {"prompt": "old prompt", "producer": "generate"}:
            raise SystemExit(f"upgrade failed: board form is {item.get('form')!r}")
        if "job_id" in item or "error" in item:
            raise SystemExit(f"upgrade failed: board kept legacy state fields: {item!r}")
        # 画板上的工具格撤下(migrate-board-tool-cells-become-abilities):翻译搬成它接着的那张便签的一项能力。
        by_id = {one["id"]: one for one in board["items"]}
        if "tool-1" in by_id or any(one.get("kind") == "action" for one in board["items"]):
            raise SystemExit(f"upgrade failed: a tool item is still on the board: {board['items']!r}")
        abilities = (by_id["note-1"].get("form") or {}).get("abilities")
        if abilities != {"node:translate": {"config": {"target_lang": "en"}, "bindings": {}}}:
            raise SystemExit(f"upgrade failed: the note's abilities are {abilities!r}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("usage: upgrade_db_fixture.py seed|verify DATA_DIR")
    globals()[sys.argv[1]](Path(sys.argv[2]))
