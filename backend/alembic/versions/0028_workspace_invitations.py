"""workspace invitations (邀请制成员加入)

Revision ID: 0028_workspace_invitations
Revises: 0027_usage_ledger
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_workspace_invitations"
down_revision = "0027_usage_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("workspace_id", sa.String(length=64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inviter_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invitee_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False, server_default="editor"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_ws_invitations_invitee_status", "workspace_invitations", ["invitee_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_ws_invitations_invitee_status", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
