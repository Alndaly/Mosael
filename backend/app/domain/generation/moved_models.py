"""连接上的模型改了名(ADR 0045,见 providers.moved_models):生成这一侧存着的引用跟着改。

- AI Studio 的生成会话选着的模型(`generation_sessions`);
- 生成记录(`generation_jobs`)和它们产出的素材上记的模型(`generated_assets`):记录脚注、「用同样的参数再来一次」读它们,
  它们跑的就是改名之后叫 `to` 的那一个;
- 任务回执(`jobs` 里生成任务的 payload):重启后接着等的那一类。

机械改名不算一次修改:`updated_at` 原样留着,会话、记录的先后不因为这次改名变。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import GeneratedAsset, GenerationJob, GenerationSession, Job
from app.domain.providers.moved_models import renamed

#: 生成任务在任务表里的种类(见 generation.operations)。
_GENERATION_JOB = "ai_generation"


def follow(db: Session, profile_id: str, renames: dict[str, str], *, why: str = "moved") -> None:
    """这条连接的模型 `renames`(旧 → 新)改了名:会话、记录、素材、回执跟着改。不提交。"""
    for source, target in renames.items():
        records = select(GenerationJob).where(GenerationJob.provider_profile_id == profile_id, GenerationJob.model == source)
        jobs = [row.job_id for row in db.scalars(records) if row.job_id]
        covers = [row.result_asset_id for row in db.scalars(records) if row.result_asset_id]
        db.execute(
            update(GeneratedAsset)
            .where(GeneratedAsset.model == source,
                   GeneratedAsset.job_id.in_(jobs) | GeneratedAsset.asset_id.in_(covers))
            .values(model=target)
        )
        db.execute(
            update(GenerationJob)
            .where(GenerationJob.provider_profile_id == profile_id, GenerationJob.model == source)
            .values(model=target, updated_at=GenerationJob.updated_at)
        )
        db.execute(
            update(GenerationSession)
            .where(GenerationSession.provider_profile_id == profile_id, GenerationSession.model == source)
            .values(model=target, updated_at=GenerationSession.updated_at)
        )
    for job in db.scalars(select(Job).where(Job.kind == _GENERATION_JOB)):
        payload: Any = job.payload
        changed = renamed(payload, profile_id, renames)
        if changed != payload:
            db.execute(update(Job).where(Job.id == job.id).values(payload=changed, updated_at=Job.updated_at))
    db.flush()


__all__ = ["follow"]
