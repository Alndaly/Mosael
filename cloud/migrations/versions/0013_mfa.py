"""MosaelCloud 可选 TOTP 双因素:用户 secret、登录票据、恢复码。

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cloud_users") as batch:
        batch.add_column(sa.Column("mfa_totp_secret_encrypted", sa.String(500), nullable=True))
        batch.add_column(sa.Column("mfa_pending_secret_encrypted", sa.String(500), nullable=True))
        batch.add_column(sa.Column("mfa_pending_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("mfa_enabled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("mfa_last_used_step", sa.Integer(), nullable=True))
    op.create_table(
        "cloud_mfa_tickets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("ticket_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("cloud_mfa_tickets") as batch:
        batch.create_index("idx_cloud_mfa_tickets_expires", ["expires_at"], unique=False)
    op.create_table(
        "cloud_mfa_recovery_codes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("cloud_mfa_recovery_codes") as batch:
        batch.create_index("idx_cloud_mfa_recovery_user", ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("cloud_mfa_recovery_codes") as batch:
        batch.drop_index("idx_cloud_mfa_recovery_user")
    op.drop_table("cloud_mfa_recovery_codes")
    with op.batch_alter_table("cloud_mfa_tickets") as batch:
        batch.drop_index("idx_cloud_mfa_tickets_expires")
    op.drop_table("cloud_mfa_tickets")
    with op.batch_alter_table("cloud_users") as batch:
        batch.drop_column("mfa_last_used_step")
        batch.drop_column("mfa_enabled_at")
        batch.drop_column("mfa_pending_expires_at")
        batch.drop_column("mfa_pending_secret_encrypted")
        batch.drop_column("mfa_totp_secret_encrypted")
