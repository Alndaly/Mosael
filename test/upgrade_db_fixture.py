"""Build and verify the oldest supported (v1.9.11) database for the packaged upgrade smoke.

The fixture owns only facts required by the remaining rolling-window migrations. Table shapes
come from the real v1.9.11 schema baseline; explicit rows exercise the migrations that still
transform old data, rather than succeeding only on an empty install.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[1] / "backend" / "tests" / "schema_baseline.json"
NOW = "2026-01-01 00:00:00"


def seed(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    database = data_dir / "mosael.db"
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    with sqlite3.connect(database) as db:
        for table, columns in baseline.items():
            declared = ", ".join(
                f'"{column}" TEXT' + (" PRIMARY KEY" if column == "id" else "") for column in columns
            )
            db.execute(f'CREATE TABLE "{table}" ({declared})')

        db.execute(
            "INSERT INTO publish_tasks (id, workspace_id, account_id, asset_id, title, description, tags, "
            "short_title, options, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-task", "legacy-workspace", "legacy-account", "legacy-asset", "Legacy title", "",
             "[]", "", "{}", "prepared", NOW, NOW),
        )
        graph = {"nodes": [{"id": "publish-1", "type": "publish", "config": {}}], "edges": []}
        db.execute(
            "INSERT INTO workflows (id, workspace_id, name, description, graph, revision, graph_hash, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-workflow", "legacy-workspace", "Legacy workflow", "", json.dumps(graph), "1", "", NOW, NOW),
        )
        for row_id in ("old-first", "old-second"):
            db.execute(
                "INSERT INTO tool_confirmations (id, workspace_id, session_id, tool_call_id, tool, permission, "
                "summary, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row_id, "legacy-workspace", "legacy-session", "legacy-call", "run_workflow", "edit", "", "pending", NOW),
            )
        db.execute(
            "INSERT INTO agent_questions (id, workspace_id, session_id, questions, answers, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-question", "legacy-workspace", "legacy-session", "[]", "[]", "pending", NOW),
        )
        db.execute("PRAGMA user_version = 0")


def verify(data_dir: Path) -> None:
    database = data_dir / "mosael.db"
    with sqlite3.connect(database) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "cloud_login" not in tables:
            raise SystemExit("upgrade failed: cloud_login is missing")

        columns = {row[1] for row in db.execute("PRAGMA table_info(publish_tasks)")}
        if not {"content_kind", "asset_ids", "body", "media_meta"} <= columns:
            raise SystemExit(f"upgrade failed: publish_tasks columns are {sorted(columns)}")
        content_kind, asset_ids, body, media_meta = db.execute(
            "SELECT content_kind, asset_ids, body, media_meta FROM publish_tasks WHERE id = 'legacy-task'"
        ).fetchone()
        if (content_kind, json.loads(asset_ids), body, json.loads(media_meta)) != ("video", ["legacy-asset"], "", {}):
            raise SystemExit(
                "upgrade failed: publish task is "
                f"{(content_kind, asset_ids, body, media_meta)!r}"
            )

        question_columns = {row[1] for row in db.execute("PRAGMA table_info(agent_questions)")}
        if "feishu_message_id" not in question_columns:
            raise SystemExit("upgrade failed: agent_questions.feishu_message_id is missing")
        confirmation_columns = {row[1] for row in db.execute("PRAGMA table_info(tool_confirmations)")}
        if "feishu_message_id" not in confirmation_columns:
            raise SystemExit("upgrade failed: tool_confirmations.feishu_message_id is missing")
        indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        if "uq_tool_confirmations_session_tool_call" not in indexes:
            raise SystemExit("upgrade failed: confirmation idempotency index is missing")
        linked = [row[0] for row in db.execute(
            "SELECT tool_call_id FROM tool_confirmations ORDER BY rowid"
        )]
        if linked != ["legacy-call", None]:
            raise SystemExit(f"upgrade failed: duplicate confirmation links are {linked!r}")

        graph = json.loads(db.execute("SELECT graph FROM workflows WHERE id = 'legacy-workflow'").fetchone()[0])
        if graph["nodes"][0]["config"].get("content_kind") != "video":
            raise SystemExit("upgrade failed: workflow publish node has no content_kind")
        profile_columns = {row[1] for row in db.execute("PRAGMA table_info(browser_profiles)")}
        if "identity" not in profile_columns:
            raise SystemExit("upgrade failed: browser_profiles.identity is missing")
        deployment_columns = {row[1] for row in db.execute("PRAGMA table_info(deployment_config)")}
        if "update_feed_url" not in deployment_columns:
            raise SystemExit("upgrade failed: deployment_config.update_feed_url is missing")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("usage: upgrade_db_fixture.py seed|verify DATA_DIR")
    globals()[sys.argv[1]](Path(sys.argv[2]))
