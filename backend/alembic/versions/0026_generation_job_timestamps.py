"""add generation job timestamps

Revision ID: 0026_generation_job_timestamps
Revises: 0025_drop_credentials
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_generation_job_timestamps"
down_revision = "0025_drop_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.execute(
        """
        UPDATE generation_jobs
        SET created_at = COALESCE(
            (SELECT jobs.created_at FROM jobs WHERE jobs.id = generation_jobs.job_id),
            CURRENT_TIMESTAMP
        )
        WHERE created_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE generation_jobs
        SET updated_at = COALESCE(
            (SELECT jobs.updated_at FROM jobs WHERE jobs.id = generation_jobs.job_id),
            created_at,
            CURRENT_TIMESTAMP
        )
        WHERE updated_at IS NULL
        """
    )
    with op.batch_alter_table("generation_jobs") as batch:
        batch.alter_column("created_at", nullable=False)
        batch.alter_column("updated_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
