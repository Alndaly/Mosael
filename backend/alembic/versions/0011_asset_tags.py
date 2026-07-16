"""asset tags: free-form label list on assets for filtering/batch organizing

Revision ID: 0011_asset_tags
Revises: 0010_text_clips
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_asset_tags"
down_revision = "0010_text_clips"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("assets", "tags")
