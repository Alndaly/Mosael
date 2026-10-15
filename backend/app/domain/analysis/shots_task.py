"""素材页的「拆镜头」后台任务(ADR 0061 §4/§5):排一个任务,量刀口取帧 →(有视觉模型就)逐镜看画面。

编排住在这里而不是 domain/shots:挑视觉模型、起视觉调用是**分析**这条域的事 —— shots 域只量、只存,
不认识任何一种连接 / 模型,也不回头 import analysis(分层见 tests/test_import_layering)。
工作流的三个节点不走这里:它们由 executors/shots.py 直接调 breakdowns.measure_into / judge,
视觉调用由这里 exported 的 `vision_ask` 做成 `ask` 交进去(记账、选连接、谁的钥匙都在调用方)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain.analysis import service as analysis
from app.domain.analysis.service import AnalysisError, select_analysis_connection
from app.domain.billing.usage import billable
from app.domain.jobs import RENDER_SLOTS, create_job, dispatch_job, emit_job_event, finish_job, say, start_job
from app.domain.providers import models as provider_models
from app.domain.shots import breakdowns, describe, detect

logger = logging.getLogger(__name__)

JOB_KIND = "shot_breakdown"


def vision_ask(
    db: Session,
    connection: Any,
    *,
    model: str,
    surface: Literal["direct", "automation"],
    user_id: str | None,
    asset: Asset,
    key_for: Callable[[], str],
) -> describe.Ask:
    """拿一条解析过的连接做成 `ask`:每次调用记一笔账(`key_for()` 给这一次的记账键)。

    调用走分析的 `call_vision_model`(和「看图 / 看视频」同一条出口,测试替身也挂在那里)。"""
    def ask(messages: list[dict[str, Any]]) -> str:
        with billable(
            db, user_id=user_id, capability="chat", operation="shot_describe", workspace_id=asset.workspace_id,
            idempotency_key=key_for(), source_type="asset", source_id=asset.id,
        ) as call:
            return analysis.call_vision_model(db, connection, messages, call, model=model, surface=surface)

    return ask


def start_breakdown(
    db: Session,
    asset: Asset,
    *,
    created_by: str | None,
    profile_id: str | None = None,
    model: str = "",
    surface: Literal["direct", "automation"] = "direct",
    threshold: float = detect.DEFAULT_THRESHOLD,
) -> Job:
    """排一个拆镜头的任务。`profile_id` 不给就按「分析」的默认挑法找视觉模型,一个都没有就只做机器那一半。"""
    breakdowns.require_video(asset)
    if not 0.05 <= threshold <= 0.9:
        raise breakdowns.ShotBreakdownError("shotsErr_badParams")
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind=JOB_KIND,
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "threshold": threshold, "lang": breakdowns.lang_now(),
                 "profile_id": profile_id or "", "model": model, "surface": surface},
        message="jobMsg_shotsQueued",
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run(job_id))
    return job


def _run(job_id: str) -> None:
    with RENDER_SLOTS:
        _body(job_id)


def _body(job_id: str) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        payload = dict(job.payload or {}) if job is not None else {}
        asset = db.get(Asset, str(payload.get("asset_id") or ""))
        if job is None or asset is None:
            return
        if not start_job(db, job, progress=0.05):
            return
        say(job, "jobMsg_shotsMeasuring")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        row = breakdowns.measure_into(db, asset, created_by=job.created_by, lang=str(payload.get("lang") or "zh"),
                                      threshold=float(payload.get("threshold") or detect.DEFAULT_THRESHOLD))
        finish_job(db, job, status="running", progress=0.4)
        db.commit()

        try:
            connection = select_analysis_connection(db, str(payload.get("profile_id") or "") or None, job.created_by)
        except AnalysisError as exc:
            #: 没有视觉模型(或钥匙没配):机器那一半照样交,提示里说一句没判、为什么。
            connection = None
            row.describe = {"error": str(exc)}
            row.hints = [*row.hints, {"shot": "", "kind": "not_described", "field": "", "value": ""}]
        if connection is not None:
            model = str(payload.get("model") or "") or provider_models.model_id_for(db, connection, "chat")
            say(job, "jobMsg_shotsDescribing")
            counter = iter(range(1, 10_000))
            ask = vision_ask(db, connection, model=model, surface=payload.get("surface") or "direct",
                             user_id=job.created_by, asset=asset,
                             key_for=lambda: f"{JOB_KIND}:{job_id}:{next(counter)}")

            def checkpoint(done: int, total: int) -> None:
                finish_job(db, job, status="running", progress=round(0.4 + 0.55 * done / max(total, 1), 3))
                db.commit()

            breakdowns.judge(db, row, asset, ask, provider=connection.vendor or "", model=model, after_batch=checkpoint)

        result = {"asset_id": asset.id, "breakdown_id": row.id, "shots": len(row.shots),
                  "judged": bool(row.describe.get("judged_batches"))}
        if finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_shotsDone", count=len(row.shots))
            emit_job_event(db, job.id, "job.succeeded", dict(result))
        logger.info("shot breakdown %s: %d shots for asset %s", row.id, len(row.shots), asset.id)


__all__ = ["JOB_KIND", "start_breakdown", "vision_ask"]
