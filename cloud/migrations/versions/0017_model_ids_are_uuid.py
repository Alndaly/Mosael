"""把网关模型的主键从手填名字换成系统 UUID(展示名单独保存)。

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-30
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, label, kind, max_output_tokens, enabled, sort_order, created_at "
            "FROM cloud_gateway_models ORDER BY created_at, id"
        )
    ).mappings().all()
    mapping: dict[str, str] = {}
    for row in rows:
        new_id = uuid.uuid4().hex
        mapping[row["id"]] = new_id
        bind.execute(
            sa.text(
                "INSERT INTO cloud_gateway_models "
                "(id, label, kind, max_output_tokens, enabled, sort_order, created_at) "
                "VALUES (:id, :label, :kind, :max_output_tokens, :enabled, :sort_order, :created_at)"
            ),
            {
                "id": new_id,
                "label": row["label"],
                "kind": row["kind"],
                "max_output_tokens": row["max_output_tokens"],
                "enabled": row["enabled"],
                "sort_order": row["sort_order"],
                "created_at": row["created_at"],
            },
        )
    for old_id, new_id in mapping.items():
        for table in ("cloud_model_prices", "cloud_upstream_channels", "cloud_gateway_calls"):
            bind.execute(
                sa.text(f"UPDATE {table} SET model_id = :new_id WHERE model_id = :old_id"),
                {"new_id": new_id, "old_id": old_id},
            )
    for old_id in mapping:
        bind.execute(sa.text("DELETE FROM cloud_gateway_models WHERE id = :id"), {"id": old_id})


def downgrade() -> None:
    # 0017 只换主键值,不改表结构;旧的手填名字没有留存,无法反推。降级保留 UUID,
    # 不影响 0016 及更早版本继续运行。
    pass
