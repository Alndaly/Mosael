"""tool confirmations table

Revision ID: 0007_tool_confirmations
Revises: 0006_scheduled_task_last_run
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_tool_confirmations"
down_revision = "0006_scheduled_task_last_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_confirmations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("permission", sa.String(40), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(120), nullable=False, server_default="external-agent"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_tool_confirmations_ws_status", "tool_confirmations", ["workspace_id", "status"])


def downgrade() -> None:
    op.drop_table("tool_confirmations")
