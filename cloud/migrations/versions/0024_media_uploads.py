"""任务输入素材上传。

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_media_uploads",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("mime", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("public_token", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cloud_media_uploads")
