"""账号封禁:记录时间与原因,封禁时撤掉已有会话 / 设备令牌。

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cloud_users", sa.Column("banned_at", sa.DateTime(), nullable=True))
    op.add_column(
        "cloud_users",
        sa.Column("ban_reason", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("cloud_users", "ban_reason")
    op.drop_column("cloud_users", "banned_at")
