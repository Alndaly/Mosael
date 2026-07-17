"""per-account proxy

Revision ID: 0020_account_proxy
Revises: 0019_luts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_account_proxy"
down_revision = "0019_luts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_accounts", sa.Column("proxy", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("publish_accounts", "proxy")
