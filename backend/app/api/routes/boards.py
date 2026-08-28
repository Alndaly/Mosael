"""创意画板的路由。薄的一层:鉴权 + 把领域错误翻成 400,画布的规矩全在 domain/boards。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BoardCreate, BoardOut, BoardUpdate
from app.db.models import Board
from app.domain.boards import (
    BoardDomainError,
    create_board,
    delete_board,
    get_board,
    list_boards,
    update_board,
)
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm

router = APIRouter(tags=["boards"])


@router.get("/boards", response_model=list[BoardOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Board]:
    ensure_workspace_access(db, user, workspace_id)
    return list_boards(db, workspace_id)


@router.get("/boards/{board_id}", response_model=BoardOut)
def read(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_access(db, user, workspace_id)
    try:
        return get_board(db, workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/boards", response_model=BoardOut)
def create(body: BoardCreate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return create_board(db, workspace_id=body.workspace_id, name=body.name, canvas=body.canvas)
    except BoardDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/boards/{board_id}", response_model=BoardOut)
def update(board_id: str, body: BoardUpdate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return update_board(
            db, workspace_id=body.workspace_id, board_id=board_id, name=body.name, canvas=body.canvas
        )
    except BoardDomainError as exc:
        # 「画板不存在」是 404,「画布不合法」是 400 —— 两者对调用方意味着完全不同的下一步。
        status = 404 if "不存在" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.delete("/boards/{board_id}")
def remove(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    try:
        delete_board(db, workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
