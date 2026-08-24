"""对话分组:建、改名、删,以及一次拖放的落库。

**行创建收在这里**,路由只做鉴权与转述 —— 这是仓库的数据归属纪律(domain/ownership.py,
由 tests/test_data_ownership_ratchet.py 钉住):谁拥有这张表,谁才能造它的行。
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import AgentSession, AgentSessionGroup


def create_group(db: Session, *, workspace_id: str, name: str, owner_user_id: str | None) -> AgentSessionGroup:
    group = AgentSessionGroup(workspace_id=workspace_id, owner_user_id=owner_user_id, name=name.strip())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def rename_group(db: Session, group: AgentSessionGroup, name: str) -> AgentSessionGroup:
    group.name = name.strip()
    db.commit()
    db.refresh(group)
    return group


def set_group_order(db: Session, group: AgentSessionGroup, sort_order: int) -> AgentSessionGroup:
    group.sort_order = sort_order
    db.commit()
    db.refresh(group)
    return group


def delete_group(db: Session, group: AgentSessionGroup) -> None:
    """删掉分组,**里面的对话留着**(退回未分组)。

    分组是收纳方式,不是所有权 —— 删一个文件夹不该连着删掉里面的对话。清空成员这一步在这里
    显式做,不指望数据库级联:老库的 group_id 是迁移加的列,没有外键约束(见 db/migrations)。
    """
    db.execute(update(AgentSession).where(AgentSession.group_id == group.id).values(group_id=None))
    db.delete(group)
    db.commit()

