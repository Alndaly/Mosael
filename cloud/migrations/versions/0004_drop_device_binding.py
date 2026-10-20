"""拆掉云端设备绑定:删掉 `cloud_device_codes` 与 `cloud_devices` 两张表。

维护者的方向是**不需要云端设备绑定机制**。表、模型、路由一起删,没有兼容分支:

- `cloud_devices` 只存桌面端绑定的设备凭据哈希;
- `cloud_device_codes` 只存一次设备码授权(`user_code` / `device_code_hash` / 谁确认的)。

两张表都只为绑定而存在,删掉之后账号、会话与社区分享不受影响。downgrade 按 0001 的形状
把表建回来 —— 它是一次迁移的回退路径,不是运行时兼容分支。

已有库升级:

    uv run python -m cloud.cli migrate

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 两张表都只指向 `cloud_users`,彼此之间没有外键;先删码表再删设备表。
    op.drop_table("cloud_device_codes")
    op.drop_table("cloud_devices")


def downgrade() -> None:
    op.create_table(
        "cloud_device_codes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_code", sa.String(length=9), nullable=False),
        sa.Column("device_code_hash", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_code"),
        sa.UniqueConstraint("device_code_hash"),
    )
    with op.batch_alter_table("cloud_device_codes") as batch:
        batch.create_index("idx_cloud_device_codes_user", ["user_id"], unique=False)
        batch.create_index("idx_cloud_device_codes_expires", ["expires_at"], unique=False)

    op.create_table(
        "cloud_devices",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("cloud_devices") as batch:
        batch.create_index("idx_cloud_devices_user", ["user_id"], unique=False)
