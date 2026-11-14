"""MosaelCloud 管理员角色:授予、撤销、最后一名守卫。

角色是 `cloud_users.role` 的 `member` / `admin`。它和 `official` 是两个独立事实:
官方内容账号不自动成为管理员,管理员也不一定是官方账号。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud.models import CloudUser

ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"


class RoleError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def is_admin(user: CloudUser) -> bool:
    return user.role == ROLE_ADMIN


def grant(db: Session, user: CloudUser) -> bool:
    if is_admin(user):
        return False
    user.role = ROLE_ADMIN
    db.flush()
    return True


def revoke(db: Session, user: CloudUser) -> bool:
    if not is_admin(user):
        return False
    remaining = db.scalar(
        select(func.count()).select_from(CloudUser).where(
            CloudUser.role == ROLE_ADMIN, CloudUser.id != user.id
        )
    )
    if not remaining:
        raise RoleError("last_admin")
    user.role = ROLE_MEMBER
    db.flush()
    return True


def admins(db: Session) -> list[CloudUser]:
    return list(
        db.scalars(
            select(CloudUser)
            .where(CloudUser.role == ROLE_ADMIN)
            .order_by(CloudUser.created_at, CloudUser.id)
        )
    )
