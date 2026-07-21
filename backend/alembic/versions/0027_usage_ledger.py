"""add provider usage ledger

Revision ID: 0027_usage_ledger
Revises: 0026_generation_job_timestamps
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_usage_ledger"
down_revision = "0026_generation_job_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_pricing_rules",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("provider_profile_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("billing_unit", sa.String(length=40), nullable=False),
        sa.Column("unit_amount_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["provider_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_provider_pricing_lookup",
        "provider_pricing_rules",
        ["workspace_id", "provider_profile_id", "provider", "capability", "model"],
    )
    op.create_table(
        "provider_usage_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("provider_profile_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("operation", sa.String(length=60), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("source_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("agent_message_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="succeeded"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("units", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_usage", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("cost_micros", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("cost_confidence", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("pricing_rule_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_message_id"], ["agent_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pricing_rule_id"], ["provider_pricing_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["provider_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_provider_usage_agent_message", "provider_usage_events", ["agent_message_id"])
    op.create_index("idx_provider_usage_job", "provider_usage_events", ["job_id"])
    op.create_index("idx_provider_usage_workspace_created", "provider_usage_events", ["workspace_id", "created_at"])
    op.create_index("uq_provider_usage_idempotency", "provider_usage_events", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_provider_usage_idempotency", table_name="provider_usage_events")
    op.drop_index("idx_provider_usage_workspace_created", table_name="provider_usage_events")
    op.drop_index("idx_provider_usage_job", table_name="provider_usage_events")
    op.drop_index("idx_provider_usage_agent_message", table_name="provider_usage_events")
    op.drop_table("provider_usage_events")
    op.drop_index("idx_provider_pricing_lookup", table_name="provider_pricing_rules")
    op.drop_table("provider_pricing_rules")
