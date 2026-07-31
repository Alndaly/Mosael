from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from app.api.routes.agent import router as agent_router
from app.api.routes.agent_credentials import router as agent_credentials_router
from app.api.routes.agent_tools import router as agent_tools_router
from app.api.routes.agent_browser import router as agent_browser_router
from app.api.routes.browser_profiles import router as browser_profiles_router
from app.api.routes.asr import router as asr_router
from app.api.routes.assets import router as assets_router
from app.api.routes.voices import router as voices_router
from app.api.routes.translate import router as translate_router
from app.api.routes.websearch import router as websearch_router
from app.api.routes.auth import router as auth_router
from app.api.routes.oauth import router as oauth_router
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
from app.api.routes.publish import router as publish_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.job_worker import router as job_worker_router
from app.api.routes.browser_worker import router as browser_worker_router
from app.api.routes.publish_worker import router as publish_worker_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.workspaces import router as workspaces_router
from app.core.config import settings
from app.api.deps import require_worker_key
from app.core.logging import configure_logging
from app.core.worker_key import issue_worker_key
from app.core.db import SessionLocal, init_db

logger = logging.getLogger(__name__)
from app.core.permissions import get_current_user
from app.domain.assets import reconcile_broken_media_info
from app.domain.generation import ensure_builtin_generation_models
from app.ai.agent.host import reconcile_orphaned_agent_sessions
from app.domain.browser import reconcile_browser_state
from app.domain.jobs import reconcile_orphaned_jobs, register_external_kind
from app.media.proxy import reconcile_missing_proxies
from app.workers.scheduler import start_scheduler_loop, stop_scheduler_loop


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()  # 先配好日志,后续启动步骤才追溯得到
    logger.info("Open Studio backend starting (host=%s port=%s)", settings.backend_host, settings.backend_port)
    init_db()
    _prepare_network()
    # Mint the publish worker's shared secret before any request can arrive. See
    # app/core/worker_key.py for why that channel needs one.
    issue_worker_key()
    # 配置指定的 kind 翻成 external 执行模式(外部 worker 经 claim/report 驱动)。
    # 必须在 reconcile 之前——external kind 的任务跨重启存活,不能被判失败。
    external = [k.strip() for k in settings.external_job_kinds.split(",") if k.strip()]
    for kind in external:
        register_external_kind(kind)
    if external:
        logger.info("external job kinds (driven by outside worker): %s", ", ".join(external))
    with SessionLocal() as db:
        ensure_builtin_generation_models(db)
        # A restart kills every in-process worker thread — fail the jobs they
        # were running so they don't linger frozen in the task center.
        failed = reconcile_orphaned_jobs(db)
        # 同理:卡在 running 的智能体会话拨回 idle,否则前端永远「思考中」。
        reconcile_orphaned_agent_sessions(db)
        # 浏览器自动化:执行器视图随旧进程消失,残留动作/会话回收(见 domain/browser)。
        reconcile_browser_state()
        # Backfill preview proxies for any videos missing one (best-effort).
        reconcile_missing_proxies(db)
        # 修复 remux 上线前导入的坏素材(直录 webm 缺时长/缩略图/波形)。
        reconcile_broken_media_info(db)
    if failed:
        logger.info("reconciled %d orphaned job(s) left running by a previous restart", failed)
    if settings.scheduler_enabled:
        start_scheduler_loop()
        logger.info("scheduler loop started")
    if settings.feishu_autostart:
        from app.integrations.feishu.service import autostart_enabled_bots, stop_all_connections

        autostart_enabled_bots()
    logger.info("Open Studio backend ready")
    yield
    logger.info("Open Studio backend shutting down")
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


def _prepare_network() -> None:
    """把库里的出站代理设置装进本进程的环境变量,后端自己的 httpx 调用随即生效。

    放在这里而不是 init_db:`core.db` 去 import 领域层会形成
    core.db ⇄ db.models ⇄ domain.network 的环(分层测试会拦)。启动装配本来就是组装根的事。

    顺带给 v0.5.0 已经建过的空行补上默认绕过列表 —— 列默认值只对新建行生效,而那批行是
    在有默认值之前建的。只在用户还没配过代理时补,填过就不动他的。
    """
    from app.db.models import NetworkConfig
    from app.domain.network import DEFAULT_BYPASS_HOSTS, apply_from_db

    with SessionLocal() as db:
        row = db.get(NetworkConfig, "default")
        if row is not None and not row.no_proxy and not row.proxy_url:
            row.no_proxy = ",".join(DEFAULT_BYPASS_HOSTS)
            db.commit()
        apply_from_db(db)


def create_app() -> FastAPI:
    app = FastAPI(title="Open Studio API", version="0.1.0", lifespan=lifespan)
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
    # OAuth 登录必须免鉴权:它本身就是登录入口(回调来自系统浏览器,不带会话)。
    app.include_router(oauth_router, prefix="/api")
    # Webhook 触发按任务密钥鉴权,不挂登录依赖。
    app.include_router(hooks_router, prefix="/api")
    # 桌面发布器 worker:本机进程,不走用户会话,改用启动时下发的共享密钥(见 worker_key.py)。
    app.include_router(publish_worker_router, prefix="/api", dependencies=[Depends(require_worker_key)])
    # 通用 job worker 通道(claim/report/heartbeat):同一把 worker key,任意 external kind。
    app.include_router(job_worker_router, prefix="/api", dependencies=[Depends(require_worker_key)])
    app.include_router(browser_worker_router, prefix="/api", dependencies=[Depends(require_worker_key)])
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
    app.include_router(publish_router, prefix="/api", dependencies=protected)
    app.include_router(settings_router, prefix="/api", dependencies=protected)
    app.include_router(confirmations_router, prefix="/api", dependencies=protected)
    app.include_router(feishu_router, prefix="/api", dependencies=protected)
    app.include_router(plugins_router, prefix="/api", dependencies=protected)
    app.include_router(agent_router, prefix="/api", dependencies=protected)
    app.include_router(agent_tools_router, prefix="/api", dependencies=protected)
    app.include_router(agent_credentials_router, prefix="/api", dependencies=protected)
    app.include_router(agent_browser_router, prefix="/api", dependencies=protected)
    app.include_router(browser_profiles_router, prefix="/api", dependencies=protected)
    return app


app = create_app()
