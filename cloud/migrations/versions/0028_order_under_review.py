"""订单多一种状态 `under_review`:渠道报的金额和订单对不上 —— 钱收了、不发放,等运营核对。

此前这种单一直停在 `pending`、还在给二维码,对账每分钟再报一次错。降级时把它们放回 `pending`(旧版只认三种)。

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels = None
depends_on = None

NEW_STATUSES = "status IN ('pending', 'paid', 'closed', 'under_review')"
OLD_STATUSES = "status IN ('pending', 'paid', 'closed')"


def upgrade() -> None:
    with op.batch_alter_table("cloud_orders") as batch:
        batch.drop_constraint("ck_cloud_orders_status", type_="check")
        batch.create_check_constraint("ck_cloud_orders_status", NEW_STATUSES)
    op.get_bind().execute(sa.text(
        "UPDATE cloud_orders SET status = 'under_review' WHERE status = 'pending' AND note LIKE 'amount mismatch:%'"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text("UPDATE cloud_orders SET status = 'pending' WHERE status = 'under_review'"))
    with op.batch_alter_table("cloud_orders") as batch:
        batch.drop_constraint("ck_cloud_orders_status", type_="check")
        batch.create_check_constraint("ck_cloud_orders_status", OLD_STATUSES)
