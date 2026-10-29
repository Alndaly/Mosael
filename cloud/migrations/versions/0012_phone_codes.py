"""手机号验证码登录。

`cloud_users.email` 改为可空(手机号账号没有邮箱),新增 `phone` / `phone_verified_at`;
新增 `cloud_phone_codes`,阈值与邮箱验证码一致(10 分钟 TTL / 5 次错误 / 60 秒重发冷却)。

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("cloud_users") as batch:
        batch.alter_column("email", existing_type=sa.String(320), nullable=True)
        batch.add_column(sa.Column("phone", sa.String(32), nullable=True))
        batch.add_column(sa.Column("phone_verified_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_cloud_users_phone", ["phone"], unique=True)
    op.create_table(
        "cloud_phone_codes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("request_ip", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("cloud_phone_codes") as batch:
        batch.create_index("ix_cloud_phone_codes_phone", ["phone"], unique=False)
        batch.create_index("idx_cloud_phone_codes_lookup", ["phone", "purpose", "created_at"], unique=False)
        batch.create_index("idx_cloud_phone_codes_ip", ["request_ip", "created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("cloud_phone_codes") as batch:
        batch.drop_index("idx_cloud_phone_codes_ip")
        batch.drop_index("idx_cloud_phone_codes_lookup")
        batch.drop_index("ix_cloud_phone_codes_phone")
    op.drop_table("cloud_phone_codes")
    with op.batch_alter_table("cloud_users") as batch:
        batch.drop_index("ix_cloud_users_phone")
        batch.drop_column("phone_verified_at")
        batch.drop_column("phone")
        #: 手机号账号没有邮箱;有这类账号时必须先手工处理,不能让降级悄悄删号。
        batch.alter_column("email", existing_type=sa.String(320), nullable=False)
