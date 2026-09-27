"""资产条目(ADR 0027 阶段 3):items 加一列 asset_kind,资产列表按人物 / 场景 / 道具筛。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27 18:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("asset_kind", sa.String(length=16), nullable=True))
        batch.create_index("ix_items_asset_kind", ["asset_kind"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_index("ix_items_asset_kind")
        batch.drop_column("asset_kind")
