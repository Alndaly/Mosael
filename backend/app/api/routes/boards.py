"""创意画板的路由。薄的一层:认人 + 把领域错误翻成 HTTP。画布的规矩、画板上的动作全在 domain/boards。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BoardCreate, BoardDuplicate, BoardGenerate, BoardOut, BoardSpeak, BoardTrim, BoardUpdate, BoardWrite
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
from app.domain.boards.actions import Slot, generate_on_board, speak_on_board, trim_on_board, write_on_board
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


@router.post("/boards/{board_id}/generate", response_model=BoardOut)
def generate(board_id: str, body: BoardGenerate, db: DbSession, user: CurrentUser) -> Board:
    """在画板上生成一份素材,产出就地落回画布(见 boards.actions.generate_on_board)。"""
    from app.domain.generation.operations import GenerationDomainError

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return generate_on_board(
            db,
            workspace_id=body.workspace_id,
            slot=Slot(board_id, body.item_id, body.x, body.y, body.base_revision),
            actor_id=user.id,
            kind=body.kind,
            prompt=body.prompt,
            provider=body.provider,
            provider_profile_id=body.provider_profile_id,
            model=body.model,
            parameters=dict(body.parameters or {}),
            source_assets=[one.model_dump() for one in (body.source_assets or [])],
            form=dict(body.form or {}),
        )
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    except GenerationDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/boards/{board_id}/write", response_model=BoardOut)
def write(board_id: str, body: BoardWrite, db: DbSession, user: CurrentUser) -> Board:
    """让 AI 往画板上的一张便签里写字(见 boards.actions.write_on_board)。"""
    from app.domain.ai_chat import AiChatError

    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    try:
        return write_on_board(
            db,
            workspace_id=body.workspace_id,
            board_id=board_id,
            item_id=body.item_id,
            actor_id=user.id,
            prompt=body.prompt,
            provider_profile_id=body.provider_profile_id,
            model=body.model,
            source_asset_ids=list(body.source_assets),
            context=list(body.context),
            base_revision=body.base_revision,
        )
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    except AiChatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/boards/{board_id}/speak", response_model=BoardOut)
def speak(board_id: str, body: BoardSpeak, db: DbSession, user: CurrentUser) -> Board:
    """把一段文字念成音频,产出落回画板上那一格(见 boards.actions.speak_on_board)。"""
    from app.domain.voices.engine_catalog import CLONE_ENGINE, synthesis_params
    from app.domain.voices.voices import VoiceError

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    engine = body.engine.strip() or CLONE_ENGINE
    try:
        # 引擎音色和克隆音色两条都要能走(此前只传 voice_id,画板配音只认克隆音色)。
        synthesis = synthesis_params(
            db,
            engine=engine,
            voice=(body.voice_id or "") if engine == CLONE_ENGINE else body.engine_voice,
            speed=body.speed,
            user_id=user.id,
            workspace_id=body.workspace_id,
            engine_voice_resource=body.engine_voice_resource,
        )
        return speak_on_board(
            db,
            workspace_id=body.workspace_id,
            slot=Slot(board_id, body.item_id, body.x, body.y, body.base_revision),
            actor_id=user.id,
            text=body.text,
            synthesis=synthesis,
            voice_id=body.voice_id,
        )
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    except VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/boards/{board_id}/trim", response_model=BoardOut)
def trim(board_id: str, body: BoardTrim, db: DbSession, user: CurrentUser) -> Board:
    """截出一段,产出落回画板上那一格(见 boards.actions.trim_on_board)。"""
    from app.domain.boards.trim import TrimError

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return trim_on_board(
            db,
            workspace_id=body.workspace_id,
            slot=Slot(board_id, body.item_id, body.x, body.y, body.base_revision),
            actor_id=user.id,
            asset_id=body.asset_id,
            start=body.start,
            end=body.end,
            mute=body.mute,
        )
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    except TrimError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
