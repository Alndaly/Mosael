"""把通知列表索引归一成普通索引 —— 修掉只在真 Postgres 上出现的漂移。

`0003` 建的是 `(recipient_id, created_at DESC)`。B-tree 索引本身就能反向扫,排序方向
不改变它"按 recipient_id 取、按 created_at 排"这件事,所以 `DESC` 只是装饰;但它是**表达式**,
而模型里那条 `Index(...)` 声明的是普通列 —— 真 Postgres 的 `alembic check` 因此一直把它们
算成两个不同的索引(先 remove 再 add),"零漂移"只在 SQLite 上成立(SQLite 的反射不保留方向)。

这里把它重建成普通 `(recipient_id, created_at)`(与模型、与 SQLite 现状一致),
不是改模型去迁就装饰性语法。列表查询的语义和查询计划都不变。

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "cloud_share_notifications"
NAME = "idx_cloud_share_notifications_recipient_created"


def upgrade() -> None:
    op.drop_index(NAME, table_name=TABLE)
    op.create_index(NAME, TABLE, ["recipient_id", "created_at"])


def downgrade() -> None:
    op.drop_index(NAME, table_name=TABLE)
    op.execute(f"CREATE INDEX {NAME} ON {TABLE} (recipient_id, created_at DESC)")
