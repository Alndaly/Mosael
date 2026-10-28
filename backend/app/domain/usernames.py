"""用户名的规矩:怎么规整、撞名了怎么起一个空着的。

**叶子模块。** 建号、改资料(accounts)和按用户名邀请成员(members)都要按同一条规矩认用户名;写在其中一个里,
另一个就得回头 import 它,而 accounts 本来就依赖 members(邀请码、独占的工作区)—— 两个模块成了环。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


def normalize_username(value: str) -> str:
    return value.strip().lower()


def free_username(db: Session, base: str) -> str:
    """`base` 没人用就是它,否则依次试 base2、base3……(第三方登录拿邮箱局部名起名时用)。"""
    username = normalize_username(base)
    suffix = 1
    while db.scalar(select(User).where(User.username == username)) is not None:
        suffix += 1
        username = f"{normalize_username(base)}{suffix}"
    return username


__all__ = ["free_username", "normalize_username"]
