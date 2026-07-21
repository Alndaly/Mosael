"""drop legacy credentials

Revision ID: 0025_drop_credentials
Revises: 0024_generation_provider_profiles
"""

from __future__ import annotations

from alembic import op

revision = "0025_drop_credentials"
down_revision = "0024_generation_provider_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("credentials")


def downgrade() -> None:
    pass
