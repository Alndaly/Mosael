"""供应商 adapter 配置。

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloud_upstream_providers",
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("cloud_upstream_providers", "config")
