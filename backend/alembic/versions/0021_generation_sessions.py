"""generation sessions

Revision ID: 0021_generation_sessions
Revises: 0020_account_proxy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_generation_sessions"
down_revision = "0020_account_proxy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_sessions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="新生成"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_generation_sessions_ws_updated", "generation_sessions", ["workspace_id", "updated_at"])
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(
            sa.Column(
                "session_id",
                sa.String(64),
                sa.ForeignKey("generation_sessions.id", ondelete="CASCADE"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("session_id")
    op.drop_index("idx_generation_sessions_ws_updated", table_name="generation_sessions")
    op.drop_table("generation_sessions")
