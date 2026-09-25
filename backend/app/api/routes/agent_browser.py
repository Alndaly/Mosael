"""智能体浏览器动作(内联,非确认卡):在**已确认打开**的隔离会话上跑单个动作。

入口 browser_open 走确认卡(用户看到目标网址再放行,见 domain/agent/confirmations);会话既开,
后续 navigate/click/type/read/wait/close 内联走这里——每次校验会话归属该工作区且用户有权访问。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import BrowserSession
from app.domain import browser, sharing

router = APIRouter(tags=["agent-browser"])


class ActRequest(BaseModel):
    workspace_id: str
    session_id: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)


class CloseRequest(BaseModel):
    workspace_id: str
    session_id: str


def _verify(db, user, workspace_id: str, session_id: str, *, perm: str | None = None) -> BrowserSession:
    if perm is None:
        ensure_workspace_access(db, user, workspace_id)
    else:
        ensure_workspace_perm(db, user, workspace_id, perm)
    # 池档案会话还要他自己能用那个档案 —— 拿到会话 id 不等于有权用别人已登录的浏览器
    # (见 domain/browser.attach_session)。
    try:
        session = browser.attach_session(db, session_id, workspace_id=workspace_id, actor=user.id)
    except sharing.NotUsableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_browserSessionNotFound"))
    return session


@router.post("/agent-browser/act")
def act(body: ActRequest, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    _verify(db, user, body.workspace_id, body.session_id, perm="edit")
    try:
        result = browser.run_action(body.session_id, body.action, body.args)
    except browser.BrowserDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"result": result}


@router.post("/agent-browser/close")
def close(body: CloseRequest, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    _verify(db, user, body.workspace_id, body.session_id, perm="edit")
    browser.close_session(db, body.session_id)
    return {"ok": True}
