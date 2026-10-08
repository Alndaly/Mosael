"""统计页要的那一屏数字。

**为什么在领域里而不在路由里**:它回答的是「这个工作区里发生了什么」—— 窗口内成功/失败了多少活、
素材按类型各有多少、发布去了哪些平台、花掉多少钱。这些问题和 HTTP 没有关系,而且不止首页一个
入口会问(以后的定时报告、飞书日报要的是同一份数字)。留在路由里时,那一百来行 SQL 谁也复用不了。

返回**普通字典**:领域不认识 api 层的 schema(那是出口的形状),由路由装配成 WorkspaceSummaryOut。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    AuthSession,
    Job,
    Project,
    ProviderUsageEvent,
    PublishAccount,
    PublishTask,
    Sequence,
    User,
    Workflow,
    Workspace,
    now,
)
from app.domain.publish import summary_bucket
from app.domain.billing.usage import CostAmount, costs_by_currency, summarize_usage

#: 统计窗口的默认值:最近一个月。统计页和管理页用同一套 —— 两页上的「近 N 天」是同一个意思。
WINDOW_DAYS = 30
#: 能选的最长窗口。再长就是在扫全库了,而那不是这两页要回答的问题。
MAX_WINDOW_DAYS = 90
#: 管理页上「最近还在用」的判据。
ACTIVE_DAYS = 7


def workspace_summary(db: Session, workspace_id: str, *, days: int = WINDOW_DAYS) -> dict[str, Any]:
    """这个工作区一屏能看完的统计。只读。

    **窗口只有一个**(`days`:今天加上前 `days - 1` 天,从那天零点起,UTC)。任务、发布、花费的
    读数和图都按它算;项目、素材、序列、工作流、运行中是当前总数,素材构成也是。此前读数是
    「近 7 天」、图是「近 14 天」,同一页上两种窗口,两个数对不上还看不出为什么。
    """

    def count(stmt) -> int:
        return int(db.scalar(stmt) or 0)

    scoped = lambda model: select(func.count()).select_from(model).where(model.workspace_id == workspace_id)  # noqa: E731

    # 活动图:窗口内逐日成功/失败(按终态时间 updated_at 归日,UTC),缺日补零。
    span_start = (now() - timedelta(days=days - 1)).date()
    since = datetime.combine(span_start, datetime.min.time())
    day_rows = db.execute(
        select(func.date(Job.updated_at), Job.status, func.count())
        .where(
            Job.workspace_id == workspace_id,
            Job.status.in_(("succeeded", "failed")),
            Job.updated_at >= since,
        )
        .group_by(func.date(Job.updated_at), Job.status)
    ).all()
    by_day: dict[str, dict[str, int]] = {}
    for day, status, count_ in day_rows:
        by_day.setdefault(str(day), {})[str(status)] = int(count_)
    daily = [
        dict(
            date=str(span_start + timedelta(days=offset)),
            succeeded=by_day.get(str(span_start + timedelta(days=offset)), {}).get("succeeded", 0),
            failed=by_day.get(str(span_start + timedelta(days=offset)), {}).get("failed", 0),
        )
        for offset in range(days)
    ]

    publish_day_rows = db.execute(
        select(func.date(PublishTask.updated_at), PublishTask.status, func.count())
        .where(
            PublishTask.workspace_id == workspace_id,
            PublishTask.updated_at >= since,
        )
        .group_by(func.date(PublishTask.updated_at), PublishTask.status)
    ).all()
    publish_by_day: dict[str, dict[str, int]] = {}
    for day, status, count_ in publish_day_rows:
        bucket = summary_bucket(str(status))
        publish_by_day.setdefault(str(day), {}).setdefault(bucket, 0)
        publish_by_day[str(day)][bucket] += int(count_)
    publish_daily = [
        dict(
            date=str(span_start + timedelta(days=offset)),
            succeeded=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("succeeded", 0),
            failed=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("failed", 0),
            active=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("active", 0),
            blocked=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("blocked", 0),
        )
        for offset in range(days)
    ]

    # 素材的数和构成**按素材库的口径**:中间产物(逐句配音的一句……,ADR 0036)不算。此前把它们算进来,统计写
    # 1267、点进素材库只有 282,构成被九百多段配音片段淹没(体检 UM-12)。
    kind_rows = db.execute(
        select(Asset.kind, func.count())
        .where(Asset.workspace_id == workspace_id, Asset.intermediate == "")
        .group_by(Asset.kind)
    ).all()
    asset_kinds = {str(kind): int(count_) for kind, count_ in kind_rows}
    publish_platform_rows = db.execute(
        select(PublishAccount.platform, func.count())
        .select_from(PublishTask)
        .join(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(PublishTask.workspace_id == workspace_id, PublishTask.updated_at >= since)
        .group_by(PublishAccount.platform)
    ).all()
    publish_platforms = {str(platform): int(count_) for platform, count_ in publish_platform_rows}
    usage = summarize_usage(db, workspace_id=workspace_id, days=days)

    return dict(
        window_days=days,
        daily=daily,
        asset_kinds=asset_kinds,
        publish_daily=publish_daily,
        publish_platforms=publish_platforms,
        usage_costs=usage.costs,
        usage_event_count=usage.event_count,
        usage_unknown_cost_events=usage.unknown_cost_events,
        usage_unpriced=usage.unpriced,
        usage_cache_hit_ratio=usage.cache_hit_ratio,
        usage_daily=usage.daily,
        usage_token_daily=usage.token_daily,
        usage_by_provider=usage.by_provider,
        project_count=count(scoped(Project)),
        asset_count=count(scoped(Asset).where(Asset.intermediate == "")),
        sequence_count=count(scoped(Sequence)),
        workflow_count=count(scoped(Workflow)),
        running_jobs=count(scoped(Job).where(Job.status.in_(("queued", "running")))),
        jobs_succeeded=sum(day["succeeded"] for day in daily),
        jobs_failed=sum(day["failed"] for day in daily),
        published=sum(day["succeeded"] for day in publish_daily),
    )


def deployment_overview(db: Session, *, days: int = WINDOW_DAYS) -> dict[str, Any]:
    """管理页总览 —— **这台部署**的状况,不分工作区。只读。口径(按人分花销、`days` 窗口怎么算)
    写在出口 routes/admin.overview 上,那段也是这个接口的 API 文档。"""
    today = now().date()
    first_day = today - timedelta(days=days - 1)
    since = datetime.combine(first_day, time.min)
    active_since = now() - timedelta(days=ACTIVE_DAYS)

    active = db.scalar(
        select(func.count(func.distinct(AuthSession.user_id))).where(AuthSession.last_seen_at >= active_since)
    )
    counted = {
        str(day): (int(total), int(failed or 0))
        for day, total, failed in db.execute(
            select(
                func.date(Job.created_at),
                func.count(),
                func.sum(func.iif(Job.status == "failed", 1, 0)),
            )
            .where(Job.created_at >= since)
            .group_by(func.date(Job.created_at))
        ).all()
    }
    # **没跑任务的那天也要有一格**,记 0。只回有数的日子,前端的类目轴就会把空着的日子挤掉 ——
    # 九十天里跑过三天,画出来是三根挨着的柱子,看着像"这三天连着很忙"。
    jobs_by_day = []
    for offset in range(days):
        day = str(first_day + timedelta(days=offset))
        total, failed = counted.get(day, (0, 0))
        jobs_by_day.append({"day": day, "total": total, "failed": failed})
    # 用量事件记的是"哪次调用花了多少",归属在 job 上 —— 顺着 job.created_by 就知道是谁花的。
    # **连不上人的也要列出来**(外连接,落进 user_id 为空的「无归属」那一行):智能体对话、画板、工作流节点里的调用
    # 不挂任务。此前内连接把它们整个丢掉,条形加起来只有合计的零头(体检 UM-11,维护者库上 94% 的美元花费归不到人)。
    # 写入时就记下是谁花的,等 ADR 定(草稿 0050);在那之前至少让各行加起来等于合计。
    in_window = ProviderUsageEvent.created_at >= since
    calls = {
        user_id: (str(username or ""), int(count_ or 0))
        for user_id, username, count_ in db.execute(
            select(Job.created_by, User.username, func.count())
            .select_from(ProviderUsageEvent)
            .join(Job, Job.id == ProviderUsageEvent.job_id, isouter=True)
            .join(User, User.id == Job.created_by, isouter=True)
            .where(in_window)
            .group_by(Job.created_by, User.username)
        ).all()
    }
    spent = costs_by_currency(
        db, in_window, group_by=(Job.created_by,), join=((Job, Job.id == ProviderUsageEvent.job_id),), outer=True
    )
    totals = costs_by_currency(db, in_window).get((), [])
    # **排序不把各币种加起来比。**按这台部署的主要币种(计过价次数最多的那种)上的金额排,
    # 再按调用次数 —— 单币种部署(绝大多数)里这就是"谁花得最多";混着两种钱时,另一种钱花得多
    # 的人排在后面,但他的那笔照样原样列出来,不会被换算或吞掉。
    primary = totals[0].currency if totals else ""

    def primary_micros(costs: list[CostAmount]) -> int:
        return next((amount.micros for amount in costs if amount.currency == primary), 0)

    # 「无归属」那一行排在最后:它是没记下是谁的余数,不是一个可以去谈的人;前二十名也给它留一个位置。
    people = sorted(
        ((user_id, row) for user_id, row in calls.items() if user_id is not None),
        key=lambda item: (primary_micros(spent.get((item[0],), [])), item[1][1]),
        reverse=True,
    )[:20]
    unattributed = [(None, calls[None])] if None in calls else []
    ranked = people + unattributed
    return dict(
        costs=totals,
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        active_users_7d=int(active or 0),
        workspaces=db.scalar(select(func.count()).select_from(Workspace)) or 0,
        assets=db.scalar(select(func.count()).select_from(Asset).where(Asset.intermediate == "")) or 0,
        jobs_by_day=jobs_by_day,
        spend_by_user=[
            {"user_id": str(user_id or ""), "username": username, "costs": spent.get((user_id,), []), "calls": count_}
            for user_id, (username, count_) in ranked
        ],
        window_days=days,
    )
