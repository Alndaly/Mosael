"""一个人在界面上叫什么。

**叶子模块,自成一个包。** 修订的作者、定时任务的主人、确认单的发起人……好几个领域都要把一个用户 id 说成人名;
写在 members 里的话,工作流为了一个名字就得依赖账号管理那一整套(删账号要回头清工作流),两个包成了环
(见 tests/test_import_layering)。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import User


def display_name(db: Session, user_id: str | None) -> str:
    """显示名,没有就用户名;账号不在了是空串。"""
    person = db.get(User, user_id) if user_id else None
    return (person.display_name or person.username) if person is not None else ""


__all__ = ["display_name"]
