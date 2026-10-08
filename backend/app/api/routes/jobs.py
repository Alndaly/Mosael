from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Tx
from app.domain.job_center import use_cases as job_center
from app.api.schemas import JobKindCatalogOut, JobOut, TaskEventOut
from app.core.i18n import get_current_locale, render_message, t
from app.db.models import Job, TaskEvent
from app.domain import job_catalog

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str | None = None,
    top_level: bool = False,
) -> list[Job]:
    # 别人私有会话里的生成不列 —— 规矩在 domain/job_center/use_cases。
    return job_center.list_jobs(db, user, workspace_id, kind=kind, top_level=top_level)


def _kind_out(entry: job_catalog.JobKind, label_key: str, locale: str) -> dict:
    return {
        "kind": entry.kind,
        "label": t(label_key, locale),
        "announce": entry.announce,
        "affects": list(entry.affects),
        "view": entry.view,
        "record_field": entry.record_field,
    }


@router.get("/jobs/kinds", response_model=JobKindCatalogOut)
def list_job_kinds(user: CurrentUser) -> dict:
    """任务种类目录:任务中心据此显示名字、决定要不要提示、刷新哪些数据、跳到哪一页。"""
    locale = get_current_locale()
    return {
        "kinds": [_kind_out(entry, entry.label_key, locale) for entry in job_catalog.JOB_KINDS.values()],
        "fallback": _kind_out(job_catalog.FALLBACK, job_catalog.FALLBACK_LABEL_KEY, locale),
    }


@router.delete("/jobs/finished")
def delete_finished_jobs(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    # 不是 Tx:清理一批一个事务,由用例自己开(见 job_center.clear_finished);请求会话只用来读和鉴权。
    return {"removed": job_center.clear_finished(db, user, workspace_id)}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: DbSession, user: CurrentUser) -> Job:
    return job_center.readable(db, user, job_id)


@router.get("/jobs/{job_id}/children", response_model=list[JobOut])
def list_job_children(job_id: str, db: DbSession, user: CurrentUser) -> list[Job]:
    """一个工作流 job 派生的子任务(发布/导出/转写/生成/配音)。任务详情里「收纳」展示。"""
    return job_center.children(db, user, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job_route(job_id: str, db: Tx, user: CurrentUser) -> Job:
    try:
        return job_center.cancel(db, user, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/events", response_model=list[TaskEventOut])
def list_job_events(job_id: str, db: DbSession, user: CurrentUser, limit: int = 500) -> list[dict]:
    """一次运行的事件流(按时间正序)。

    上限按**最早**截断,不是最新 30 条。工作流详情靠 workflow.node.started / finished 配对还原
    每个节点的状态,取最新 N 条会把早期的 started 挤掉 —— 表现为「旧任务只剩最后一个节点、
    前面的步骤全没了」,而最后那个节点因为丢了 started 反而显示成一直在跑。
    """
    job_center.readable(db, user, job_id)
    events = list(
        db.scalars(
            select(TaskEvent)
            .where(TaskEvent.job_id == job_id)
            .order_by(TaskEvent.created_at.asc())
            .limit(max(1, min(limit, 2000)))
        )
    )
    # 出口才翻:事件里存的是 key + 参数(见 domain/jobs.create_job),这里按请求方的
    # Accept-Language 渲染。没有 key 的事件(自由文本、外部 worker 写的)原样过。
    locale = get_current_locale()
    out: list[dict] = []
    for event in events:
        payload = dict(event.payload or {})
        key = payload.get("message_key")
        if isinstance(key, str) and key:
            params = payload.get("message_params")
            payload["message"] = render_message(key, locale, params if isinstance(params, dict) else {})
        out.append({
            "id": event.id,
            "job_id": event.job_id,
            "type": event.type,
            "payload": payload,
            "created_at": event.created_at,
        })
    return out
