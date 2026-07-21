"""user profile fields

Revision ID: 0022_user_profile
Revises: 0021_generation_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_user_profile"
down_revision = "0021_generation_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(120), nullable=False, server_default=""))
    op.add_column("users", sa.Column("signature", sa.Text(), nullable=False, server_default=""))
    op.execute("UPDATE users SET display_name = username WHERE display_name = ''")


def downgrade() -> None:
    op.drop_column("users", "signature")
    op.drop_column("users", "display_name")
