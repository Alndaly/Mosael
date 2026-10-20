"""基线:账号、会话、邮箱验证码、设备码、第三方身份、OAuth 中间状态。

这一条对应 0001 之前由 `Base.metadata.create_all` 建出来的形状,一个列都不改。
本次改动(身份列 + 社区分享)在 0002;已有的库先 `stamp 0001` 再升级,新库直接升到 head。

Revision ID: 0001
Revises:
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cloud_users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("cloud_users") as batch:
        batch.create_index("ix_cloud_users_email", ["email"], unique=True)

    op.create_table(
        "cloud_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    with op.batch_alter_table("cloud_sessions") as batch:
        batch.create_index("idx_cloud_sessions_user", ["user_id"], unique=False)

    op.create_table(
        "cloud_email_codes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("cloud_email_codes") as batch:
        batch.create_index("ix_cloud_email_codes_email", ["email"], unique=False)
        batch.create_index("idx_cloud_email_codes_lookup", ["email", "purpose", "created_at"], unique=False)
        batch.create_index("idx_cloud_email_codes_ip", ["request_ip", "created_at"], unique=False)

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
        "cloud_identities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_user_id", sa.String(length=191), nullable=False),
        sa.Column("cloud_user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cloud_user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_cloud_identities_provider_user"),
    )
    with op.batch_alter_table("cloud_identities") as batch:
        batch.create_index("idx_cloud_identities_user", ["cloud_user_id"], unique=False)

    op.create_table(
        "cloud_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("link_user_id", sa.String(length=64), nullable=True),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("return_page", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["link_user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    with op.batch_alter_table("cloud_oauth_states") as batch:
        batch.create_index("idx_cloud_oauth_states_expires", ["expires_at"], unique=False)

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


def downgrade() -> None:
    with op.batch_alter_table("cloud_devices") as batch:
        batch.drop_index("idx_cloud_devices_user")
    op.drop_table("cloud_devices")

    with op.batch_alter_table("cloud_oauth_states") as batch:
        batch.drop_index("idx_cloud_oauth_states_expires")
    op.drop_table("cloud_oauth_states")

    with op.batch_alter_table("cloud_identities") as batch:
        batch.drop_index("idx_cloud_identities_user")
    op.drop_table("cloud_identities")

    with op.batch_alter_table("cloud_device_codes") as batch:
        batch.drop_index("idx_cloud_device_codes_expires")
        batch.drop_index("idx_cloud_device_codes_user")
    op.drop_table("cloud_device_codes")

    with op.batch_alter_table("cloud_email_codes") as batch:
        batch.drop_index("idx_cloud_email_codes_ip")
        batch.drop_index("idx_cloud_email_codes_lookup")
        batch.drop_index("ix_cloud_email_codes_email")
    op.drop_table("cloud_email_codes")

    with op.batch_alter_table("cloud_sessions") as batch:
        batch.drop_index("idx_cloud_sessions_user")
    op.drop_table("cloud_sessions")

    with op.batch_alter_table("cloud_users") as batch:
        batch.drop_index("ix_cloud_users_email")
    op.drop_table("cloud_users")
