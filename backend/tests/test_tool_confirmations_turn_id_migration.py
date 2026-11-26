"""确认卡记录所属轮次:老库升级后必须有 `turn_id` 列,重复跑不再改动。"""

from __future__ import annotations

import sqlite3

from app.core.config import settings
from app.db.migrations import _migrate_tool_confirmations_turn_id
from tests.test_schema_migrations_cover_the_models import _build_baseline_database
from tests.util import fresh_client


def test_旧库补上确认卡的_turn_id_列() -> None:
    fresh_client()
    database = settings.db_path
    _build_baseline_database(database, seeded=False)

    _migrate_tool_confirmations_turn_id()
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info("tool_confirmations")')}
    assert "turn_id" in columns

    _migrate_tool_confirmations_turn_id()
    with sqlite3.connect(database) as connection:
        columns_again = {row[1] for row in connection.execute('PRAGMA table_info("tool_confirmations")')}
    assert columns_again == columns
