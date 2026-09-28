from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    FeishuBindCodeOut,
    FeishuBindingOut,
    FeishuBotCreate,
    FeishuBotOut,
    FeishuBotUpdate,
    FeishuOnboardingOut,
)
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import FeishuBot
from app.domain.feishu import bindings, bots
from app.integrations.feishu import client, connections, onboarding

router = APIRouter(tags=["feishu"])


@router.get("/feishu/bots", response_model=list[FeishuBotOut])
def list_bots(workspace_id: str, db: DbSession, user: CurrentUser) -> list[FeishuBot]:
    ensure_workspace_access(db, user, workspace_id)
    return bots.list_bots(db, workspace_id)


@router.post("/feishu/bots", response_model=FeishuBotOut)
def create_bot(body: FeishuBotCreate, db: DbSession, user: CurrentUser) -> FeishuBot:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    bot = bots.create_bot(db, **body.model_dump())
    db.commit()
    connections.start_or_report(bot.id)
    db.refresh(bot)
    return bot


@router.patch("/feishu/bots/{bot_id}", response_model=FeishuBotOut)
def update_bot(bot_id: str, body: FeishuBotUpdate, db: DbSession, user: CurrentUser) -> FeishuBot:
    bot = _require_bot(db, user, bot_id, perm="edit")
    changes = body.model_dump(exclude_unset=True)
    bots.update_bot(db, bot, changes)
    db.commit()
    if "enabled" in changes:
        if bot.enabled:
            connections.start_connection(bot.id)
        else:
            connections.stop_connection(bot.id)
    db.refresh(bot)
    return bot


@router.delete("/feishu/bots/{bot_id}", status_code=204)
def delete_bot(bot_id: str, db: DbSession, user: CurrentUser) -> Response:
    bot = _require_bot(db, user, bot_id, perm="edit")
    connections.stop_connection(bot.id)
    bots.delete_bot(db, bot)
    db.commit()
    return Response(status_code=204)


@router.post("/feishu/bots/{bot_id}/restart", response_model=FeishuBotOut)
def restart_bot(bot_id: str, db: DbSession, user: CurrentUser) -> FeishuBot:
    bot = _require_bot(db, user, bot_id, perm="edit")
    connections.restart_connection(bot.id)
    db.refresh(bot)
    return bot


@router.post("/feishu/onboarding/{workspace_id}", response_model=FeishuOnboardingOut)
def begin_onboarding(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    try:
        return onboarding.begin_onboarding(workspace_id)
    except client.FeishuError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/feishu/onboarding/{workspace_id}", response_model=FeishuOnboardingOut)
def onboarding_status(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return onboarding.onboarding_status(workspace_id)


def _require_bot(db: DbSession, user: CurrentUser, bot_id: str, *, perm: str | None = None) -> FeishuBot:
    bot = db.get(FeishuBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Not found")
    if perm is None:
        ensure_workspace_access(db, user, bot.workspace_id)
    else:
        ensure_workspace_perm(db, user, bot.workspace_id, perm)
    return bot


@router.post("/feishu/bots/{bot_id}/bind-code", response_model=FeishuBindCodeOut)
def issue_bind_code(bot_id: str, db: DbSession, user: CurrentUser) -> FeishuBindCodeOut:
    """Any member issues a one-time code, then sends it to the bot from Feishu to bind their
    own Feishu account. The bot then acts with THIS member's permissions."""
    bot = _require_bot(db, user, bot_id, perm="edit")
    code, expires = bindings.issue_bind_code(db, bot.workspace_id, user.id)
    return FeishuBindCodeOut(code=code, expires_at=expires)


@router.get("/feishu/bots/{bot_id}/bindings", response_model=list[FeishuBindingOut])
def list_bindings(bot_id: str, db: DbSession, user: CurrentUser) -> list[FeishuBindingOut]:
    bot = _require_bot(db, user, bot_id)
    return [
        FeishuBindingOut(open_id=open_id, user_id=member.id, username=member.username)
        for open_id, member in bindings.list_bindings(db, bot.workspace_id)
    ]


@router.delete("/feishu/bots/{bot_id}/bindings/{open_id}", status_code=204)
def remove_binding(bot_id: str, open_id: str, db: DbSession, user: CurrentUser) -> Response:
    bot = db.get(FeishuBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_perm(db, user, bot.workspace_id, "members")  # managing who can drive the bot = member mgmt
    bindings.remove_binding(db, bot.workspace_id, open_id)
    return Response(status_code=204)
