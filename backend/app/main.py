from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from app.api.routes.agent import router as agent_router
from app.api.routes.asr import router as asr_router
from app.api.routes.assets import router as assets_router
from app.api.routes.voices import router as voices_router
from app.api.routes.translate import router as translate_router
from app.api.routes.websearch import router as websearch_router
from app.api.routes.auth import router as auth_router
from app.api.routes.confirmations import router as confirmations_router
from app.api.routes.feishu import router as feishu_router
from app.api.routes.generation import router as generation_router
from app.api.routes.health import router as health_router
from app.api.routes.hooks import router as hooks_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.kb import router as kb_router
from app.api.routes.fonts import router as fonts_router
from app.api.routes.luts import router as luts_router
from app.api.routes.plugins import router as plugins_router
from app.api.routes.projects import router as projects_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.sequences import router as sequences_router
from app.api.routes.settings import router as settings_router
from app.api.routes.batches import router as batches_router
from app.api.routes.publish import router as publish_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.publish_worker import router as publish_worker_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.workspaces import router as workspaces_router
from app.core.config import settings
from app.api.deps import require_worker_key
from app.core.worker_key import issue_worker_key
from app.core.db import SessionLocal, init_db
from app.core.permissions import get_current_user
from app.domain.generation import ensure_builtin_generation_models
from app.domain.jobs import reconcile_orphaned_jobs
from app.media.proxy import reconcile_missing_proxies
from app.workers.scheduler import start_scheduler_loop, stop_scheduler_loop


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    # Mint the publish worker's shared secret before any request can arrive. See
    # app/core/worker_key.py for why that channel needs one.
    issue_worker_key()
    with SessionLocal() as db:
        ensure_builtin_generation_models(db)
        # A restart kills every in-process worker thread — fail the jobs they
        # were running so they don't linger frozen in the task center.
        reconcile_orphaned_jobs(db)
        # Backfill preview proxies for any videos missing one (best-effort).
        reconcile_missing_proxies(db)
    if settings.scheduler_enabled:
        start_scheduler_loop()
    if settings.feishu_autostart:
        from app.integrations.feishu.service import autostart_enabled_bots, stop_all_connections

        autostart_enabled_bots()
    yield
    stop_scheduler_loop()
    if settings.feishu_autostart:
        stop_all_connections()


class _MethodBindingMiddleware:
    """Pure-ASGI middleware: bind the request's HTTP method into a contextvar so the
    workspace access chokepoint can write-gate mutations. Pure ASGI (not
    BaseHTTPMiddleware) so the contextvar is set in the same context that FastAPI later
    copies into the threadpool for sync route handlers."""

    def __init__(self, app: object) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] == "http":
            from app.core.permissions import bind_request_method

            bind_request_method(scope.get("method", "GET"))
        await self.app(scope, receive, send)  # type: ignore[operator]


def create_app() -> FastAPI:
    app = FastAPI(title="Mibu New API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(_MethodBindingMiddleware)
    # Auth is bearer-token (no cookies) and the packaged Electron shell loads the frontend
    # from file://, whose fetches carry Origin: null — hence an explicit "null" here rather
    # than a same-origin policy.
    #
    # NOT "*": that reasoning ("authentication gates every request") holds only for the
    # authenticated routers below. The publish-worker channel is deliberately unauthenticated,
    # so with a wildcard any page the user happened to be browsing could call it AND READ THE
    # REPLY — which includes publish tasks across every workspace and account proxy strings
    # with credentials in them. Naming the origins we actually ship from means such a page
    # fails the CORS check and cannot read the response.
    #
    # This bounds disclosure, not side effects: a simple cross-origin POST still reaches the
    # handler even when the browser refuses to hand back the body. Authenticating the worker
    # channel is the actual fix and needs a change on the Electron side too.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "null",                    # Electron shell (file://)
            "http://localhost:5173",   # Vite dev server
            "http://127.0.0.1:5173",
            "http://localhost:8800",   # backend serving the built frontend
            "http://127.0.0.1:8800",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    # Webhook 触发按任务密钥鉴权,不挂登录依赖。
    app.include_router(hooks_router, prefix="/api")
    # 桌面发布器 worker:本机进程,不走用户会话,改用启动时下发的共享密钥(见 worker_key.py)。
    app.include_router(publish_worker_router, prefix="/api", dependencies=[Depends(require_worker_key)])
    protected = [Depends(get_current_user)]
    app.include_router(projects_router, prefix="/api", dependencies=protected)
    app.include_router(workspaces_router, prefix="/api", dependencies=protected)
    app.include_router(assets_router, prefix="/api", dependencies=protected)
    app.include_router(asr_router, prefix="/api", dependencies=protected)
    app.include_router(voices_router, prefix="/api", dependencies=protected)
    app.include_router(translate_router, prefix="/api", dependencies=protected)
    app.include_router(websearch_router, prefix="/api", dependencies=protected)
    app.include_router(luts_router, prefix="/api", dependencies=protected)
    app.include_router(fonts_router, prefix="/api", dependencies=protected)
    app.include_router(sequences_router, prefix="/api", dependencies=protected)
    app.include_router(jobs_router, prefix="/api", dependencies=protected)
    app.include_router(notifications_router, prefix="/api", dependencies=protected)
    app.include_router(kb_router, prefix="/api", dependencies=protected)
    app.include_router(generation_router, prefix="/api", dependencies=protected)
    app.include_router(scheduler_router, prefix="/api", dependencies=protected)
    app.include_router(workflows_router, prefix="/api", dependencies=protected)
    app.include_router(batches_router, prefix="/api", dependencies=protected)
    app.include_router(publish_router, prefix="/api", dependencies=protected)
    app.include_router(settings_router, prefix="/api", dependencies=protected)
    app.include_router(confirmations_router, prefix="/api", dependencies=protected)
    app.include_router(feishu_router, prefix="/api", dependencies=protected)
    app.include_router(plugins_router, prefix="/api", dependencies=protected)
    app.include_router(agent_router, prefix="/api", dependencies=protected)
    return app


app = create_app()
