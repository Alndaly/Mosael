from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.worker_key import LEGACY_WORKER_KEY_HEADER, WORKER_KEY_HEADER, verify_worker_key
from app.core.permissions import ensure_deployment_admin, get_current_user, presented_token
from app.db.models import User

DbSession = Annotated[Session, Depends(session_scope)]
CurrentUser = Annotated[User, Depends(get_current_user)]
#: 这次请求带进来的凭据原文。只给需要把它继续传下去的路由用(工具通道的回连);
#: 认人一律走 CurrentUser。
PresentedToken = Annotated[str, Depends(presented_token)]


def require_worker_key(request: Request) -> None:
    """Gate for the local publish-worker channel.

    It carries no user session — the worker is an Electron process, not a person — so it
    authenticates with the per-process secret written to the data directory at startup. A web
    page cannot read that file, which is exactly what separates the worker from any other caller
    able to reach 127.0.0.1.
    """
    # 旧头名一并接受:升级后第一次启动可能是「新壳 + 复用的旧后端」,反之亦然。
    sent = request.headers.get(WORKER_KEY_HEADER) or request.headers.get(LEGACY_WORKER_KEY_HEADER)
    if not verify_worker_key(sent):
        raise HTTPException(status_code=401, detail="Invalid or missing worker key")
