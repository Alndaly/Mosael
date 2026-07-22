"""oauth identities (Google / Apple 登录 → 本地账号映射)

Revision ID: 0029_oauth_identities
Revises: 0028_workspace_invitations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_oauth_identities"
down_revision = "0028_workspace_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_identities",
        sa.Column("provider", sa.String(length=20), primary_key=True),
        sa.Column("subject", sa.String(length=255), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_identities")
