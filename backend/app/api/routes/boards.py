"""创意画板的路由。薄的一层:认人 + 把领域错误翻成 HTTP。画布的规矩、画板上的动作全在 domain/boards。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BoardCreate, BoardDuplicate, BoardOut, BoardRun, BoardUpdate
from app.db.models import Board
from app.domain.boards import (
    BoardDomainError,
    BoardNotFound,
    BoardRevisionConflict,
    create_board,
    delete_board,
    duplicate_board,
    get_board,
    list_boards,
    update_board,
)
from app.domain.boards import producers
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm, owning_workspace

router = APIRouter(tags=["boards"])


def _board_http_error(exc: BoardDomainError) -> HTTPException:
    """领域错误 → HTTP。**按类型分**,不按报错文字里有没有"不存在"。"""
    if isinstance(exc, BoardRevisionConflict):
        return HTTPException(
            status_code=409,
            detail={
                "code": "board_revision_conflict",
                "base_revision": exc.base_revision,
                "current_revision": exc.current_revision,
                "message": str(exc),
            },
        )
    if isinstance(exc, producers.ProducerFailed):
        # 产出者那一侧没做成:状态码由产出者声明(见 producers.Producer.failure_status)。
        return HTTPException(status_code=exc.status, detail=str(exc))
    return HTTPException(status_code=404 if isinstance(exc, BoardNotFound) else 400, detail=str(exc))


@router.get("/boards", response_model=list[BoardOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Board]:
    ensure_workspace_access(db, user, workspace_id)
    return list_boards(db, workspace_id)


@router.get("/boards/{board_id}", response_model=BoardOut)
def read(board_id: str, db: DbSession, user: CurrentUser, workspace_id: str | None = None) -> Board:
    """`workspace_id` **可选** —— 画板自带归属,和素材/工作流那两条详情路由一致(同 notes.read)。"""
    ws = workspace_id or owning_workspace(db, Board, board_id)
    ensure_workspace_access(db, user, ws)
    try:
        return get_board(db, ws, board_id)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc


@router.post("/boards", response_model=BoardOut)
def create(body: BoardCreate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return create_board(db, workspace_id=body.workspace_id, name=body.name, canvas=body.canvas, actor_id=user.id)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc


@router.post("/boards/{board_id}/duplicate", response_model=BoardOut)
def duplicate(board_id: str, body: BoardDuplicate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return duplicate_board(
            db, workspace_id=body.workspace_id, board_id=board_id, name=body.name, actor_id=user.id
        )
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc


@router.patch("/boards/{board_id}", response_model=BoardOut)
def update(board_id: str, body: BoardUpdate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return update_board(
            db,
            workspace_id=body.workspace_id,
            board_id=board_id,
            name=body.name,
            canvas=body.canvas,
            base_revision=body.base_revision,
            actor_id=user.id,
        )
    except BoardDomainError as exc:
        # 「画板不存在」是 404,「画布不合法」是 400 —— 两者对调用方意味着完全不同的下一步。
        raise _board_http_error(exc) from exc


@router.delete("/boards/{board_id}")
def remove(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    try:
        delete_board(db, workspace_id, board_id, actor_id=user.id)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    return {"ok": True}


@router.post("/boards/{board_id}/run", response_model=BoardOut)
def run(board_id: str, body: BoardRun, db: DbSession, user: CurrentUser) -> Board:
    """在画板上跑一个产出者,产出落回那一格(见 boards.producers.run)。

    画板上一切产出(生成、写字、念出来、截一段)都走这一条 —— 此前是四条各自的路由和请求体。
    跑它要什么权限由产出者声明。
    """
    try:
        producer = producers.get_producer(body.producer)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    ensure_workspace_perm(db, user, body.workspace_id, producer.permission)
    try:
        return producers.run(
            db,
            producers.RunRequest(
                workspace_id=body.workspace_id,
                board_id=board_id,
                item_id=body.item_id,
                kind=body.kind,
                x=body.x,
                y=body.y,
                base_revision=body.base_revision,
                actor_id=user.id,
                producer=producer.id,
                form=dict(body.form or {}),
            ),
        )
    except producers.ProducerFormInvalid as exc:
        # 表单是请求体的一部分,只是形状由产出者声明 —— 和请求体校验失败回同一种 422。
        raise RequestValidationError(
            [{**one, "loc": ("body", "form", *one.get("loc", ()))} for one in exc.errors]
        ) from exc
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
