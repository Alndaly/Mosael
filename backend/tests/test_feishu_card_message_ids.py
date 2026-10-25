"""卡片消息 id 的 schema 与迁移入口。

`migrate-tool-confirmations-feishu-message-id` 和 `migrate-agent-questions-feishu-message-id`
给两张已有表补 `feishu_message_id`;没有它,回调超时 / 应用内处理 / 过期就不能收回原卡。
"""

from __future__ import annotations

from sqlalchemy import inspect

from app.core.db import engine


def test_卡片表都有飞书消息_id_列() -> None:
    inspector = inspect(engine)
    for table in ("tool_confirmations", "agent_questions"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "feishu_message_id" in columns, table
