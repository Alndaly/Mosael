"""expand:供应商 adapter、模型 interaction/capability、价格计量分量。

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloud_upstream_providers",
        sa.Column("adapter", sa.String(length=32), nullable=False, server_default="openai"),
    )
    op.add_column(
        "cloud_gateway_models",
        sa.Column("interaction", sa.String(length=16), nullable=False, server_default="stream"),
    )
    op.add_column(
        "cloud_gateway_models",
        sa.Column("capability", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "cloud_model_price_components",
        sa.Column("price_id", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("credits_per_unit", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["price_id"], ["cloud_model_prices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("price_id", "unit"),
        sa.CheckConstraint("credits_per_unit >= 0", name="ck_cloud_model_price_components_nonnegative"),
    )

    bind = op.get_bind()
    bind.execute(sa.text("UPDATE cloud_upstream_providers SET adapter = protocol"))
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(
            "UPDATE cloud_gateway_models SET interaction = 'stream', "
            "capability = json_object('max_output_tokens', max_output_tokens)"
        ))
    else:
        bind.execute(sa.text(
            "UPDATE cloud_gateway_models SET interaction = 'stream', "
            "capability = json_build_object('max_output_tokens', max_output_tokens)"
        ))
    bind.execute(sa.text(
        "INSERT INTO cloud_model_price_components (price_id, unit, credits_per_unit) "
        "SELECT id, 'token_input', input_per_1k FROM cloud_model_prices"
    ))
    bind.execute(sa.text(
        "INSERT INTO cloud_model_price_components (price_id, unit, credits_per_unit) "
        "SELECT id, 'token_output', output_per_1k FROM cloud_model_prices"
    ))


def downgrade() -> None:
    op.drop_table("cloud_model_price_components")
    op.drop_column("cloud_gateway_models", "capability")
    op.drop_column("cloud_gateway_models", "interaction")
    op.drop_column("cloud_upstream_providers", "adapter")
