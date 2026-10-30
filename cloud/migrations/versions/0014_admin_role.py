"""MosaelCloud 管理员账号角色。

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cloud_users") as batch:
        batch.add_column(
            sa.Column("role", sa.String(16), nullable=False, server_default="member")
        )
        batch.create_check_constraint("ck_cloud_users_role", "role IN ('member', 'admin')")


def downgrade() -> None:
    with op.batch_alter_table("cloud_users") as batch:
        batch.drop_constraint("ck_cloud_users_role", type_="check")
        batch.drop_column("role")
