"""任务与任务事件的保留清理。

这里是任务行唯一被物理删除的地方(ADR 0050);任务中心的「清空已结束」只挪水位线。
删的时候攥着写锁,所以既提供只读的「该删哪些」计划,也提供按批删除,调用方自己定批大小。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, union_all
from sqlalchemy.orm import Session

from app.core.db import Base
from app.db.models import Job, TaskEvent, now as models_now
from app.domain.jobs.constants import TERMINAL_STATUSES

#: 已结束的任务保留最近这么多条事件;工作流任务在窗口内全留。
TERMINAL_KEEP_EVENTS = 5
EVENT_RETENTION_DAYS = 30

#: 一批最多删这么多条任务事件。删的时候攥着写锁:一批要短,别的写入(请求、任务进度)才等得过 busy_timeout。
PRUNE_BATCH = 2000


def prunable_task_events(db: Session, *, now: datetime | None = None) -> list[str]:
    """按保留规则该删的任务事件 id。**只读** —— 不占写锁;删由 `delete_task_events` 分批做(见 workers/scheduler.prune_events)。

    规则:进行中的任务全留;已结束的留最近 TERMINAL_KEEP_EVENTS 条(工作流在窗口内全留);结束超过 EVENT_RETENTION_DAYS
    天的事件全删,任务那一行留着。

    **判据是一条集合式查询,不把任务读成 ORM 对象。** 此前逐个任务查、逐个删,而 ORM 的 DELETE 每一次都把身份映射里
    的全部对象过一遍(默认的 synchronize_session):一年的量(三万多个任务)清一次 67 秒,全程攥着写锁 ——
    期间别的写入 5 秒后报 database is locked。
    """
    reference = now or models_now()  # utcnow() is deprecated; models_now is the same naive UTC
    cutoff = reference - timedelta(days=EVENT_RETENTION_DAYS)
    finished = Job.status.in_(TERMINAL_STATUSES)
    expired = (
        select(TaskEvent.id.label("id"))
        .join(Job, Job.id == TaskEvent.job_id)
        .where(finished, Job.updated_at < cutoff)
    )
    # 工作流历史靠 started/finished/failed 事件配对还原每一个节点。通用的“只留最后 5 条”
    # 会稳定地裁掉前半程，让失败运行看起来只执行了最后一个报错节点。30 天窗口已经给存储
    # 设了明确上限；窗口内保留完整工作流事件，才能让“执行历史”名副其实。
    ranked = (
        select(
            TaskEvent.id.label("id"),
            func.row_number()
            .over(partition_by=TaskEvent.job_id, order_by=(TaskEvent.created_at.desc(), TaskEvent.id.desc()))
            .label("newest_first"),
        )
        .join(Job, Job.id == TaskEvent.job_id)
        .where(finished, Job.updated_at >= cutoff, Job.kind != "workflow")
        .subquery()
    )
    trimmed = select(ranked.c.id).where(ranked.c.newest_first > TERMINAL_KEEP_EVENTS)
    return list(db.scalars(union_all(expired, trimmed)))


def delete_task_events(db: Session, ids: list[str]) -> int:
    """按 id 删一批任务事件(不提交)。返回删了几条。"""
    if not ids:
        return 0
    db.execute(delete(TaskEvent).where(TaskEvent.id.in_(ids)).execution_options(synchronize_session=False))
    return len(ids)


def prune_task_events(db: Session, *, now: datetime | None = None) -> int:
    """一次删完(一个事务)。给测试和小库用;调度线程走分批的 `workers/scheduler.prune_events`。"""
    ids = prunable_task_events(db, now=now)
    return sum(delete_task_events(db, ids[start:start + PRUNE_BATCH]) for start in range(0, len(ids), PRUNE_BATCH))


@dataclass(frozen=True)
class _JobRow:
    """建保留清理那份计划时读的几列 —— 不把任务读成 ORM 对象(见 `expired_job_trees`)。"""

    id: str
    parent_job_id: str | None
    status: str
    updated_at: datetime


def _referenced_job_ids(db: Session) -> set[str]:
    """保留清理不删的任务:别处的记录还指着它(ADR 0050 D29)。

    「别处的记录」按外键认,不在这里点名是哪几张表(任务域不认识发布单、生成记录这些):指着 `jobs.id`、任务删了只是**置空**的
    那几列 —— 定时任务的运行记录、AI Studio 的生成记录、发布记录、用量事件。它们各自是一份「这一次是怎么跑的 / 花了多少」,
    任务删了就只剩一个空的 job_id。级联删除的那几张(任务事件、运行产出全文)本来就是任务的一部分,跟着任务走,不算。
    """

    kept: set[str] = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == Job.__tablename__ and fk.ondelete == "SET NULL":
                column = fk.parent
                kept |= set(db.scalars(select(column).where(column.is_not(None)).distinct()))
    return kept


def expired_job_trees(db: Session, *, cutoff: datetime) -> list[str]:
    """保留清理要删的任务 id:结束在 `cutoff` 之前的**整棵树**(顶层任务连同它收纳的子任务)。只读 —— 删由 `delete_jobs`
    分批做(见 workers/scheduler.prune_jobs)。这是任务行唯一被物理删除的地方(ADR 0050):任务中心的「清空已结束」只挪水位线。

    一棵树整棵删或整棵留:
    - 树里有一行还没结束(顶层结束了、它派生的代理转码还在跑),整棵留着 —— 删了父任务,还在跑的那个就成了孤儿;
    - 树里有一行结束得不够久,整棵留着 —— 父任务的详情要能读到每一步;
    - 树里有一行被别处的记录指着(`_referenced_job_ids`),整棵留着。

    父任务早就不在了的行当作顶层(旧版本的「清空已结束」留下的孤儿)。全部署一起算:保留多久是这台部署的事(部署设置)。
    """
    rows = [
        _JobRow(row.id, row.parent_job_id, row.status, row.updated_at)
        for row in db.execute(select(Job.id, Job.parent_job_id, Job.status, Job.updated_at)).all()
    ]
    kept_ids = _referenced_job_ids(db)
    present = {row.id for row in rows}
    children: dict[str, list[_JobRow]] = {}
    for row in rows:
        if row.parent_job_id:
            children.setdefault(row.parent_job_id, []).append(row)

    def tree(root: _JobRow) -> list[_JobRow]:
        nodes, frontier = [root], [root]
        while frontier:
            kids = children.get(frontier.pop().id, [])
            nodes.extend(kids)
            frontier.extend(kids)
        return nodes

    doomed: list[str] = []
    for root in rows:
        if root.parent_job_id in present:
            continue
        nodes = tree(root)
        if any(node.status not in TERMINAL_STATUSES or node.updated_at >= cutoff or node.id in kept_ids for node in nodes):
            continue
        doomed.extend(node.id for node in nodes)
    return doomed


#: 保留清理一批删多少个任务。删的时候攥着写锁(连带它们的事件、运行产出、外键上的置空),一批要短。
DELETE_JOBS_BATCH = 500


def delete_jobs(db: Session, ids: list[str]) -> int:
    """按 id 删一批任务连同它们的事件(不提交);运行产出由外键级联跟着走。返回删了几个。批的大小由调用方定(见 DELETE_JOBS_BATCH)。"""
    if not ids:
        return 0
    db.execute(delete(TaskEvent).where(TaskEvent.job_id.in_(ids)).execution_options(synchronize_session=False))
    db.execute(delete(Job).where(Job.id.in_(ids)).execution_options(synchronize_session=False))
    return len(ids)
