"""智能体浏览器动作(内联,非确认卡):在**已确认打开**的隔离会话上跑单个动作。

入口 browser_open 走确认卡(用户看到目标网址再放行,见 domain/agent/confirmations);会话既开,
后续 navigate/click/type/read/wait/close 内联走这里。闸在 domain/browser/use_cases.act,拒绝由
api/domain_errors 统一翻成状态码。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, Tx
from app.domain.browser import use_cases as sessions

router = APIRouter(tags=["agent-browser"])


class ActRequest(BaseModel):
    workspace_id: str
    session_id: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)


class CloseRequest(BaseModel):
    workspace_id: str
    session_id: str


@router.post("/agent-browser/act")
def act(body: ActRequest, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    return {"result": sessions.act(db, user, body.workspace_id, body.session_id, body.action, body.args)}


@router.post("/agent-browser/close")
def close(body: CloseRequest, db: Tx, user: CurrentUser) -> dict[str, Any]:
    sessions.close_session(db, user, body.workspace_id, body.session_id)
    return {"ok": True}
