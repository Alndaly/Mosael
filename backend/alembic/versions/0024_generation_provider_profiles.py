"""generation provider profiles

Revision ID: 0024_generation_provider_profiles
Revises: 0023_remove_mock_generation_models
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_generation_provider_profiles"
down_revision = "0023_remove_mock_generation_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_sessions") as batch:
        batch.add_column(sa.Column("provider_profile_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("model", sa.String(120), nullable=True))
        batch.add_column(sa.Column("kind", sa.String(24), nullable=True))
        batch.create_foreign_key(
            "fk_generation_sessions_provider_profile_id",
            "provider_profiles",
            ["provider_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("provider_profile_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_generation_jobs_provider_profile_id",
            "provider_profiles",
            ["provider_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_constraint("fk_generation_jobs_provider_profile_id", type_="foreignkey")
        batch.drop_column("provider_profile_id")
    with op.batch_alter_table("generation_sessions") as batch:
        batch.drop_constraint("fk_generation_sessions_provider_profile_id", type_="foreignkey")
        batch.drop_column("kind")
        batch.drop_column("model")
        batch.drop_column("provider_profile_id")
