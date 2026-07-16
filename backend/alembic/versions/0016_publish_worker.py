"""browser-platform publish: task rich status + account binding

Revision ID: 0016_publish_worker
Revises: 0015_publish
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_publish_worker"
down_revision = "0015_publish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_accounts", sa.Column("binding_status", sa.String(40), nullable=False, server_default="unknown"))
    op.add_column("publish_accounts", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("publish_accounts", sa.Column("last_checked_at", sa.DateTime(), nullable=True))
    op.add_column("publish_tasks", sa.Column("short_title", sa.String(80), nullable=False, server_default=""))
    op.add_column("publish_tasks", sa.Column("status", sa.String(40), nullable=False, server_default="pending"))
    op.add_column("publish_tasks", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("publish_tasks", sa.Column("screenshot_path", sa.Text(), nullable=True))
    op.add_column("publish_tasks", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for column in ("updated_at", "screenshot_path", "error_message", "status", "short_title"):
        op.drop_column("publish_tasks", column)
    for column in ("last_checked_at", "last_error", "binding_status"):
        op.drop_column("publish_accounts", column)
