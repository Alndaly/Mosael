"""`cloud_shares.kind` 增加 `plugin`:官方账号发布的插件分享。

维护者裁决的"官方内容"就是官方账号发布的分享,所以插件不需要第二张表、第二套 payload:
它只是 `kind` 的第三个取值。CHECK 直接换成含 `plugin` 的新值,**不写"旧数据兼容"分支** ——
既有 workflow / board 行原样保留,数据库自己会拒绝任何其它值。

downgrade 把 CHECK 换回 0004 的两个值。如果库里已经有 plugin 行,回退会在这里**明确失败**
(SQLite 重建表 / PostgreSQL 校验约束),而不是悄悄删掉那些分享;要真的降级,先自己处理
那些行。

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "kind IN ('workflow', 'board')"
NEW_KINDS = "kind IN ('workflow', 'board', 'plugin')"


def upgrade() -> None:
    with op.batch_alter_table("cloud_shares") as batch:
        batch.drop_constraint("ck_cloud_shares_kind", type_="check")
        batch.create_check_constraint("ck_cloud_shares_kind", NEW_KINDS)


def downgrade() -> None:
    with op.batch_alter_table("cloud_shares") as batch:
        batch.drop_constraint("ck_cloud_shares_kind", type_="check")
        batch.create_check_constraint("ck_cloud_shares_kind", OLD_KINDS)
