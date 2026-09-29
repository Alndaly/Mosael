from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.worker_key import WORKER_KEY_HEADER, verify_worker_key
from app.api.deps.auth import get_current_user, presented_token
from app.domain.permissions import ensure_deployment_admin
from app.db.models import User

DbSession = Annotated[Session, Depends(session_scope)]


def transaction(db: DbSession) -> Iterator[Session]:
    """这次请求就是一次用例:端点正常返回就提交,抛异常(含 HTTPException)就回滚(见 core/unit_of_work)。

    用的是**同一个**请求会话(FastAPI 按请求缓存依赖),CurrentUser 查出来的那个人和这里是一个会话里的对象。

    **`scope="function"` 不能省。** FastAPI 默认在响应**发出之后**才执行 yield 依赖的收尾 —— 那样提交失败时
    用户已经收到了 200,背后什么都没落库。function 作用域在端点返回后、响应发出前收尾,提交失败就是这次
    请求的 500(tests/test_unit_of_work.py 钉着)。
    """
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


#: 写操作的路由用它代替 DbSession:路由里不再写 `db.commit()`,领域函数也不写。
Tx = Annotated[Session, Depends(transaction, scope="function")]
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
    sent = request.headers.get(WORKER_KEY_HEADER)
    if not verify_worker_key(sent):
        raise HTTPException(status_code=401, detail="Invalid or missing worker key")
