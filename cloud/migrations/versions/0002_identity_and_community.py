"""身份(昵称 / 短名 / 头像种子)与社区分享(分享、点赞、收藏、评论)。

- `cloud_users` 只**加列**,不动登录:`display_name` / `handle` / `avatar_seed` 都可空 ——
  "有没有身份"是账号的一种状态,不是注册的一部分。
- 新表 `cloud_shares` 的 `owner_user_id` NOT NULL:没有匿名发布。
- 点赞 / 收藏靠 `(share_id, user_id)` 的主键去重,不靠先查再插。

已有库的升级路径(一次性,之后都用 `migrate`):

    uv run python -m cloud.cli stamp 0001     # 0001 之前 create_all 建出来的库
    uv run python -m cloud.cli migrate

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: PostgreSQL 上落 JSONB;SQLite 上用 JSON。
JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("cloud_users") as batch:
        batch.add_column(sa.Column("display_name", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("handle", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("avatar_seed", sa.String(length=16), nullable=True))
        # 多个 NULL 不算冲突:没有身份的老账号可以是空 handle。
        batch.create_index("ix_cloud_users_handle", ["handle"], unique=True)

    op.create_table(
        "cloud_shares",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("license", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("downloads", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('workflow', 'board')", name="ck_cloud_shares_kind"),
        sa.CheckConstraint("status IN ('listed', 'removed')", name="ck_cloud_shares_status"),
    )
    with op.batch_alter_table("cloud_shares") as batch:
        batch.create_index("idx_cloud_shares_owner", ["owner_user_id"], unique=False)
        batch.create_index("idx_cloud_shares_created", ["created_at"], unique=False)
        batch.create_index("idx_cloud_shares_kind_created", ["kind", "created_at"], unique=False)

    op.create_table(
        "cloud_share_likes",
        sa.Column("share_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["share_id"], ["cloud_shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("share_id", "user_id"),
    )
    with op.batch_alter_table("cloud_share_likes") as batch:
        batch.create_index("idx_cloud_share_likes_user", ["user_id"], unique=False)

    op.create_table(
        "cloud_share_favorites",
        sa.Column("share_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["share_id"], ["cloud_shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("share_id", "user_id"),
    )
    with op.batch_alter_table("cloud_share_favorites") as batch:
        batch.create_index("idx_cloud_share_favorites_user", ["user_id"], unique=False)

    op.create_table(
        "cloud_share_comments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("share_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["share_id"], ["cloud_shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("cloud_share_comments") as batch:
        batch.create_index("idx_cloud_share_comments_share", ["share_id", "created_at"], unique=False)
        batch.create_index("idx_cloud_share_comments_user", ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("cloud_share_comments") as batch:
        batch.drop_index("idx_cloud_share_comments_user")
        batch.drop_index("idx_cloud_share_comments_share")
    op.drop_table("cloud_share_comments")

    with op.batch_alter_table("cloud_share_favorites") as batch:
        batch.drop_index("idx_cloud_share_favorites_user")
    op.drop_table("cloud_share_favorites")

    with op.batch_alter_table("cloud_share_likes") as batch:
        batch.drop_index("idx_cloud_share_likes_user")
    op.drop_table("cloud_share_likes")

    with op.batch_alter_table("cloud_shares") as batch:
        batch.drop_index("idx_cloud_shares_kind_created")
        batch.drop_index("idx_cloud_shares_created")
        batch.drop_index("idx_cloud_shares_owner")
    op.drop_table("cloud_shares")

    with op.batch_alter_table("cloud_users") as batch:
        batch.drop_index("ix_cloud_users_handle")
        batch.drop_column("avatar_seed")
        batch.drop_column("handle")
        batch.drop_column("display_name")
