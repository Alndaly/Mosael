"""智能体浏览器动作(内联,非确认卡):在**已确认打开**的隔离会话上跑单个动作。

入口 browser_open 走确认卡(用户看到目标网址再放行,见 domain/agent/confirmations);会话既开,
后续 navigate/click/type/read/wait/close 内联走这里——每次校验会话归属该工作区且用户有权访问。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, Tx
from app.domain import browser, host_files, sharing
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
    try:
        sessions.operable_session(db, user, body.workspace_id, body.session_id)
    except sharing.NotUsableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        if body.action == "upload":
            # 此前 args 原样交给执行器:`{"path": "~/.ssh/id_rsa"}` 就能把这台电脑上的私钥塞进任意网页。
            try:
                file = host_files.upload_source(
                    db,
                    workspace_id=body.workspace_id,
                    asset_id=str(body.args.get("asset_id") or ""),
                    path=str(body.args.get("path") or ""),
                    actor=user.id,
                )
            except host_files.HostFileError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            try:
                timeout_ms = int(float(body.args.get("timeout_ms") or 15_000))
            except (TypeError, ValueError):
                timeout_ms = 15_000
            result = browser.upload_file(
                body.session_id, file, selector=str(body.args.get("selector") or ""), timeout_ms=timeout_ms
            )
        else:
            result = browser.run_action(body.session_id, body.action, body.args)
    except browser.BrowserDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"result": result}


@router.post("/agent-browser/close")
def close(body: CloseRequest, db: Tx, user: CurrentUser) -> dict[str, Any]:
    try:
        sessions.close_session(db, user, body.workspace_id, body.session_id)
    except sharing.NotUsableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True}
