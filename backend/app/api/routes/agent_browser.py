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
from app.db.models import Asset, BrowserSession
from app.domain import browser, host_files, sharing

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


def _upload_source(db, user, workspace_id: str, args: dict[str, Any]) -> host_files.HostFile:
    """上传动作要塞的那个文件:素材(本工作区素材库里的)或本机路径(经 domain/host_files 放行)。

    此前 args 原样交给执行器:`{"path": "~/.ssh/id_rsa"}` 就能把这台电脑上的私钥塞进任意网页。
    """
    asset_id = str(args.get("asset_id") or "").strip()
    if asset_id:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != workspace_id or not asset.file_key:
            raise HTTPException(status_code=404, detail=tr("routeErr_assetNotFound"))
        return host_files.asset_file(asset)
    try:
        return host_files.ensure_readable(db, str(args.get("path") or ""), actor=user.id)
    except host_files.HostFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agent-browser/act")
def act(body: ActRequest, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    _verify(db, user, body.workspace_id, body.session_id, perm="edit")
    try:
        if body.action == "upload":
            file = _upload_source(db, user, body.workspace_id, body.args)
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
def close(body: CloseRequest, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    _verify(db, user, body.workspace_id, body.session_id, perm="edit")
    browser.close_session(db, body.session_id)
    return {"ok": True}
