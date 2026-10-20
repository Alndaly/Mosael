"""分享加 `locale`:一条内容记下它用的是哪种语言。

维护者裁决:用户发布时记下**自己的语言**(`zh-CN` / `en-US`),官方内容按语言各发一条;
列表按当前语言筛。于是语言必须是分享的一列,而不是标题的猜测。

- `locale` **NOT NULL**,只有 `zh-CN` / `en-US` 两个值(CHECK 兜底,和 kind / status 同一套风格)。
- **既有行一律填 `zh-CN`**:这一列是这次才加的,历史分享没有留下任何语言信息可推断 ——
  迁移当时的内容都是中文,所以这是唯一能诚实地定下来的值。这里写明,不在读取代码里猜。
- 种子命令的稳定键从 `(owner_user_id, kind, slug)` 扩成
  `(owner_user_id, kind, slug, locale)`:同一条官方内容的中英两行可以共存,
  同一语言仍然只许一行。

downgrade 把唯一索引换回三列、删掉 `locale` 与 CHECK。如果库里已经有同一 slug 的两种语言,
三列唯一索引会在这里**明确失败**(SQLite 重建表 / PostgreSQL 校验索引),而不是悄悄删掉其中
一条;要真的降级,先自己处理那些行。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_INDEX = "uq_cloud_shares_owner_kind_slug"
NEW_INDEX = "uq_cloud_shares_owner_kind_slug_locale"
LOCALE_CHECK = "ck_cloud_shares_locale"
LOCALE_CHECK_SQL = "locale IN ('zh-CN', 'en-US')"


def upgrade() -> None:
    with op.batch_alter_table("cloud_shares") as batch:
        # server_default 同时负责给既有行回填 —— 这就是它们被定为 zh-CN 的地方。
        batch.add_column(
            sa.Column("locale", sa.String(length=5), nullable=False, server_default="zh-CN")
        )
        batch.create_check_constraint(LOCALE_CHECK, LOCALE_CHECK_SQL)
        batch.drop_index(OLD_INDEX)
        batch.create_index(NEW_INDEX, ["owner_user_id", "kind", "slug", "locale"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("cloud_shares") as batch:
        batch.drop_index(NEW_INDEX)
        batch.drop_constraint(LOCALE_CHECK, type_="check")
        batch.create_index(OLD_INDEX, ["owner_user_id", "kind", "slug"], unique=True)
        batch.drop_column("locale")
