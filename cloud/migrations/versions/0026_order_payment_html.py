"""订单保存电脑网站支付表单。

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cloud_orders", sa.Column("payment_html", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cloud_orders", "payment_html")
