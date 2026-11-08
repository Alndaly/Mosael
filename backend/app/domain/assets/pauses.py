"""「压缩停顿」:把一段话音频里长过上限的停顿压到上限,产出一份**新**素材,原素材不动。

**为什么有这一步。** 视频模型拿音频驱动口型时,长静音会诱使它换镜头(H3 数字人的硬切都落在静音里,见 ADR 0092)。
数字人模板在配音之后、分段之前过一遍这里,段数、每段配哪一截音频都按压完的这一份算。媒体上怎么找、怎么剪见 media/pauses。

**只收音频。** 视频的停顿压了画面也得跟着剪,那是剪辑台的事(删静音),不是这一步。

**授权的出处跟着走。** 压完的这份记着来源(`tighten`),用到的克隆嗓子登记时从出处继承(ADR 0093),
数字人的授权检查照查不误。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import TIGHTEN, derived
from app.domain.jobs import create_job, dispatch_job, emit_job_event, ensure_wanted, finish_job, say, start_job
from app.media.pauses import MAX_PAUSE_RANGE, PauseError, find_pauses, join_spans, kept_spans
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)


def checked_max_pause(value: float) -> float:
    low, high = MAX_PAUSE_RANGE
    if not low <= value <= high:
        raise PauseError("pauseErr_maxPauseOutOfRange", value=value, low=low, high=high)
    return value


def start_tighten_pauses(db: Session, *, asset: Asset, max_pause: float, created_by: str | None) -> Job:
    """起一个压停顿任务。能不能做在这里就查:不是音频、没有本地文件、上限不在范围里,建任务之前就说。"""
    if asset.kind != "audio":
        raise PauseError("pauseErr_audioOnly")
    if not asset.file_key:
        raise PauseError("pauseErr_noLocalFile")
    max_pause = checked_max_pause(max_pause)
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="tighten_pauses",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "max_pause": max_pause},
        message="jobMsg_tightenPausesQueued",
    )
    job_id, asset_id = job.id, asset.id
    dispatch_job(db, job, lambda: _tighten_body(job_id, asset_id, max_pause))
    return job


@dataclass(frozen=True)
class _Source:
    """重活开始前从库里抄下来的几样东西:找停顿、剪拼全程不碰数据库(同 scrub 的 ScrubSource)。"""

    id: str
    workspace_id: str
    project_id: str | None
    name: str
    path: Path
    duration: float
    intermediate: str


def _tighten_body(job_id: str, asset_id: str, max_pause: float) -> None:
    #: 第一个短事务:起任务、说一句、把要用的抄下来 —— 出块即提交,「在压」马上看得见。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        asset = db.get(Asset, asset_id)
        if job is None or asset is None:
            return
        if not start_job(db, job, progress=0.1):
            return
        say(job, "jobMsg_tightenPausesRunning")
        emit_job_event(db, job.id, "job.running", {})
        info = asset.media_info or {}
        source = _Source(
            id=asset.id, workspace_id=asset.workspace_id, project_id=asset.project_id, name=asset.name,
            path=resolve_key(asset.file_key), duration=float(info.get("duration") or 0.0),
            intermediate=asset.intermediate,
        )

    #: 找停顿、剪拼在事务之外;失败原样抛出,由派发处(jobs.run_job_guarded)落成失败。
    if not source.path.is_file():
        raise PauseError("pauseErr_fileMissing")
    if source.duration <= 0:
        raise PauseError("pauseErr_noDuration")
    spans = kept_spans(source.duration, find_pauses(source.path, duration=source.duration, longer_than=max_pause), max_pause)
    removed = round(source.duration - sum(span.length for span in spans), 3)

    with tempfile.TemporaryDirectory(prefix="mosael-pauses-") as tmp:
        #: wav 进 wav 出、不重新有损编码:后面还要截段、喂给视频模型,一路无损。
        target = Path(tmp) / "tightened.wav"
        join_spans(source.path, target, spans)
        ensure_wanted()  # 剪的时候被取消了:不进素材库

        #: 第二个短事务:登记产出、落终态。
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            made = register_file_asset(
                db,
                workspace_id=source.workspace_id,
                project_id=source.project_id,
                source_path=target,
                name=f"{source.name} · ≤{max_pause:g}s",
                source="generated",
                derived_from=derived(TIGHTEN, source.id),
                intermediate=source.intermediate,
                move=True,
            )
            result = {"asset_id": made.id, "removed_seconds": removed, "duration": round(source.duration - removed, 3)}
            if finish_job(db, job, status="succeeded", progress=1.0, result=result):
                say(job, "jobMsg_tightenPausesDone", seconds=removed)
                emit_job_event(db, job.id, "job.succeeded", {"asset_id": made.id})
    logger.info("tighten pauses %s (≤%.2fs, removed %.2fs)", source.id, max_pause, removed)


__all__ = ["checked_max_pause", "start_tighten_pauses"]
