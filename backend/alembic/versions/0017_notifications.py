"""in-app notifications

Revision ID: 0017_notifications
Revises: 0016_publish_worker
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_notifications"
down_revision = "0016_publish_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False, server_default="system"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.String(200), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
