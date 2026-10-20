"""社区分享的 HTTP 入口。

路由只做转译:解析请求、取当前用户(或游客)、调 `cloud.domain.shares`、按状态码返回。
校验、权限、统计、分页规则都在 domain 层,**这里不写业务分支**。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel

from cloud.api.deps import CurrentUser, DbSession, MaybeUser
from cloud.domain.shares import (
    add_comment,
    create_share,
    delete_comment,
    delete_share,
    favorite_share,
    get_share,
    get_share_payload,
    like_share,
    list_comments,
    list_shares,
    record_download,
)

router = APIRouter(tags=["shares"])


class ShareIn(BaseModel):
    #: `workflow` / `board`。别的值由 domain 回 422(带"只能是哪几个"的人话)。
    kind: str
    title: str
    summary: str | None = None
    #: 工程文件本体。`Any` 是有意的:服务端不解析结构,只量大小。
    payload: Any = None
    license: str | None = None


class CommentIn(BaseModel):
    body: str


@router.post("/shares", status_code=201)
def publish(body: ShareIn, user: CurrentUser, db: DbSession) -> dict[str, object]:
    share = create_share(
        db,
        user,
        kind=body.kind,
        title=body.title,
        summary=body.summary,
        payload=body.payload,
        license=body.license,
    )
    return {"share": share}


@router.get("/shares")
def browse(
    user: MaybeUser,
    db: DbSession,
    q: str = "",
    kind: str = "",
    sort: str = "new",
    limit: int = 20,
    cursor: str = "",
) -> dict[str, object]:
    items, next_cursor = list_shares(
        db, user, q=q, kind=kind, sort=sort, limit=limit, cursor=cursor
    )
    return {"items": items, "next_cursor": next_cursor}


@router.get("/shares/{share_id}")
def detail(share_id: str, user: MaybeUser, db: DbSession) -> dict[str, object]:
    return get_share(db, user, share_id)


@router.get("/shares/{share_id}/payload")
def payload(share_id: str, db: DbSession) -> dict[str, object]:
    return {"payload": get_share_payload(db, share_id)}


@router.post("/shares/{share_id}/download")
def download(share_id: str, db: DbSession) -> dict[str, object]:
    return {"payload": record_download(db, share_id)}


@router.delete("/shares/{share_id}", status_code=204)
def remove(share_id: str, user: CurrentUser, db: DbSession) -> Response:
    delete_share(db, user, share_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- 点赞 / 收藏


@router.post("/shares/{share_id}/like", status_code=204)
def like(share_id: str, user: CurrentUser, db: DbSession) -> Response:
    like_share(db, user, share_id, liked=True)
    return Response(status_code=204)


@router.delete("/shares/{share_id}/like", status_code=204)
def unlike(share_id: str, user: CurrentUser, db: DbSession) -> Response:
    like_share(db, user, share_id, liked=False)
    return Response(status_code=204)


@router.post("/shares/{share_id}/favorite", status_code=204)
def favorite(share_id: str, user: CurrentUser, db: DbSession) -> Response:
    favorite_share(db, user, share_id, favorited=True)
    return Response(status_code=204)


@router.delete("/shares/{share_id}/favorite", status_code=204)
def unfavorite(share_id: str, user: CurrentUser, db: DbSession) -> Response:
    favorite_share(db, user, share_id, favorited=False)
    return Response(status_code=204)


# ---------------------------------------------------------------- 评论


@router.get("/shares/{share_id}/comments")
def comments(
    share_id: str,
    db: DbSession,
    limit: int = 20,
    cursor: str = "",
) -> dict[str, object]:
    items, next_cursor = list_comments(db, share_id, limit=limit, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor}


@router.post("/shares/{share_id}/comments", status_code=201)
def comment(share_id: str, body: CommentIn, user: CurrentUser, db: DbSession) -> dict[str, object]:
    return {"comment": add_comment(db, user, share_id, body.body)}


@router.delete("/shares/{share_id}/comments/{comment_id}", status_code=204)
def remove_comment(share_id: str, comment_id: str, user: CurrentUser, db: DbSession) -> Response:
    delete_comment(db, user, share_id, comment_id)
    return Response(status_code=204)
