from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Response

from app.core import lifeline
from app.core.config import app_version, settings
from app.core.shell_origin import shell_token

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """活着,并且说得清自己是谁(见 core/lifeline):壳据此判断端口上那个后端能不能复用。"""
    return {
        "status": "ok",
        "app": "mosael",
        "version": app_version(),
        "instance": lifeline.INSTANCE_ID,
        "data_dir_id": lifeline.data_dir_id(settings.data_dir),
    }


@router.head("/health", status_code=204)
def health_head() -> Response:
    """Dev process managers such as wait-on probe HTTP URLs with HEAD."""
    return Response(status_code=204)


@router.post("/health/shutdown", status_code=202, include_in_schema=False)
def shutdown(x_mosael_shell: str = Header(default="")) -> Response:
    """桌面壳退出时请后端自己收尾、退出(见 electron/backend-lifecycle.cjs 的 shutdown)。

    Windows 上壳发不了 SIGTERM —— Node 的 kill 在那边就是强杀,lifespan 的收尾(停本机服务、调度线程)一步都不跑,
    后端起的子进程成了孤儿。只认壳令牌(主密钥派生,网页算不出来);不是桌面版、令牌不对一律当没有这个接口。"""
    if not settings.local_desktop or not hmac.compare_digest(x_mosael_shell, shell_token()):
        raise HTTPException(status_code=404)
    lifeline.shut_down_soon("the desktop shell asked this backend to shut down")
    return Response(status_code=202)
