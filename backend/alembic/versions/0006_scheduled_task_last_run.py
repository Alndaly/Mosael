"""scheduled_tasks.last_run_at

Revision ID: 0006_scheduled_task_last_run
Revises: 0005_credentials
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_scheduled_task_last_run"
down_revision = "0005_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_tasks", sa.Column("last_run_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "last_run_at")
