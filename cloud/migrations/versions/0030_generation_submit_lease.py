"""Cloud 生成任务记录「提交已开始」的时刻。

提交上游是付费动作,而 `provider_job_id` 只在 submit 返回之后才写。中间崩溃时,原来的代码只能
把任务留在 `queued`,重启后再次提交 —— 上游可能已经收下并扣费,于是同一件事付两次钱。

现在 worker 在调上游**之前**把状态改成 `submitting`、记下 `submit_started_at` 并提交;重启时
`reconcile_uncertain_submits` 看到没有 `provider_job_id` 的 `submitting` 行,按「结局不明」收预占,
不再自动重提。

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cloud_generation_jobs", sa.Column("submit_started_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cloud_generation_jobs") as batch:
        batch.drop_column("submit_started_at")
