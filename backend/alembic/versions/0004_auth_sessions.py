"""auth sessions table

Revision ID: 0004_auth_sessions
Revises: 0003_transcripts
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_auth_sessions"
down_revision = "0003_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("token", sa.String(80), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_auth_sessions_user", "auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
