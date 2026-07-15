from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import FeishuBotCreate, FeishuBotOut, FeishuBotUpdate, FeishuOnboardingOut
from app.core.permissions import ensure_workspace_access
from app.db.models import FeishuBot
from app.integrations.feishu import service

router = APIRouter(tags=["feishu"])


@router.get("/feishu/bots", response_model=list[FeishuBotOut])
def list_bots(workspace_id: str, db: DbSession, user: CurrentUser) -> list[FeishuBot]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(FeishuBot).where(FeishuBot.workspace_id == workspace_id).order_by(FeishuBot.created_at)
    return list(db.scalars(stmt))


@router.post("/feishu/bots", response_model=FeishuBotOut)
def create_bot(body: FeishuBotCreate, db: DbSession, user: CurrentUser) -> FeishuBot:
    ensure_workspace_access(db, user, body.workspace_id)
    bot = FeishuBot(**body.model_dump())
    db.add(bot)
    db.commit()
    db.refresh(bot)
    try:
        service.start_connection(bot.id)
    except Exception:
        service.write_status(bot.id, "error", "启动长连接失败")
    db.refresh(bot)
    return bot


@router.patch("/feishu/bots/{bot_id}", response_model=FeishuBotOut)
def update_bot(bot_id: str, body: FeishuBotUpdate, db: DbSession, user: CurrentUser) -> FeishuBot:
    bot = _require_bot(db, user, bot_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is not None:
            setattr(bot, key, value)
    db.commit()
    if "enabled" in changes:
        if bot.enabled:
            service.start_connection(bot.id)
        else:
            service.stop_connection(bot.id)
    db.refresh(bot)
    return bot


@router.delete("/feishu/bots/{bot_id}", status_code=204)
def delete_bot(bot_id: str, db: DbSession, user: CurrentUser) -> Response:
    bot = _require_bot(db, user, bot_id)
    service.stop_connection(bot.id)
    db.delete(bot)
    db.commit()
    return Response(status_code=204)


@router.post("/feishu/bots/{bot_id}/restart", response_model=FeishuBotOut)
def restart_bot(bot_id: str, db: DbSession, user: CurrentUser) -> FeishuBot:
    bot = _require_bot(db, user, bot_id)
    service.stop_connection(bot.id)
    service.start_connection(bot.id)
    db.refresh(bot)
    return bot


@router.post("/feishu/onboarding/{workspace_id}", response_model=FeishuOnboardingOut)
def begin_onboarding(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    try:
        return service.begin_onboarding(workspace_id)
    except service.FeishuError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/feishu/onboarding/{workspace_id}", response_model=FeishuOnboardingOut)
def onboarding_status(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return service.onboarding_status(workspace_id)


def _require_bot(db: DbSession, user: CurrentUser, bot_id: str) -> FeishuBot:
    bot = db.get(FeishuBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, bot.workspace_id)
    return bot
