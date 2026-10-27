"""插件的调用记录:查最近几条、删一条、清空 —— 都只碰**这个人自己接的**那些实例的记录。

记录里带着每次调用的 input/output —— 别人的请求参数和返回内容,没有任何理由出现在我这儿。
领域只改对象,提交交给入口层(见 core/unit_of_work)。
"""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import PluginInvocation
from app.domain.plugins import instances as inst


class InvocationNotYours(LookupError):
    """记录所属的实例不是这个人接的。对他来说就是不存在。"""


def _mine(db: Session, user_id: str, instance_id: str | None) -> Select[tuple[PluginInvocation]]:
    stmt = select(PluginInvocation).where(PluginInvocation.instance_id.in_(inst.owned_ids(db, user_id)))
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    return stmt


def recent(db: Session, user_id: str, *, instance_id: str | None, limit: int) -> list[PluginInvocation]:
    """最新的 `limit` 条。

    **一定有上限。** 每条都带着完整输出,一条就可能上 MB;插件页只摆最近十条,却曾经一次拿回一个连接的全部
    上千条(七百多 MB),渲染进程解不动,界面反复崩溃(见 tools.invoke_host 的 `record`)。
    """
    return list(db.scalars(_mine(db, user_id, instance_id).order_by(PluginInvocation.created_at.desc()).limit(limit)))


def delete(db: Session, user_id: str, invocation_id: str) -> None:
    """删一条。记录不存在就什么都不做;是别人的就报 `InvocationNotYours` —— 删不得,也不该知道它存在。"""
    obj = db.get(PluginInvocation, invocation_id)
    if obj is None:
        return
    if inst.owned(db, obj.instance_id, user_id) is None:
        raise InvocationNotYours(invocation_id)
    db.delete(obj)


def clear(db: Session, user_id: str, *, instance_id: str | None) -> None:
    """清空**我自己**的调用记录;带 `instance_id` 只清该接入的(调用方先确认那个接入是他的)。"""
    for obj in db.scalars(_mine(db, user_id, instance_id)):
        db.delete(obj)
