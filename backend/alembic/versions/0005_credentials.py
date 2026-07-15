"""provider credentials table

Revision ID: 0005_credentials
Revises: 0004_auth_sessions
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_credentials"
down_revision = "0004_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("provider", sa.String(80), primary_key=True),
        sa.Column("secret", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("credentials")
