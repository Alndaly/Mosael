"""undo/redo history columns on sequence_operations

Revision ID: 0002_operation_history
Revises: 0001_initial_schema
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_operation_history"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sequence_operations",
        sa.Column("reverted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sequence_operations", sa.Column("undo_of", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("sequence_operations", "undo_of")
    op.drop_column("sequence_operations", "reverted")
