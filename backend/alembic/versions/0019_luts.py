"""3D LUT storage

Revision ID: 0019_luts
Revises: 0018_account_profile
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_luts"
down_revision = "0018_account_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "luts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("original_filename", sa.String(260), nullable=False, server_default=""),
        sa.Column("file_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_luts_workspace_created", "luts", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_luts_workspace_created", table_name="luts")
    op.drop_table("luts")
