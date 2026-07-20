from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.worker_key import WORKER_KEY_HEADER, verify_worker_key
from app.core.permissions import get_current_user
from app.db.models import User

DbSession = Annotated[Session, Depends(session_scope)]
CurrentUser = Annotated[User, Depends(get_current_user)]



def require_worker_key(request: Request) -> None:
    """Gate for the local publish-worker channel.

    It carries no user session — the worker is an Electron process, not a person — so it
    authenticates with the per-process secret written to the data directory at startup. A web
    page cannot read that file, which is exactly what separates the worker from any other caller
    able to reach 127.0.0.1.
    """
    if not verify_worker_key(request.headers.get(WORKER_KEY_HEADER)):
        raise HTTPException(status_code=401, detail="Invalid or missing worker key")
