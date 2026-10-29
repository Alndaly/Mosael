"""积分账本与网关目录(ADR 0088 第 2 步)。

- 套餐与积分:`cloud_plans`、`cloud_subscriptions`、`cloud_credit_batches`、`cloud_usage_entries`(只追加,余额是流水的和);
- 网关:`cloud_gateway_models`(对外的模型)、`cloud_model_prices`(带生效时间的积分单价)、
  `cloud_upstream_channels`(上游端点与加密的 Key)、`cloud_gateway_calls`(每一次调用:预占、扣了多少、用量)。

全是新表,不碰已有数据。已有库升级:

    uv run python -m cloud.cli migrate

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(64), primary_key=True)


def _user() -> sa.Column:
    return sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "cloud_plans",
        _id(),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("monthly_credits", sa.Integer(), nullable=False),
        sa.Column("credit_ttl_days", sa.Integer(), nullable=False),
        sa.Column("on_sale", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("period IN ('month', 'quarter', 'year')", name="ck_cloud_plans_period"),
        sa.CheckConstraint("monthly_credits > 0 AND credit_ttl_days > 0", name="ck_cloud_plans_positive"),
    )
    op.create_table(
        "cloud_subscriptions",
        _id(),
        _user(),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("cloud_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("next_grant_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'ended')", name="ck_cloud_subscriptions_status"),
    )
    op.create_index("idx_cloud_subscriptions_user", "cloud_subscriptions", ["user_id"])
    op.create_table(
        "cloud_credit_batches",
        _id(),
        _user(),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "subscription_id", sa.String(64), sa.ForeignKey("cloud_subscriptions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(200), nullable=False),
        sa.CheckConstraint("source IN ('plan', 'gift')", name="ck_cloud_credit_batches_source"),
        sa.CheckConstraint("amount > 0", name="ck_cloud_credit_batches_amount"),
    )
    op.create_index("idx_cloud_credit_batches_user_expiry", "cloud_credit_batches", ["user_id", "expires_at"])
    op.create_table(
        "cloud_gateway_models",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('chat')", name="ck_cloud_gateway_models_kind"),
    )
    op.create_table(
        "cloud_model_prices",
        _id(),
        sa.Column(
            "model_id", sa.String(64), sa.ForeignKey("cloud_gateway_models.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("input_per_1k", sa.Integer(), nullable=False),
        sa.Column("output_per_1k", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.CheckConstraint("input_per_1k >= 0 AND output_per_1k >= 0", name="ck_cloud_model_prices_nonnegative"),
    )
    op.create_index("idx_cloud_model_prices_model_effective", "cloud_model_prices", ["model_id", "effective_from"])
    op.create_table(
        "cloud_upstream_channels",
        _id(),
        sa.Column(
            "model_id", sa.String(64), sa.ForeignKey("cloud_gateway_models.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("upstream_model", sa.String(120), nullable=False),
        sa.Column("api_key_encrypted", sa.String(1000), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("protocol IN ('openai')", name="ck_cloud_upstream_channels_protocol"),
    )
    op.create_index("idx_cloud_upstream_channels_model", "cloud_upstream_channels", ["model_id", "priority"])
    op.create_table(
        "cloud_gateway_calls",
        _id(),
        _user(),
        sa.Column(
            "device_token_id", sa.String(64), sa.ForeignKey("cloud_device_tokens.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column(
            "channel_id", sa.String(64), sa.ForeignKey("cloud_upstream_channels.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("charged", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("usage_reported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('reserved', 'settled', 'released')", name="ck_cloud_gateway_calls_status"),
    )
    op.create_index("idx_cloud_gateway_calls_user_created", "cloud_gateway_calls", ["user_id", "created_at"])
    op.create_table(
        "cloud_usage_entries",
        _id(),
        _user(),
        sa.Column(
            "batch_id", sa.String(64), sa.ForeignKey("cloud_credit_batches.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column(
            "call_id", sa.String(64), sa.ForeignKey("cloud_gateway_calls.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('grant', 'reserve', 'release', 'expire', 'adjust')", name="ck_cloud_usage_entries_kind"
        ),
    )
    op.create_index("idx_cloud_usage_entries_batch", "cloud_usage_entries", ["batch_id"])
    op.create_index("idx_cloud_usage_entries_user_created", "cloud_usage_entries", ["user_id", "created_at"])
    op.create_index("idx_cloud_usage_entries_call", "cloud_usage_entries", ["call_id"])


def downgrade() -> None:
    for table in (
        "cloud_usage_entries",
        "cloud_gateway_calls",
        "cloud_upstream_channels",
        "cloud_model_prices",
        "cloud_gateway_models",
        "cloud_credit_batches",
        "cloud_subscriptions",
        "cloud_plans",
    ):
        op.drop_table(table)
