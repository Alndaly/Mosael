"""generation_jobs.job_id 改 SET NULL(生成记录与任务清理解耦)

「清空已完成任务」删除 jobs 行时,ON DELETE CASCADE 把 generation_jobs
一并抹掉 —— 生成历史(创作记录)不该陪任务日志殉葬。改为 SET NULL:
job 没了记录仍在,状态由 result_asset_id 兜底判定。

Revision ID: 0030_generation_job_detach
Revises: 0029_oauth_identities
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_generation_job_detach"
down_revision = "0029_oauth_identities"
branch_labels = None
depends_on = None

# 库里的外键都是匿名的;batch 反射时按此约定命名,才能点名 drop。
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    # SQLite 改不了既有外键,batch 模式重建表(数据原样搬运)。
    with op.batch_alter_table("generation_jobs", schema=None, naming_convention=NAMING) as batch:
        batch.alter_column("job_id", existing_type=sa.String(length=64), nullable=True)
        batch.drop_constraint("fk_generation_jobs_job_id_jobs", type_="foreignkey")
        batch.create_foreign_key(
            "fk_generation_jobs_job_id_jobs", "jobs", ["job_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None, naming_convention=NAMING) as batch:
        batch.drop_constraint("fk_generation_jobs_job_id_jobs", type_="foreignkey")
        batch.create_foreign_key(
            "fk_generation_jobs_job_id_jobs", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
        )
        batch.alter_column("job_id", existing_type=sa.String(length=64), nullable=False)
