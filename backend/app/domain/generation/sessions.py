"""生成会话:建、删、他看得见的生成历史,以及两道闸 —— **看**和**写**。路由和生成漏斗都来这里问。

生成会话是某人的私人工作线程(见 domain/sharing.KINDS)。共享给同事是给他**看**;改名、删除、收进分组、
换模型 / 连接、在里面接着生成,只有主人。判据和对话会话一字不差,所以写在 domain/sharing
(`readable` / `writable` / `ensure_writable`),这里只绑上种类与权限档。每一条写路径被拒、读路径放行,
由 tests/test_generation_session_access.py 钉着。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import GeneratedAsset, GenerationJob, GenerationSession, Job, ProviderUsageEvent, User
from app.domain import sharing, usage
from app.domain.permissions import NotVisible

#: 共享记录里这一类叫什么(见 domain/sharing.KINDS)。
SHARE_KIND = "generation_session"


def readable_session(db: Session, user: User, session_id: str) -> GenerationSession:
    """他看得见的那条会话。看不见 = 不存在(404)。"""
    return sharing.readable(db, SHARE_KIND, user, session_id)


def writable_session(db: Session, user: User, session_id: str) -> GenerationSession:
    """他能改的那条会话:看得见(否则 404)+ 工作区的 `ai` 权限 + 是主人(否则 403)。"""
    return sharing.writable(db, SHARE_KIND, user, session_id, perm="ai")


def ensure_writable(db: Session, session: GenerationSession, actor_id: str | None) -> None:
    """写之前的最后一道:只有主人。生成漏斗往一条点了名的会话里放生成之前也过这里。"""
    sharing.ensure_writable(db, SHARE_KIND, session, actor_id)


# ---------- 任务总线上的生成 ----------
#
# 每次生成在任务总线(`jobs` 表)上也有一行,任务中心、生成页的进度都从那里读 —— 而那一行的 payload 里就是提示词
# 和整份请求。所以总线上的这一行跟着它那条生成所在的会话走:看不见那条会话,就看不见这个任务(否则「私有」
# 只挡住了会话列表,内容还在任务中心里);取消它是在那条会话里写,只有主人。不挂在生成记录上的任务(导出、转写、
# 工作流……)是工作区的,不受这里管。


def jobs_filter(job_id_column: Any, user: User, workspace_id: str) -> Any:
    """`jobs` 表上他看得见的那些(SQL 条件)。`job_id_column` 是任务 id 那一列。"""
    visible_sessions = select(GenerationSession.id).where(sharing.visible_filter(SHARE_KIND, user, workspace_id))
    hidden = select(GenerationJob.job_id).where(
        GenerationJob.job_id.is_not(None),
        GenerationJob.session_id.is_not(None),
        GenerationJob.session_id.not_in(visible_sessions),
    )
    return job_id_column.not_in(hidden)


def ensure_job_readable(db: Session, user: User, job_id: str) -> None:
    """按 id 看一个任务之前。它是某条会话里的生成时,得看得见那条会话(否则 404)。"""
    _session_of_job(db, user, job_id)


def ensure_job_writable(db: Session, user: User, job_id: str) -> None:
    """取消一个任务之前。它是某条会话里的生成时,得看得见(否则 404)且是会话主人(否则 403)。"""
    session = _session_of_job(db, user, job_id)
    if session is not None:
        ensure_writable(db, session, user.id)


def _session_of_job(db: Session, user: User, job_id: str) -> GenerationSession | None:
    session_id = db.scalar(select(GenerationJob.session_id).where(GenerationJob.job_id == job_id))
    return readable_session(db, user, session_id) if session_id else None


# ---------- 建、删 ----------


def new_session(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str | None,
    title: str,
    provider_profile_id: str | None,
    model: str,
    kind: str,
) -> GenerationSession:
    """开一条生成会话。界面上点「新生成」和生成漏斗里没点名会话时现开的那条,走的都是这里。

    **必须有主**:列表按 `owner_user_id == 我 或 被共享` 过滤,没主人的会话连建它的人自己都看不见。
    生成会话默认不共享给工作区(见 domain/sharing.KINDS),所以这里只记下主人。
    """
    session = GenerationSession(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        title=title.strip() or "新生成",
        provider_profile_id=provider_profile_id,
        model=model,
        kind=kind,
    )
    db.add(session)
    db.flush()
    return session


def delete_session(db: Session, session: GenerationSession) -> None:
    """删会话,连同里面的生成记录、它们在任务总线上的那几行,和共享记录。"""
    job_ids = [
        job_id for job_id in db.scalars(select(GenerationJob.job_id).where(GenerationJob.session_id == session.id)) if job_id
    ]
    db.execute(delete(GenerationJob).where(GenerationJob.session_id == session.id))
    if job_ids:
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    db.execute(delete(GenerationSession).where(GenerationSession.id == session.id))
    sharing.forget(db, "generation_session", session.id)


# ---------- 他看得见的生成历史 ----------


def visible_history(
    db: Session, user: User, workspace_id: str, *, kind: str | None = None, session_id: str | None = None
) -> list[GenerationJob]:
    """这个人在这个工作区里看得见的生成记录,按时间正序;每条带上全部产出与花费(瞬态属性)。

    记录跟着它所属的会话走:私有会话里生成的东西不该在工作区的总列表里露出来 —— 否则「私有」只挡住了
    标题,内容还在。不属于任何会话的老记录(session_id 为空)照旧全工作区可见。
    """
    visible_sessions = select(GenerationSession.id).where(sharing.visible_filter(SHARE_KIND, user, workspace_id))
    stmt = select(GenerationJob).where(
        GenerationJob.workspace_id == workspace_id,
        (GenerationJob.session_id.is_(None)) | (GenerationJob.session_id.in_(visible_sessions)),
    )
    if session_id:
        if readable_session(db, user, session_id).workspace_id != workspace_id:
            raise NotVisible("Not found")
        stmt = stmt.where(GenerationJob.session_id == session_id)
    if kind:
        stmt = stmt.where(GenerationJob.kind == kind)
    # 按记录自身时间排序,不 join jobs:job 被任务中心清掉后(job_id 置空)
    # 记录仍要出现在会话历史里 —— inner join 会把它们整个吞掉。
    stmt = stmt.order_by(GenerationJob.created_at.asc(), GenerationJob.id.asc())
    generations = list(db.scalars(stmt))
    _attach_costs(db, generations)
    _attach_assets(db, generations)
    return generations


def _attach_assets(db: Session, generations: list[GenerationJob]) -> None:
    """把每条生成的**全部**产出贴到瞬态属性上,供 GenerationJobOut 读。

    result_asset_id 那一栏只放得下封面,而一次生成可能出多份(图像接口的 n)。真正的账在
    generated_assets 里 —— 每一份产出一行。封面排第一,其余按它们登记的顺序跟在后面。
    """
    job_ids = [g.job_id for g in generations if g.job_id]
    by_job: dict[str, list[str]] = {}
    if job_ids:
        for row in db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id.in_(job_ids))):
            by_job.setdefault(str(row.job_id), []).append(row.asset_id)
    for gen in generations:
        cover = gen.result_asset_id
        rest = [one for one in by_job.get(gen.job_id or "", []) if one != cover]
        gen.result_asset_ids = ([cover] if cover else []) + rest  # type: ignore[attr-defined]


def _attach_costs(db: Session, generations: list[GenerationJob]) -> None:
    """把各生成记录的计费(用量事件 source_type=generation_job)贴到瞬态属性上,供 GenerationJobOut 读。

    一条生成可能有多个事件(started/succeeded…):已知费用按币种各自求和(usage.costs_by_currency,
    人民币和美元不相加);有事件但都无价则计 unknown。
    """
    ids = [g.id for g in generations]
    if not ids:
        return
    scope = (ProviderUsageEvent.source_type == "generation_job", ProviderUsageEvent.source_id.in_(ids))
    costs = usage.costs_by_currency(db, *scope, group_by=(ProviderUsageEvent.source_id,))
    # 置信度取计过价的那几条的(它们同出一处估算);一条都没计上价的就是 unknown。
    confidence: dict[str, str] = {}
    for source_id, cost_micros, cost_confidence in db.execute(
        select(ProviderUsageEvent.source_id, ProviderUsageEvent.cost_micros, ProviderUsageEvent.cost_confidence).where(
            *scope
        )
    ).all():
        if cost_micros is not None:
            confidence[source_id] = cost_confidence
        else:
            confidence.setdefault(source_id, "unknown")
    for gen in generations:
        gen.costs = costs.get((gen.id,), [])  # type: ignore[attr-defined]
        gen.cost_confidence = confidence.get(gen.id)  # type: ignore[attr-defined]
