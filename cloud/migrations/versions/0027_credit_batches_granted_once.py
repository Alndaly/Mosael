"""一份订阅同一发放时刻只有一批积分:先并掉已有的重复批次,再加唯一约束。

此前补发月度批次(`credits.catch_up`)没有互斥:读余额和预占同时到了发放那一刻,两边各发一批。重复的那批的用量流水
(预占、退回、过期)转到保留的那一批上,它自己的「发放」流水和批次删掉 —— 账面回到只发过一次。

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicated = connection.execute(sa.text(
        "SELECT subscription_id, granted_at FROM cloud_credit_batches WHERE subscription_id IS NOT NULL "
        "GROUP BY subscription_id, granted_at HAVING COUNT(*) > 1"
    )).all()
    for subscription_id, granted_at in duplicated:
        ids = [row[0] for row in connection.execute(sa.text(
            "SELECT id FROM cloud_credit_batches WHERE subscription_id = :s AND granted_at = :g ORDER BY id"
        ), {"s": subscription_id, "g": granted_at}).all()]
        kept, extra = ids[0], ids[1:]
        for batch_id in extra:
            connection.execute(sa.text(
                "DELETE FROM cloud_usage_entries WHERE batch_id = :b AND kind = 'grant'"), {"b": batch_id})
            connection.execute(sa.text(
                "UPDATE cloud_usage_entries SET batch_id = :k WHERE batch_id = :b"), {"k": kept, "b": batch_id})
            connection.execute(sa.text("DELETE FROM cloud_credit_batches WHERE id = :b"), {"b": batch_id})
    with op.batch_alter_table("cloud_credit_batches") as batch:
        batch.create_unique_constraint("uq_cloud_credit_batches_subscription_grant", ["subscription_id", "granted_at"])


def downgrade() -> None:
    with op.batch_alter_table("cloud_credit_batches") as batch:
        batch.drop_constraint("uq_cloud_credit_batches_subscription_grant", type_="unique")
