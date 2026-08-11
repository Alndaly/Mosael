"""智能体浏览器动作(内联,非确认卡):在**已确认打开**的隔离会话上跑单个动作。

入口 browser_open 走确认卡(用户看到目标网址再放行,见 domain/agent/confirmations);会话既开,
后续 navigate/click/type/read/wait/close 内联走这里——每次校验会话归属该工作区且用户有权访问。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import BrowserSession
from app.domain import browser

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
    session = db.get(BrowserSession, session_id)
    if session is None or session.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    if perm is None:
        ensure_workspace_access(db, user, session.workspace_id)
    else:
        ensure_workspace_perm(db, user, session.workspace_id, perm)
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
