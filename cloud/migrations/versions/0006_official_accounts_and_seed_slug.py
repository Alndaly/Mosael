"""官方账号:`cloud_users.official`,`cloud_shares.slug`(种子命令的稳定去重键)。

**为什么另起 0006、不并进 0005:** 0005 只做"kind 的 CHECK 加 plugin"这一件事,和分享类型
绑定;`official` 属于账号,`slug` 属于"种子命令怎么认出自己上次写的那一行",两者是同一笔
"官方内容"落地的两部分,回退时也要一起回到 0004 的形状。拆开也让每支迁移只回答一个问题。

- `official` NOT NULL DEFAULT false:已有账号升级后就是 false,不猜谁是官方号。
- `slug` 可空:用户分享没有它;`(owner_user_id, kind, slug)` 唯一索引让重复跑种子不会多出行。
  多条 NULL 在 SQLite 与 PostgreSQL 上都不冲突。

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cloud_users") as batch:
        batch.add_column(
            sa.Column("official", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("cloud_shares") as batch:
        batch.add_column(sa.Column("slug", sa.String(length=80), nullable=True))
        batch.create_index(
            "uq_cloud_shares_owner_kind_slug", ["owner_user_id", "kind", "slug"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("cloud_shares") as batch:
        batch.drop_index("uq_cloud_shares_owner_kind_slug")
        batch.drop_column("slug")
    with op.batch_alter_table("cloud_users") as batch:
        batch.drop_column("official")
