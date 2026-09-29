"""「谁还指着它」:按引用表(db/references)反查。

返回来源 id 的子查询,调用方拿它去查来源表 —— 来源被级联删掉时引用表里会留下几行过期的,
回到来源表查一次就自然滤掉了。
"""

from __future__ import annotations

from sqlalchemy import Select, select

from app.db.models import RecordReference


def referrers(target_kind: str, target_id: str, source_kind: str, *, how: str | None = None) -> Select:
    stmt = select(RecordReference.source_id).where(
        RecordReference.target_kind == target_kind,
        RecordReference.target_id == target_id,
        RecordReference.source_kind == source_kind,
    )
    return stmt if how is None else stmt.where(RecordReference.how == how)
