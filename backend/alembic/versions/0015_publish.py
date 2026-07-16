"""publish accounts + tasks

Revision ID: 0015_publish
Revises: 0014_batch_runs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_publish"
down_revision = "0014_batch_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publish_accounts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_publish_accounts_workspace", "publish_accounts", ["workspace_id"])
    op.create_table(
        "publish_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(64), sa.ForeignKey("publish_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(64), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_publish_tasks_workspace", "publish_tasks", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_publish_tasks_workspace", table_name="publish_tasks")
    op.drop_table("publish_tasks")
    op.drop_index("idx_publish_accounts_workspace", table_name="publish_accounts")
    op.drop_table("publish_accounts")
