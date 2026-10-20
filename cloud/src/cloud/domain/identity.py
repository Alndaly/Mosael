"""身份:公开昵称、唯一短名、头像种子。

规则:

- **注册时不要求身份。** 账号可以先只有邮箱;第一次发布 / 评论时才要 `display_name`。
- 公开形状只有 `display_name` / `handle` / `avatar_seed`。**email 不在这个函数里出现。**
- `handle` 只能 `[a-z0-9_-]`,唯一,保留字不可占用;`display_name` 非空、有长度上限。
- 头像不存图片:只存一个短种子,P1 由前端算"昵称首字母 + 颜色"。
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud.errors import CloudError
from cloud.models import CloudUser

DISPLAY_NAME_MAX = 40
HANDLE_MAX = 24
HANDLE_RE = re.compile(r"^[a-z0-9_-]+$")

#: 这些短名留给路由 / 系统 / 官方账号。个人页 `/u/<handle>` 与 API 路径共用一套命名空间。
RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "anonymous",
        "api",
        "account",
        "community",
        "device",
        "devices",
        "help",
        "login",
        "logout",
        "me",
        "mosael",
        "null",
        "official",
        "privacy",
        "register",
        "root",
        "settings",
        "share",
        "shares",
        "signup",
        "static",
        "support",
        "system",
        "terms",
        "u",
        "undefined",
        "user",
        "users",
    }
)


def public_user(user: CloudUser) -> dict[str, object]:
    """公开响应里的"这是谁"。**只有这三列,email 永远不出现在这里。**"""
    return {
        "display_name": user.display_name,
        "handle": user.handle,
        "avatar_seed": user.avatar_seed,
    }


def account_user(user: CloudUser) -> dict[str, object]:
    """本人看到的账号形状(登录 / 注册 / `/me`)。邮箱是"自己的",不是公开字段。"""
    return {
        "id": user.id,
        "email": user.email,
        "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
        "created_at": user.created_at.isoformat(),
        **public_user(user),
    }


def new_handle() -> str:
    """自动短名。用户可以之后用 `PUT /me` 改成自己想要的;它只需要可读、可分享。"""
    return f"member-{secrets.token_hex(4)}"


def new_avatar_seed() -> str:
    return secrets.token_hex(4)


def ensure_identity(user: CloudUser) -> None:
    """写接口的前置条件。没有昵称 = 409(让界面弹"先起个名字"),不是 401、也不是 422。"""
    if not user.display_name:
        raise CloudError(409, "identity_required")


def _clean_display_name(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise CloudError(422, "display_name_required")
    if len(value) > DISPLAY_NAME_MAX:
        raise CloudError(422, "display_name_too_long", max=DISPLAY_NAME_MAX)
    return value


def _clean_handle(raw: str) -> str:
    value = raw.strip().lower()
    if len(value) > HANDLE_MAX or not HANDLE_RE.fullmatch(value):
        raise CloudError(422, "handle_invalid", max=HANDLE_MAX)
    if value in RESERVED_HANDLES:
        # 保留字用 409:名字本身合法,只是被占用了 —— 和"已经被别人用了"同一种处理。
        raise CloudError(409, "handle_reserved")
    return value


def set_identity(
    db: Session,
    user: CloudUser,
    *,
    display_name: str | None = None,
    handle: str | None = None,
) -> CloudUser:
    """`PUT /me`:改昵称 / 短名。

    第一次设置昵称时补一个头像种子和(如果还没有)自动短名。**唯一性由数据库的唯一索引兜底**:
    并发改同一个短名时,后到的那次撞 IntegrityError → 409,不靠"先 SELECT 再 UPDATE"。
    """
    name = _clean_display_name(display_name) if display_name is not None else None
    chosen = _clean_handle(handle) if handle is not None else None
    if name is None and chosen is None:
        return user

    for _attempt in range(5):
        if name is not None:
            user.display_name = name
            if not user.avatar_seed:
                user.avatar_seed = new_avatar_seed()
        if chosen is not None:
            user.handle = chosen
        elif not user.handle:
            user.handle = new_handle()
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if chosen is not None:
                raise CloudError(409, "handle_taken") from exc
            # 自动生成的短名撞了(概率极低):换一个再试,而不是让用户看到"短名被占"。
            continue
        return user
    raise CloudError(409, "handle_taken")
