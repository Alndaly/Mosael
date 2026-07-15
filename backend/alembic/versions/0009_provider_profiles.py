"""provider profiles table

Revision ID: 0009_provider_profiles
Revises: 0008_agent_host
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_provider_profiles"
down_revision = "0008_agent_host"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("vendor", sa.String(60), nullable=False),
        sa.Column("base_url", sa.String(300), nullable=False, server_default=""),
        sa.Column("api_key", sa.String(500), nullable=False),
        sa.Column("default_model", sa.String(120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_profiles")
