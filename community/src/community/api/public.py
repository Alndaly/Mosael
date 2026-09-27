"""统计(`/stats/*`)与作者主页(`/users/{handle}`)—— 官网的可视化读这些(ADR 0026 第 7 节)。"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from community.api.deps import Ctx, Db
from community.api.items import public_items
from community.api.views import item_summaries, public_user, share_summary
from community.errors import ApiError
from community.models import (
    KIND_PLUGIN,
    KIND_WORKFLOW,
    VERSION_APPROVED,
    VISIBILITY_PUBLIC,
    Item,
    ItemDailyStat,
    ItemVersion,
    Share,
    ShareVersion,
    User,
)
from community.stats import fill_days, today
from mosael_formats.i18n import current_locale

router = APIRouter(tags=["stats"])

#: 逐日趋势能看的指标。
METRICS = ("signups", "downloads", "views", "likes", "shares", "submissions")
TOP_N = 5
PROFILE_LIST = 12
HEATMAP_DAYS = 365


def _public_shares():
    return select(Share).where(Share.visibility == VISIBILITY_PUBLIC, Share.revoked_at.is_(None), Share.hidden_at.is_(None))


@router.get("/stats/overview")
def overview(ctx: Ctx, db: Db) -> dict:
    count = lambda stmt: int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)  # noqa: E731
    top = {}
    for kind in (KIND_WORKFLOW, KIND_PLUGIN):
        rows = list(db.scalars(public_items(kind).order_by(Item.downloads_total.desc(), Item.id.desc()).limit(TOP_N)))
        top[f"top_{kind}s"] = item_summaries(ctx, db, rows)
    since = today() - timedelta(days=29)
    return {
        "users": count(select(User.id).where(User.is_official.is_(False))),
        "workflows": count(public_items(KIND_WORKFLOW)),
        "plugins": count(public_items(KIND_PLUGIN)),
        "shares": count(_public_shares()),
        "downloads": int(db.scalar(select(func.coalesce(func.sum(Item.downloads_total), 0))) or 0),
        "downloads_30d": int(
            db.scalar(select(func.coalesce(func.sum(ItemDailyStat.downloads), 0)).where(ItemDailyStat.day >= since)) or 0
        ),
        **top,
    }


def daily_counts(db: Db, created_at, where, start) -> dict:
    """某张表按天数行数。日期按 UTC 切。"""
    day = func.date(created_at)
    rows = db.execute(select(day, func.count()).where(created_at >= start, *where).group_by(day)).all()
    return {str(key)[:10]: int(value) for key, value in rows}


@router.get("/stats/timeseries")
def timeseries(db: Db, metric: str, days: int = Query(default=30, ge=1, le=365)) -> dict:
    if metric not in METRICS:
        raise ApiError(422, "metric_invalid", metric=metric)
    start_day = today() - timedelta(days=days - 1)
    start = datetime.combine(start_day, time.min, tzinfo=UTC)
    if metric in ("downloads", "views", "likes"):
        column = getattr(ItemDailyStat, metric)
        rows = db.execute(
            select(ItemDailyStat.day, func.sum(column)).where(ItemDailyStat.day >= start_day).group_by(ItemDailyStat.day)
        ).all()
        values = {key: int(value or 0) for key, value in rows}
    elif metric == "signups":
        values = daily_counts(db, User.created_at, [User.is_official.is_(False)], start)
    elif metric == "shares":
        values = daily_counts(db, ShareVersion.created_at, [ShareVersion.number == 1], start)
    else:
        values = daily_counts(db, ItemVersion.created_at, [], start)
    return {"metric": metric, "days": days, "points": [{"date": one["date"], "value": one["count"]} for one in fill_days(values, start_day, days)]}


@router.get("/users/{handle}")
def profile(handle: str, ctx: Ctx, db: Db) -> dict:
    """作者主页:TA 的工作流、插件、公开画板,和近一年逐日贡献(用于热力图)。"""
    user = db.scalars(select(User).where(User.handle == handle.strip().lower())).first()
    if user is None or user.status != "active":
        raise ApiError(404, "user_not_found")
    out: dict = {"user": public_user(ctx, db, user)}
    for kind in (KIND_WORKFLOW, KIND_PLUGIN):
        stmt = public_items(kind).where(Item.owner_id == user.id)
        out[f"{kind}s"] = item_summaries(ctx, db, list(db.scalars(stmt.order_by(Item.updated_at.desc()).limit(PROFILE_LIST))))
        out[f"{kind}s_count"] = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    shares_stmt = _public_shares().where(Share.owner_id == user.id)
    shares = list(db.scalars(shares_stmt.order_by(Share.updated_at.desc()).limit(PROFILE_LIST)))
    versions = {
        one.id: one for one in db.scalars(select(ShareVersion).where(ShareVersion.id.in_({row.current_version_id for row in shares})))
    }
    locale = current_locale()
    out["boards"] = [share_summary(ctx, db, row, user, versions.get(row.current_version_id or ""), locale) for row in shares]
    out["boards_count"] = int(db.scalar(select(func.count()).select_from(shares_stmt.subquery())) or 0)

    start_day = today() - timedelta(days=HEATMAP_DAYS - 1)
    start = datetime.combine(start_day, time.min, tzinfo=UTC)
    contributions: dict[str, int] = {}
    # 贡献 = 公开出去的版本(工作流的每一版、审核通过的插件版本)+ 公开画板的每一次分享。
    submitted = daily_counts(
        db,
        ItemVersion.created_at,
        [ItemVersion.submitter_id == user.id, ItemVersion.status == VERSION_APPROVED],
        start,
    )
    shared = daily_counts(
        db,
        ShareVersion.created_at,
        [ShareVersion.share_id.in_(select(Share.id).where(Share.owner_id == user.id, Share.visibility == VISIBILITY_PUBLIC, Share.revoked_at.is_(None)))],
        start,
    )
    for source in (submitted, shared):
        for key, value in source.items():
            contributions[key] = contributions.get(key, 0) + value
    out["contributions"] = fill_days(contributions, start_day, HEATMAP_DAYS)
    return out


__all__ = ["METRICS", "router"]
