"""身份与个人页:`PUT /me`、`GET /users/{handle}/shares`。

`GET /me` 在 `api/auth.py`(它和登录 / 注册共用会话的故事);这里只加改身份和按人列分享。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from cloud.api.deps import CurrentUser, DbSession, MaybeUser
from cloud.domain.identity import account_user, set_identity
from cloud.domain.shares import list_user_shares

router = APIRouter(tags=["profile"])


class ProfileIn(BaseModel):
    """两个字段都可选:只改昵称、只改短名、或者一次都给。"""

    display_name: str | None = None
    handle: str | None = None


@router.put("/me")
def update_me(body: ProfileIn, user: CurrentUser, db: DbSession) -> dict[str, object]:
    updated = set_identity(db, user, display_name=body.display_name, handle=body.handle)
    return {"user": account_user(updated)}


@router.get("/users/{handle}/shares")
def user_shares(
    handle: str,
    user: MaybeUser,
    db: DbSession,
    limit: int = 20,
    cursor: str = "",
) -> dict[str, object]:
    items, next_cursor = list_user_shares(db, user, handle, limit=limit, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor}
