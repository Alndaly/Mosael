"""社区数据:下载、浏览、点赞按天聚合(每项每天一行),以及热度分。"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from community.db import utcnow
from community.models import Item, ItemDailyStat

METRIC_COLUMNS = {"downloads": "downloads", "views": "views", "likes": "likes"}
TOTAL_COLUMNS = {"downloads": "downloads_total", "views": "views_total", "likes": "likes_total"}
TREND_WEIGHTS = {"downloads": 1.0, "likes": 3.0, "views": 0.1}
TREND_DAYS = 7


def today() -> date:
    return utcnow().date()


def bump(db: Session, item: Item, metric: str, delta: int = 1) -> None:
    """给这一项今天的某个数加 `delta`,总数跟着加,热度重算。调用方负责 commit。

    「按天一行」用 update-then-insert:先试着加到今天那一行上,没有这一行再插;两个请求同时插的那一个
    撞唯一约束,退回去再加一次。
    """
    column = METRIC_COLUMNS[metric]
    day = today()
    if delta > 0:
        for _ in range(2):
            changed = db.execute(
                update(ItemDailyStat)
                .where(ItemDailyStat.item_id == item.id, ItemDailyStat.day == day)
                .values({column: getattr(ItemDailyStat, column) + delta})
            ).rowcount
            if changed:
                break
            try:
                with db.begin_nested():
                    db.add(ItemDailyStat(item_id=item.id, day=day, **{**{"downloads": 0, "views": 0, "likes": 0}, column: delta}))
                break
            except IntegrityError:
                continue
    total = TOTAL_COLUMNS[metric]
    setattr(item, total, max(0, (getattr(item, total) or 0) + delta))
    refresh_trend(db, item)


def refresh_trend(db: Session, item: Item) -> None:
    since = today() - timedelta(days=TREND_DAYS - 1)
    row = db.execute(
        select(
            func.coalesce(func.sum(ItemDailyStat.downloads), 0),
            func.coalesce(func.sum(ItemDailyStat.likes), 0),
            func.coalesce(func.sum(ItemDailyStat.views), 0),
        ).where(ItemDailyStat.item_id == item.id, ItemDailyStat.day >= since)
    ).one()
    downloads, likes, views = (int(value or 0) for value in row)
    item.trend_score = (
        downloads * TREND_WEIGHTS["downloads"] + likes * TREND_WEIGHTS["likes"] + views * TREND_WEIGHTS["views"]
    )


def item_series(db: Session, item_id: str, metric: str, days: int) -> list[dict]:
    column = getattr(ItemDailyStat, METRIC_COLUMNS[metric])
    start = today() - timedelta(days=days - 1)
    rows = dict(
        db.execute(
            select(ItemDailyStat.day, column).where(ItemDailyStat.item_id == item_id, ItemDailyStat.day >= start)
        ).all()
    )
    return fill_days(rows, start, days)


def fill_days(values: dict, start: date, days: int) -> list[dict]:
    """把稀疏的「日期 → 数」补成连续的 `[{date, count}]`,缺的天是 0。"""
    normalized = {(key if isinstance(key, date) else date.fromisoformat(str(key)[:10])): int(value or 0) for key, value in values.items()}
    return [
        {"date": (start + timedelta(days=offset)).isoformat(), "count": normalized.get(start + timedelta(days=offset), 0)}
        for offset in range(days)
    ]


__all__ = ["METRIC_COLUMNS", "bump", "fill_days", "item_series", "refresh_trend", "today"]
