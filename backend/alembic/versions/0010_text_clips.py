"""text clips: clips.asset_id becomes nullable (subtitle clips carry text only)

Revision ID: 0010_text_clips
Revises: 0009_provider_profiles
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_text_clips"
down_revision = "0009_provider_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clips") as batch:
        batch.alter_column("asset_id", existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("clips") as batch:
        batch.alter_column("asset_id", existing_type=sa.String(64), nullable=False)
