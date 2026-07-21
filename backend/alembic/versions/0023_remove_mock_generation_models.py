"""remove mock generation models

Revision ID: 0023_remove_mock_generation_models
Revises: 0022_user_profile
"""

from __future__ import annotations

from alembic import op

revision = "0023_remove_mock_generation_models"
down_revision = "0022_user_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM generation_models WHERE provider = 'mock'")


def downgrade() -> None:
    pass
