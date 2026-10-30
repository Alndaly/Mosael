"""MosaelCloud 管理操作审计。

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_admin_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor_user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("cloud_admin_audit") as batch:
        batch.create_index("idx_cloud_admin_audit_created", ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("cloud_admin_audit") as batch:
        batch.drop_index("idx_cloud_admin_audit_created")
    op.drop_table("cloud_admin_audit")
