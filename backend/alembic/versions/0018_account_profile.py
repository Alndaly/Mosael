"""publish account profile fields (matrix ops)

Revision ID: 0018_account_profile
Revises: 0017_notifications
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_account_profile"
down_revision = "0017_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_accounts", sa.Column("profile_name", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("publish_accounts", "profile_name")
