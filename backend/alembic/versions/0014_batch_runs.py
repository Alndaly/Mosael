"""batch_runs table

Revision ID: 0014_batch_runs
Revises: 0013_workflows
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_batch_runs"
down_revision = "0013_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("params_list", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_job_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_batch_runs_workspace", "batch_runs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("idx_batch_runs_workspace", table_name="batch_runs")
    op.drop_table("batch_runs")
