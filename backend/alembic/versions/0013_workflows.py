"""workflows table

Revision ID: 0013_workflows
Revises: 0012_kb
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_workflows"
down_revision = "0012_kb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("graph", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_workflows_workspace", "workflows", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("idx_workflows_workspace", table_name="workflows")
    op.drop_table("workflows")
