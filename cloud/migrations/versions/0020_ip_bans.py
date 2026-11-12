"""来源 IP 封禁。

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_ip_bans",
        sa.Column("ip", sa.String(length=45), primary_key=True),
        sa.Column("reason", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cloud_ip_bans")
