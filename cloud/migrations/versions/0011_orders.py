"""订单与套餐价格(ADR 0088 第 3 步:国内二维码预付)。

- `cloud_plans` 加 `price_cents`(可空 = 不在线卖,只由管理员开通)与 `currency`(缺省 CNY)。已有套餐价格为空,行为不变;
- 新表 `cloud_orders`:一笔购买(金额是下单那一刻的价、渠道、状态、二维码、渠道交易号、发放了哪个订阅)。

已有库升级:

    uv run python -m cloud.cli migrate

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("cloud_plans") as batch:
        batch.add_column(sa.Column("price_cents", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"))
        batch.create_check_constraint("ck_cloud_plans_price", "price_cents IS NULL OR price_cents > 0")
    op.create_table(
        "cloud_orders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("cloud_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("code_url", sa.String(500), nullable=False),
        sa.Column("channel_trade_no", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column(
            "subscription_id", sa.String(64), sa.ForeignKey("cloud_subscriptions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("note", sa.String(300), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'paid', 'closed')", name="ck_cloud_orders_status"),
        sa.CheckConstraint("channel IN ('alipay', 'wechat')", name="ck_cloud_orders_channel"),
        sa.CheckConstraint("amount_cents > 0", name="ck_cloud_orders_amount"),
    )
    op.create_index("idx_cloud_orders_user_created", "cloud_orders", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_cloud_orders_user_created", table_name="cloud_orders")
    op.drop_table("cloud_orders")
    with op.batch_alter_table("cloud_plans") as batch:
        batch.drop_constraint("ck_cloud_plans_price", type_="check")
        batch.drop_column("currency")
        batch.drop_column("price_cents")
