"""首页仪表要的那一屏数字。

**为什么在领域里而不在路由里**:它回答的是「这个工作区里发生了什么」—— 近两周成功/失败了多少活、
素材按类型各有多少、发布去了哪些平台、花掉多少钱。这些问题和 HTTP 没有关系,而且不止首页一个
入口会问(以后的定时报告、飞书日报要的是同一份数字)。留在路由里时,那一百来行 SQL 谁也复用不了。

返回**普通字典**:领域不认识 api 层的 schema(那是出口的形状),由路由装配成 WorkspaceSummaryOut。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Job, Project, PublishAccount, PublishTask, Sequence, Workflow, now
from app.domain.publish import summary_bucket
from app.domain.usage import summarize_usage

#: 首页那两张图各看多少天。
SPAN_DAYS = 14


def workspace_summary(db: Session, workspace_id: str) -> dict[str, Any]:
    """这个工作区一屏能看完的统计。只读。"""

    def count(stmt) -> int:
        return int(db.scalar(stmt) or 0)

    week_ago = now() - timedelta(days=7)
    scoped = lambda model: select(func.count()).select_from(model).where(model.workspace_id == workspace_id)  # noqa: E731

    # 活动图:近 SPAN_DAYS 天逐日成功/失败(按终态时间 updated_at 归日,UTC),缺日补零。
    span_start = (now() - timedelta(days=SPAN_DAYS - 1)).date()
    day_rows = db.execute(
        select(func.date(Job.updated_at), Job.status, func.count())
        .where(
            Job.workspace_id == workspace_id,
            Job.status.in_(("succeeded", "failed")),
            Job.updated_at >= datetime.combine(span_start, datetime.min.time()),
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
        for offset in range(SPAN_DAYS)
    ]

    publish_day_rows = db.execute(
        select(func.date(PublishTask.updated_at), PublishTask.status, func.count())
        .where(
            PublishTask.workspace_id == workspace_id,
            PublishTask.updated_at >= datetime.combine(span_start, datetime.min.time()),
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
        for offset in range(SPAN_DAYS)
    ]

    kind_rows = db.execute(
        select(Asset.kind, func.count()).where(Asset.workspace_id == workspace_id).group_by(Asset.kind)
    ).all()
    asset_kinds = {str(kind): int(count_) for kind, count_ in kind_rows}
    publish_platform_rows = db.execute(
        select(PublishAccount.platform, func.count())
        .select_from(PublishTask)
        .join(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(PublishTask.workspace_id == workspace_id)
        .group_by(PublishAccount.platform)
    ).all()
    publish_platforms = {str(platform): int(count_) for platform, count_ in publish_platform_rows}
    usage = summarize_usage(db, workspace_id=workspace_id, days=SPAN_DAYS)

    return dict(
        daily=daily,
        asset_kinds=asset_kinds,
        publish_daily=publish_daily,
        publish_platforms=publish_platforms,
        usage_cost_micros=usage.total_cost_micros,
        usage_currency=usage.currency,
        usage_event_count=usage.event_count,
        usage_unknown_cost_events=usage.unknown_cost_events,
        usage_unpriced=usage.unpriced,
        usage_duration_seconds=usage.duration_seconds,
        usage_token_count=usage.token_count,
        usage_cache_read_tokens=usage.cache_read_tokens,
        usage_cache_write_tokens=usage.cache_write_tokens,
        usage_cache_hit_ratio=usage.cache_hit_ratio,
        usage_daily=usage.daily,
        usage_token_daily=usage.token_daily,
        usage_by_capability=usage.by_capability,
        usage_by_provider=usage.by_provider,
        project_count=count(scoped(Project)),
        asset_count=count(scoped(Asset)),
        sequence_count=count(scoped(Sequence)),
        workflow_count=count(scoped(Workflow)),
        running_jobs=count(scoped(Job).where(Job.status.in_(("queued", "running")))),
        week_jobs_succeeded=count(scoped(Job).where(Job.status == "succeeded", Job.updated_at >= week_ago)),
        week_jobs_failed=count(scoped(Job).where(Job.status == "failed", Job.updated_at >= week_ago)),
        publish_accounts=count(scoped(PublishAccount)),
        week_published=count(
            scoped(PublishTask).where(PublishTask.status == "success", PublishTask.updated_at >= week_ago)
        ),
    )
