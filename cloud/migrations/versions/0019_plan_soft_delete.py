"""套餐软删除:历史订阅 / 订单仍引用套餐行。

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cloud_plans", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("cloud_plans", "deleted_at")
