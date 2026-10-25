from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    FeishuBindCodeOut,
    FeishuBindingOut,
    FeishuBotCreate,
    FeishuBotOut,
    FeishuBotUpdate,
    FeishuOnboardingOut,
)
from app.core.unit_of_work import after_commit
from app.db.models import FeishuBot
from app.domain.feishu import use_cases as feishu
from app.integrations.feishu import client, connections, onboarding

router = APIRouter(tags=["feishu"])


@router.get("/feishu/bots", response_model=list[FeishuBotOut])
def list_bots(workspace_id: str, db: DbSession, user: CurrentUser) -> list[FeishuBot]:
    return feishu.list_bots(db, user, workspace_id)


@router.post("/feishu/bots", response_model=FeishuBotOut)
def create_bot(body: FeishuBotCreate, db: Tx, user: CurrentUser) -> FeishuBot:
    fields = body.model_dump()
    bot = feishu.create_bot(db, user, fields.pop("workspace_id"), **fields)
    # 长连接在提交之后才起:子进程读的是库里的那一行。
    bot_id = bot.id
    after_commit(db, lambda: connections.start_or_report(bot_id))
    return bot


@router.patch("/feishu/bots/{bot_id}", response_model=FeishuBotOut)
def update_bot(bot_id: str, body: FeishuBotUpdate, db: Tx, user: CurrentUser) -> FeishuBot:
    changes = body.model_dump(exclude_unset=True)
    credential_changed = bool({"app_id", "app_secret"} & set(changes))
    bot = feishu.update_bot(db, user, bot_id, changes)
    if credential_changed:
        # 旧 token 是旧 app 的;不失效的话,最长两小时内所有出站 REST 仍会拿它去发。
        after_commit(db, lambda: client.invalidate_token(bot_id))
    if credential_changed or "enabled" in changes:
        # 凭据变了要重启;开关变了要起/停。两件事同时写时,以“当前 enabled 状态”为准:
        # 禁用就停,启用就重启,不出现“先停再被起”或“只停了但凭据没换”的分叉。
        def sync_connection() -> None:
            if bot.enabled:
                connections.restart_connection(bot_id)
            else:
                connections.stop_connection(bot_id)

        after_commit(db, sync_connection)
    return bot


@router.delete("/feishu/bots/{bot_id}", status_code=204)
def delete_bot(bot_id: str, db: Tx, user: CurrentUser) -> Response:
    feishu.editable_bot(db, user, bot_id)
    connections.stop_connection(bot_id)
    client.invalidate_token(bot_id)
    feishu.delete_bot(db, user, bot_id)
    return Response(status_code=204)


@router.post("/feishu/bots/{bot_id}/restart", response_model=FeishuBotOut)
def restart_bot(bot_id: str, db: DbSession, user: CurrentUser) -> FeishuBot:
    bot = feishu.editable_bot(db, user, bot_id)
    connections.restart_connection(bot.id)
    db.refresh(bot)
    return bot


@router.post("/feishu/onboarding/{workspace_id}", response_model=FeishuOnboardingOut)
def begin_onboarding(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    #: **发起人是谁要带下去**:建完机器人,第一条绑定绑的就是他/她(见 integrations/feishu/onboarding)。
    #: 这里写注释而不是 docstring —— docstring 会进 OpenAPI 的接口描述,那就是一次要跟前端一起
    #: 重新生成的漂移(见 export_openapi.py --check)。
    feishu.ensure_can_edit(db, user, workspace_id)
    try:
        return onboarding.begin_onboarding(workspace_id, user.id)
    except client.FeishuError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/feishu/onboarding/{workspace_id}", response_model=FeishuOnboardingOut)
def onboarding_status(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    feishu.ensure_can_browse(db, user, workspace_id)
    return onboarding.onboarding_status(workspace_id)


@router.post("/feishu/bots/{bot_id}/bind-code", response_model=FeishuBindCodeOut)
def issue_bind_code(bot_id: str, db: Tx, user: CurrentUser) -> FeishuBindCodeOut:
    """Any member issues a one-time code, then sends it to the bot from Feishu to bind their
    own Feishu account. The bot then acts with THIS member's permissions."""
    code, expires = feishu.issue_bind_code(db, user, bot_id)
    return FeishuBindCodeOut(code=code, expires_at=expires)


@router.get("/feishu/bots/{bot_id}/bindings", response_model=list[FeishuBindingOut])
def list_bindings(bot_id: str, db: DbSession, user: CurrentUser) -> list[FeishuBindingOut]:
    """**这台机器人**的绑定。

    「哪台机器人」是那张表的键的一部分(open_id 按飞书应用隔离),所以列出来的天然只有本机的
    那些 —— 谁的面板显示谁的东西,不靠出口再筛一遍。
    """
    return [
        FeishuBindingOut(
            open_id=one.open_id,
            user_id=one.user.id,
            username=one.user.username,
            bot_id=one.bot_id,
        )
        for one in feishu.list_bindings(db, user, bot_id)
    ]


@router.delete("/feishu/bots/{bot_id}/bindings/{open_id}", status_code=204)
def remove_binding(bot_id: str, open_id: str, db: Tx, user: CurrentUser) -> Response:
    """**只删这台机器人的那一行**(别的机器人名下同一个人那一行不动)。"""
    feishu.remove_binding(db, user, bot_id, open_id)
    return Response(status_code=204)
