"""通用异步生成任务、用量事实与结果文件。

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_generation_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_token_id", sa.String(64), sa.ForeignKey("cloud_device_tokens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("cloud_gateway_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("call_id", sa.String(64), sa.ForeignKey("cloud_gateway_calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("capability", sa.JSON(), nullable=False),
        sa.Column("price_snapshot", sa.JSON(), nullable=False),
        sa.Column("provider_job_id", sa.String(200), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_detail", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_cloud_generation_jobs_user_idempotency", "cloud_generation_jobs", ["user_id", "idempotency_key"], unique=True)
    op.create_index("idx_cloud_generation_jobs_status_poll", "cloud_generation_jobs", ["status", "next_poll_at"])
    op.create_table(
        "cloud_job_usage",
        sa.Column("job_id", sa.String(64), sa.ForeignKey("cloud_generation_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("unit", sa.String(32), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reported", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "cloud_media_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("cloud_generation_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("mime", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cloud_media_artifacts")
    op.drop_table("cloud_job_usage")
    op.drop_index("idx_cloud_generation_jobs_status_poll", table_name="cloud_generation_jobs")
    op.drop_index("uq_cloud_generation_jobs_user_idempotency", table_name="cloud_generation_jobs")
    op.drop_table("cloud_generation_jobs")
