"""创意画板的路由。薄的一层:认人 + 把领域错误翻成 HTTP。画布的规矩、画板上的动作全在 domain/boards。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession, Tx
from app.core.i18n import get_current_locale
from app.api.schemas import BoardCreate, BoardDuplicate, BoardNoteAppend, BoardNoteAppendOut, BoardOut, BoardProducerOut, BoardRun, BoardSequenceCreate, BoardSequenceOut, BoardSummaryOut, BoardUpdate
from app.db.models import Board
from app.domain.boards import BoardDomainError, BoardNotFound, BoardRevisionConflict, producers
from app.domain.boards import use_cases as boards

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


@router.get("/boards", response_model=list[BoardSummaryOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    """清单:每张板一份摘要(缩略图用的画布),不带整份画布 —— 打开一张板时由 `/boards/{board_id}` 给。"""
    return boards.list_all(db, user, workspace_id)


@router.get("/boards/producers", response_model=list[BoardProducerOut])
def list_producers(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    """画板上**这个人**能用的产出者:内置的,加上画板上能跑的节点 —— 内容格的能力、空格子上的生成器(插件工具只列他自己接的)。

    节点的描述和工作流节点面板是同一份(标签、分组、字段一个字都不差),按请求方的语言翻好。
    **注册在 `/boards/{board_id}` 之前** —— 反过来的话 `producers` 会被当成一张板的 id。
    """
    return boards.producers_for(db, user, workspace_id, get_current_locale())


@router.get("/boards/{board_id}", response_model=BoardOut)
def read(board_id: str, db: DbSession, user: CurrentUser, workspace_id: str | None = None) -> Board:
    """`workspace_id` **可选** —— 画板自带归属,和素材/工作流那两条详情路由一致(同 notes.read)。"""
    try:
        return boards.read(db, user, board_id, workspace_id)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc


@router.post("/boards", response_model=BoardOut)
def create(body: BoardCreate, db: Tx, user: CurrentUser) -> Board:
    try:
        return boards.create(db, user, body.workspace_id, name=body.name, canvas=body.canvas)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc


@router.post("/boards/{board_id}/sequences", response_model=BoardSequenceOut)
def create_sequence(board_id: str, body: BoardSequenceCreate, db: Tx, user: CurrentUser) -> dict:
    """放一格时间线格之前先建好它那条时间线(放进这张画板的项目,ADR 0030)。"""
    try:
        sequence = boards.create_timeline(db, user, body.workspace_id, board_id, copy_of=body.copy_of)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    return {"sequence_id": sequence.id, "name": sequence.name}


@router.post("/boards/{board_id}/notes", response_model=BoardNoteAppendOut)
def append_note(board_id: str, body: BoardNoteAppend, db: Tx, user: CurrentUser) -> dict:
    """往画板上追加一张便签,摆在空位上(笔记选区工具条的「加到画板」)。见 boards.use_cases.append_note。"""
    try:
        board, item_id = boards.append_note(
            db, user, body.workspace_id, board_id, text=body.text,
            source_note=body.source_note.model_dump() if body.source_note else None,
        )
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    return {"board_id": board.id, "item_id": item_id, "revision": board.revision}


@router.post("/boards/{board_id}/duplicate", response_model=BoardOut)
def duplicate(board_id: str, body: BoardDuplicate, db: Tx, user: CurrentUser) -> Board:
    try:
        return boards.duplicate(db, user, body.workspace_id, board_id, name=body.name)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc


@router.patch("/boards/{board_id}", response_model=BoardOut)
def update(board_id: str, body: BoardUpdate, db: Tx, user: CurrentUser) -> Board | JSONResponse:
    try:
        return boards.update(
            db,
            user,
            body.workspace_id,
            board_id,
            name=body.name,
            canvas=body.canvas,
            base_revision=body.base_revision,
        )
    except BoardDomainError as exc:
        #: 存不下是因为**某一格**(字太长、字段写错):回包里带上是哪一格,界面跳过去、圈出来 —— 报错那句话里的 id
        #: 是内部的,人认不出是哪张便签。`detail` 照旧是那句话。
        item_id = exc.params.get("item_id") if not isinstance(exc, BoardNotFound) else None
        if isinstance(item_id, str) and item_id:
            return JSONResponse(status_code=400, content={"detail": str(exc), "item_id": item_id})
        # 「画板不存在」是 404,「画布不合法」是 400 —— 两者对调用方意味着完全不同的下一步。
        raise _board_http_error(exc) from exc


@router.delete("/boards/{board_id}")
def remove(board_id: str, workspace_id: str, db: Tx, user: CurrentUser) -> dict[str, bool]:
    try:
        boards.delete(db, user, workspace_id, board_id)
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
    return {"ok": True}


@router.post("/boards/{board_id}/run", response_model=BoardOut)
def run(board_id: str, body: BoardRun, db: Tx, user: CurrentUser) -> Board:
    """在画板上跑一个产出者,产出落回那一格(见 boards.producers.run)。

    画板上一切产出(生成、写字、念出来、截一段、一格的能力跑一个节点)都走这一条 —— 此前是四条各自的
    路由和请求体。跑它要什么权限由产出者声明。插件工具用的是**点运行的这个人**自己的连接。
    """
    try:
        return boards.run(
            db,
            user,
            body.workspace_id,
            board_id,
            producer=body.producer,
            item_id=body.item_id,
            kind=body.kind,
            x=body.x,
            y=body.y,
            base_revision=body.base_revision,
            form=dict(body.form or {}),
        )
    except producers.ProducerFormInvalid as exc:
        # 表单是请求体的一部分,只是形状由产出者声明 —— 和请求体校验失败回同一种 422。
        raise RequestValidationError(
            [{**one, "loc": ("body", "form", *one.get("loc", ()))} for one in exc.errors]
        ) from exc
    except BoardDomainError as exc:
        raise _board_http_error(exc) from exc
