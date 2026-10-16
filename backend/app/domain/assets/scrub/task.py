"""「清除元数据」这条工序的领域编排:**两份入口共用一个身子**(后台任务 / 工作流节点)。

做的事就是 `engine.scrub_file` 那三步,外加两件领域上的收拾:产出登记成一份**派生素材**,
对账文本落成一份能看回来的产物。工作流的节点同步调 `scrub_asset`,后台任务把它包进 `Job`。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import SCRUB, derived
from app.domain.jobs import RENDER_SLOTS, create_job, dispatch_job, emit_job_event, finish_job, say, start_job
from app.domain.assets.scrub import gates as gates_mod
from app.domain.assets.scrub.engine import (
    REMOVED_REPORT_SUFFIX,
    ScrubError,
    ScrubOutcome,
    gate_report,
    render_report,
    scrub_file,
)
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

JOB_KIND = "scrub_metadata"

#: 产出素材的名字后缀。用户看到的就是它 —— 别写成英文。
DERIVED_SUFFIX = " · 已清除元数据"


@dataclass(frozen=True)
class ScrubSource:
    """重活开始前从库里抄下来的几样东西。

    **抄下来是有意的**:`scrub_file` 要跑几秒到几分钟,中间全程不碰数据库 —— 会话不占用、
    写锁早就放掉了(和 video_gif / shots_task 那个"先落 running 再干活"同一个道理,
    只是这里连 `.commit()` 都不用写:整段重活**根本不在事务里**)。
    """

    id: str
    workspace_id: str
    project_id: str | None
    name: str
    file_key: str
    ai_generated: bool

    @classmethod
    def of(cls, asset: Asset) -> "ScrubSource":
        return cls(
            id=asset.id, workspace_id=asset.workspace_id, project_id=asset.project_id,
            name=asset.name, file_key=asset.file_key or "",
            ai_generated=bool(asset.ai_generated),
        )


@dataclass
class ScrubRun:
    """一次清除的**文件产出**,不带任何 ORM 对象 —— 登记是下一步的事。"""

    target: Path
    report_path: Path
    outcome: ScrubOutcome
    gates: list[dict[str, object]]
    report: str

    @property
    def passed(self) -> bool:
        return not gates_mod.failures(self.gates, hard_only=True)


@dataclass
class ScrubResult:
    asset: Asset | None
    outcome: ScrubOutcome
    gates: list[dict[str, object]]
    report: str
    report_path: Path

    @property
    def passed(self) -> bool:
        return not gates_mod.failures(self.gates, hard_only=True)


def require_video(asset: Asset) -> None:
    if asset.kind != "video":
        raise ScrubError("scrubErr_notVideo")
    if not asset.file_key:
        raise ScrubError("scrubErr_noLocalFile")


def report_path_for(source: Path) -> Path:
    return source.with_name(source.stem + REMOVED_REPORT_SUFFIX)


def scrub_source(source: ScrubSource, *, provenance: bool = False) -> ScrubRun:
    """**纯文件活**:重封装 → 原地改码流 → 门禁 → 对账文本。全程不碰数据库。

    硬门红了(产出不可信)就把文件删掉再抛 —— 不登记、不留半成品。
    """
    if not source.file_key:
        raise ScrubError("scrubErr_noLocalFile")
    origin = resolve_key(source.file_key)
    if not origin.is_file():
        raise ScrubError("scrubErr_sourceMissing")
    target = origin.with_name(origin.stem + " · clean.mp4")
    outcome = scrub_file(origin, target, provenance=provenance)
    gate_list = gate_report(outcome)
    report = render_report(outcome, gate_list)
    run = ScrubRun(target=target, report_path=report_path_for(origin), outcome=outcome,
                   gates=gate_list, report=report)
    if not run.passed:
        target.unlink(missing_ok=True)
        raise ScrubError("scrubErr_gateFailed", gates="、".join(
            str(gate["id"]) for gate in gates_mod.failures(gate_list, hard_only=True)))
    run.report_path.parent.mkdir(parents=True, exist_ok=True)
    run.report_path.write_text(report, encoding="utf-8")
    return run


def register_scrub(db: Session, source: ScrubSource, run: ScrubRun, *, created_by: str | None = None) -> Asset:
    """把产出登记进库。**调用方的事务。**"""
    made = register_file_asset(
        db,
        workspace_id=source.workspace_id,
        project_id=source.project_id,
        source_path=run.target,
        name=f"{source.name}{DERIVED_SUFFIX}",
        source="generated",
        derived_from=derived(SCRUB, source.id),
        #: **在 Mosael 里不许洗白**:文件里那份 C2PA 清单可以按开关清掉,但库里这份产出照样继承
        #: "含 AI 内容"的标记(ADR 0028 的 AI 标识是另一件事,见 ADR 0062 §provenance)。
        ai_generated=source.ai_generated,
        move=True,
    )
    made.media_info = {
        **(made.media_info or {}),
        "scrubbed": True,
        "scrub_provenance_removed": bool(run.outcome.provenance),
        "scrub_gates_ok": not gates_mod.failures(run.gates),
    }
    return made


def scrub_asset(
    db: Session,
    asset: Asset,
    *,
    provenance: bool = False,
    created_by: str | None = None,
) -> ScrubResult:
    """工作流节点那条路:**在调用方的事务里**跑完一次用例(引擎的事务)。"""
    require_video(asset)
    source = ScrubSource.of(asset)
    run = scrub_source(source, provenance=provenance)
    made = register_scrub(db, source, run, created_by=created_by)
    return ScrubResult(asset=made, outcome=run.outcome, gates=run.gates,
                       report=run.report, report_path=run.report_path)


# ---------------- 后台任务 ----------------


def start_scrub_job(db: Session, *, asset: Asset, created_by: str | None, provenance: bool = False) -> Job:
    """排一条清除元数据的后台任务。**按体积估:转封装 + 逐样本改写可能是分钟级。**"""
    require_video(asset)
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind=JOB_KIND,
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "provenance": bool(provenance)},
        message="jobMsg_scrubQueued" if not provenance else "jobMsg_scrubQueuedWithProvenance",
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run(job_id))
    return job


def _run(job_id: str) -> None:
    #: 和渲染 / 拆镜头同一挡:这一步是重 I/O(整份读一遍、整份写一遍),同时开十个没有意义。
    with RENDER_SLOTS:
        _body(job_id)


def _body(job_id: str) -> None:
    #: 第一个短事务:起任务、说一句 —— 出块即提交,写锁在这一刻就放掉了。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        payload = dict(job.payload or {}) if job is not None else {}
        asset = db.get(Asset, str(payload.get("asset_id") or ""))
        if job is None or asset is None:
            return
        if not start_job(db, job, progress=0.05):
            return
        say(job, "jobMsg_scrubRunning")
        emit_job_event(db, job.id, "job.running", {})
        source = ScrubSource.of(asset)
        provenance = bool(payload.get("provenance"))
        created_by = job.created_by

    #: **整段重活在这儿,事务之外。** 失败(ScrubError 等)原样抛出去,由派发处
    #: (`jobs.run_job_guarded`)把这个任务落成失败 —— 不留"排队中"。
    run = scrub_source(source, provenance=provenance)

    #: 第二个短事务:登记产出、落终态。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        made = register_scrub(db, source, run, created_by=created_by)
        result = {
            "asset_id": made.id,
            "source_asset_id": source.id,
            "report": run.report,
            "gates": run.gates,
            "gates_ok": not gates_mod.failures(run.gates),
            "removed": removed_counts(run.outcome),
            "provenance": provenance,
            **({"warnings": run.outcome.warnings} if run.outcome.warnings else {}),
        }
        if finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_scrubDone")
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": made.id})
        logger.info("scrubbed asset %s -> %s", source.id, made.id)


def removed_counts(outcome: ScrubOutcome) -> dict[str, int]:
    """清掉了什么 —— 给任务结果和节点输出一份能直接看的数字。"""
    return {
        "sei_nals": outcome.sei_nals_replaced,
        "sei_payloads": outcome.sei_payloads_removed,
        "aac_dse": outcome.aac_dse_removed,
        "aac_dse_zeroed": outcome.aac_dse_zeroed,
        "aac_fill_zeroed": outcome.aac_fil_zeroed,
        "compressorname": outcome.compressorname_cleared,
        "uuid_boxes": outcome.uuid_dropped,
        "data_tracks": len(outcome.before.container.data_tracks),
        "container_keys": len(outcome.before.container.tags),
        "provenance_kept": outcome.sei_provenance_kept + outcome.uuid_preserved,
        "provenance_removed": outcome.sei_provenance_removed,
    }


__all__ = [
    "DERIVED_SUFFIX", "JOB_KIND", "ScrubResult", "ScrubRun", "ScrubSource", "register_scrub",
    "removed_counts", "report_path_for", "require_video", "scrub_asset", "scrub_source",
    "start_scrub_job",
]
