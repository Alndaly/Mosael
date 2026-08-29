"""创意画板的路由。薄的一层:鉴权 + 把领域错误翻成 400,画布的规矩全在 domain/boards。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BoardCreate, BoardGenerate, BoardOut, BoardUpdate
from app.db.models import Board
from app.domain.boards import (
    BoardDomainError,
    create_board,
    delete_board,
    get_board,
    list_boards,
    place_pending,
    receipt_to_item,
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


@router.post("/boards/{board_id}/generate", response_model=BoardOut)
def generate(board_id: str, body: BoardGenerate, db: DbSession, user: CurrentUser) -> Board:
    """在画板上生成一份素材,产出就地落回画布。

    **不自己实现生成** —— 汇进 create_generation_job 那条漏斗(AI 工作台、定时任务、
    工作流节点、智能体走的是同一条),于是描述符校验、能力探测、计量记账、任务中心全都白拿。
    这里只多做一件画板自己的事:先摆一个「正在生成」的占位,并把回执指向它。
    """
    from app.domain import provider_models
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.runner import start_generation_thread

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        board = get_board(db, body.workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    provider, model = body.provider.strip(), body.model.strip()
    if not provider or not model:
        # 没点名就用这个人在这种能力上的默认 —— 和定时任务那条路同一个解析。
        default = provider_models.resolve_default(db, body.kind, user.id)
        if default is not None and default.profile is not None:
            provider, model = default.profile.vendor, default.model_id
    if not provider or not model:
        raise HTTPException(status_code=400, detail="还没有可用的生成模型,先去设置里配一个")

    try:
        generation, job = create_generation_job(
            db,
            workspace_id=body.workspace_id,
            session_id=None,
            project_id=None,
            created_by=user.id,
            provider=provider,
            model=model,
            kind=body.kind,
            prompt=body.prompt,
            negative_prompt="",
            parameters=dict(body.parameters or {}),
            source_assets=list(body.source_assets or []),
        )
    except GenerationDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 回执指向这一项:任务落终态时由 domain/boards.deliver_generated 把 asset_id 填回来。
    job.payload = {**(job.payload or {}), "receipt": receipt_to_item(board.id, body.item_id)}
    db.commit()

    try:
        board = place_pending(
            db,
            workspace_id=body.workspace_id,
            board_id=board.id,
            item={
                "id": body.item_id,
                "kind": body.kind,
                "x": body.x,
                "y": body.y,
                "job_id": job.id,
                "text": body.prompt[:120],
            },
        )
    except BoardDomainError as exc:
        # 画布放不下这一项是**请求的问题**,不是服务器崩了 —— 漏出去的话调用方收到 500
        # 和一整页 traceback,而真正的原因(比如坐标不合法)一个字都看不到。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    start_generation_thread(generation.id)
    return board
