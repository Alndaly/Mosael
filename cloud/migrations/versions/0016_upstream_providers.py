"""把通道里的供应商端点 / Key 拆成可复用的 cloud_upstream_providers。

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-30
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


def _provider_name(base_url: str, index: int) -> str:
    host = urlsplit(base_url).hostname or ""
    return (host or f"Provider {index}")[:80]


def upgrade() -> None:
    op.create_table(
        "cloud_upstream_providers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key_encrypted", sa.String(1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("protocol IN ('openai')", name="ck_cloud_upstream_providers_protocol"),
    )
    bind = op.get_bind()
    old = bind.execute(
        sa.text(
            "SELECT id, model_id, protocol, base_url, upstream_model, api_key_encrypted, priority, enabled, "
            "cooldown_until, note, created_at FROM cloud_upstream_channels ORDER BY created_at, id"
        )
    ).mappings().all()
    providers: dict[tuple[str, str, str], str] = {}
    channel_provider: dict[str, str] = {}
    for index, row in enumerate(old, start=1):
        key = (row["protocol"], row["base_url"], row["api_key_encrypted"])
        provider_id = providers.get(key)
        if provider_id is None:
            provider_id = uuid.uuid4().hex
            providers[key] = provider_id
            bind.execute(
                sa.text(
                    "INSERT INTO cloud_upstream_providers "
                    "(id, name, protocol, base_url, api_key_encrypted, enabled, note, created_at) "
                    "VALUES (:id, :name, :protocol, :base_url, :api_key_encrypted, :enabled, :note, :created_at)"
                ),
                {
                    "id": provider_id,
                    "name": _provider_name(row["base_url"], index),
                    "protocol": row["protocol"],
                    "base_url": row["base_url"],
                    "api_key_encrypted": row["api_key_encrypted"],
                    "enabled": True,
                    "note": "",
                    "created_at": row["created_at"],
                },
            )
        channel_provider[row["id"]] = provider_id

    with op.batch_alter_table("cloud_upstream_channels") as batch:
        batch.add_column(sa.Column("provider_id", sa.String(64), nullable=True))
    for channel_id, provider_id in channel_provider.items():
        bind.execute(
            sa.text("UPDATE cloud_upstream_channels SET provider_id = :provider_id WHERE id = :id"),
            {"provider_id": provider_id, "id": channel_id},
        )
    with op.batch_alter_table("cloud_upstream_channels") as batch:
        batch.alter_column("provider_id", existing_type=sa.String(64), nullable=False)
        batch.create_foreign_key(
            "fk_cloud_upstream_channels_provider",
            "cloud_upstream_providers",
            ["provider_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_constraint("ck_cloud_upstream_channels_protocol", type_="check")
        batch.drop_column("protocol")
        batch.drop_column("base_url")
        batch.drop_column("api_key_encrypted")


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("cloud_upstream_channels") as batch:
        batch.add_column(sa.Column("protocol", sa.String(16), nullable=True))
        batch.add_column(sa.Column("base_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("api_key_encrypted", sa.String(1000), nullable=True))
    rows = bind.execute(
        sa.text(
            "SELECT c.id, p.protocol, p.base_url, p.api_key_encrypted "
            "FROM cloud_upstream_channels c "
            "JOIN cloud_upstream_providers p ON p.id = c.provider_id"
        )
    ).mappings().all()
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE cloud_upstream_channels SET protocol=:protocol, base_url=:base_url, "
                "api_key_encrypted=:api_key_encrypted WHERE id=:id"
            ),
            {
                "id": row["id"],
                "protocol": row["protocol"],
                "base_url": row["base_url"],
                "api_key_encrypted": row["api_key_encrypted"],
            },
        )
    with op.batch_alter_table("cloud_upstream_channels") as batch:
        batch.alter_column("protocol", existing_type=sa.String(16), nullable=False)
        batch.alter_column("base_url", existing_type=sa.String(500), nullable=False)
        batch.alter_column("api_key_encrypted", existing_type=sa.String(1000), nullable=False)
        batch.create_check_constraint(
            "ck_cloud_upstream_channels_protocol", "protocol IN ('openai')"
        )
        batch.drop_constraint("fk_cloud_upstream_channels_provider", type_="foreignkey")
        batch.drop_column("provider_id")
    op.drop_table("cloud_upstream_providers")
