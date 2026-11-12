"""订单退款登记。

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cloud_orders", sa.Column("refunded_at", sa.DateTime(), nullable=True))
    op.add_column("cloud_orders", sa.Column("refund_cents", sa.Integer(), nullable=True))
    op.add_column("cloud_orders", sa.Column("refund_note", sa.String(300), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("cloud_orders", "refund_note")
    op.drop_column("cloud_orders", "refund_cents")
    op.drop_column("cloud_orders", "refunded_at")
