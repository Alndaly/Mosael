"""桌面端设备令牌:`cloud_device_tokens`(ADR 0088 第 1 步)。

网关只认这枚令牌。它由桌面端在登录之后用会话换取,和 0004 拆掉的「设备绑定」(设备码 + 官网确认)
不是一回事 —— 那两张表不回来。

已有库升级:

    uv run python -m cloud.cli migrate

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "cloud_device_tokens"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("cloud_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_cloud_device_tokens_user", TABLE, ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_cloud_device_tokens_user", table_name=TABLE)
    op.drop_table(TABLE)
