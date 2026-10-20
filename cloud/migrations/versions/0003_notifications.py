"""通知:谁对谁的分享点了赞 / 收藏 / 评论。

新表 `cloud_share_notifications`,一条互动一行,收件人 = 分享作者。

- 未读去重:部分唯一索引 `(recipient_id, actor_id, share_id, kind) WHERE read_at IS NULL` ——
  同一个人对同一条分享连续点赞 / 取消 / 再点赞,最多一条未读。已读之后的新互动另起一行。
- 列表索引:`(recipient_id, created_at DESC)`(新序在前);未读查询:`(recipient_id, read_at)`。
- **不为旧数据写任何兼容 / 回填分支**:这是新表,从零张行开始。

已有库升级:

    uv run python -m cloud.cli migrate

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cloud_share_notifications",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("recipient_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("share_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("comment_id", sa.String(length=64), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["cloud_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["share_id"], ["cloud_shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["cloud_share_comments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('like', 'favorite', 'comment')", name="ck_cloud_share_notifications_kind"
        ),
    )
    # 新序在前。SQLite 的索引反射不保留 DESC,模型里按同名列声明,这里写真实建库语句。
    op.execute(
        "CREATE INDEX idx_cloud_share_notifications_recipient_created "
        "ON cloud_share_notifications (recipient_id, created_at DESC)"
    )
    op.create_index(
        "idx_cloud_share_notifications_recipient_read",
        "cloud_share_notifications",
        ["recipient_id", "read_at"],
        unique=False,
    )
    op.create_index(
        "idx_cloud_share_notifications_comment",
        "cloud_share_notifications",
        ["comment_id"],
        unique=False,
    )
    # 未读去重:每个 (收件人, 互动者, 分享, 类型) 槽位最多一条未读。
    op.create_index(
        "uq_cloud_share_notifications_unread",
        "cloud_share_notifications",
        ["recipient_id", "actor_id", "share_id", "kind"],
        unique=True,
        sqlite_where=sa.text("read_at IS NULL"),
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_cloud_share_notifications_unread", table_name="cloud_share_notifications")
    op.drop_index("idx_cloud_share_notifications_comment", table_name="cloud_share_notifications")
    op.drop_index("idx_cloud_share_notifications_recipient_read", table_name="cloud_share_notifications")
    op.drop_index("idx_cloud_share_notifications_recipient_created", table_name="cloud_share_notifications")
    op.drop_table("cloud_share_notifications")
