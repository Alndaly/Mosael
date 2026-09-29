"""会话分组:建、改名、删,以及一次拖放的落库。

从 `domain/agent/groups.py` 搬出来的 —— 分组不再只属于对话:生成会话用的是同一张表、
同一组接口,由 `kind` 分开(见 db/models.SessionGroup)。留在 `agent/` 下面时,生成那边
要用就只能反向 import 对话域,或者照抄一份。

**行创建收在这里**,路由只做转述(闸在 use_cases) —— 这是仓库的数据归属纪律(domain/ownership.py,
由 tests/test_data_ownership_ratchet.py 钉住):谁拥有这张表,谁才能造它的行。
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import AgentSession, GenerationSession, SessionGroup
from app.domain.permissions import NotVisible

#: 每种分组管着哪张会话表。删分组时要清空的就是它 —— 新增一种会话时在这里补一行,
#: 别在 delete_group 里写 if/else:漏掉一支的后果是成员留着一个指向空气的 group_id。
MEMBER_MODEL = {"agent": AgentSession, "generation": GenerationSession}


def create_group(db: Session, *, workspace_id: str, kind: str, name: str, owner_user_id: str | None) -> SessionGroup:
    group = SessionGroup(workspace_id=workspace_id, kind=kind, owner_user_id=owner_user_id, name=name.strip())
    db.add(group)
    db.flush()
    db.refresh(group)
    return group


def rename_group(db: Session, group: SessionGroup, name: str) -> SessionGroup:
    group.name = name.strip()
    return group


def set_group_order(db: Session, group: SessionGroup, sort_order: int) -> SessionGroup:
    group.sort_order = sort_order
    return group


def delete_group(db: Session, group: SessionGroup) -> None:
    """删掉分组,**里面的会话留着**(退回未分组)。

    分组是收纳方式,不是所有权 —— 删一个文件夹不该连着删掉里面的对话。清空成员这一步在这里
    显式做,不指望数据库级联:group_id 是迁移加的列,没有外键约束(见 db/migrations)。
    """
    model = MEMBER_MODEL[group.kind]
    db.execute(update(model).where(model.group_id == group.id).values(group_id=None))
    db.delete(group)


def list_groups(db: Session, workspace_id: str, kind: str) -> list[SessionGroup]:
    return list(
        db.scalars(
            select(SessionGroup)
            .where(SessionGroup.workspace_id == workspace_id, SessionGroup.kind == kind)
            .order_by(SessionGroup.sort_order, SessionGroup.created_at)
        )
    )


def resolve_member_group(db: Session, group_id: str, *, workspace_id: str, kind: str) -> SessionGroup | None:
    """把一个会话收进分组前,确认这个分组**接得住它**。

    三条都要查:存在、同一个工作区、同一种 kind。少了工作区那条,就能把会话塞进别人的分组
    (而分组按工作区列出,那条会话会在两边都显得不知从哪来);少了 kind 那条,对话能落进
    生成的分组里 —— 两边各自按 kind 列分组,于是它从此不出现在任何一摞里。

    返回 None 表示不该收 —— 由调用方决定报什么错。
    """
    group = db.get(SessionGroup, group_id)
    if group is None or group.workspace_id != workspace_id or group.kind != kind:
        return None
    return group


def move_into(db: Session, row: AgentSession | GenerationSession, group_id: str, *, kind: str) -> None:
    """把一条会话收进分组;空串 = 移出分组。分组得接得住它(见 resolve_member_group),否则 404。"""
    if group_id and resolve_member_group(db, group_id, workspace_id=row.workspace_id, kind=kind) is None:
        raise NotVisible("sessionGroupErr_notFound")
    row.group_id = group_id or None


def restore_updated_at(db: Session, row: AgentSession | GenerationSession, updated_at) -> None:
    """**收纳不是活动**:只改了分组的话,把会话的 updated_at 写回原值 —— 两边的会话列表都按它倒序排,
    收一次纳不该让它显得「刚用过」、把顺序搅了。对话和生成同一条规矩,所以只写这一份。

    **不能只是把属性赋回原值**:赋成原来的值,SQLAlchemy 的变更检测认为「没改」,这一列就不进 SET,
    而 onupdate=now 照常把它顶成现在。所以走显式 UPDATE —— 调用方在提交完这次修改之后再调,再提交一次。
    """
    model = type(row)
    db.execute(update(model).where(model.id == row.id).values(updated_at=updated_at))
