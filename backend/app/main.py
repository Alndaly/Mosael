from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fastapi import Depends

from app.api.routes.agent import router as agent_router
from app.api.routes.session_groups import router as session_groups_router
from app.api.routes.agent_credentials import router as agent_credentials_router
from app.api.routes.agent_tools import router as agent_tools_router
from app.api.routes.agent_browser import router as agent_browser_router
from app.api.routes.browser_profiles import router as browser_profiles_router
from app.api.routes.asr import router as asr_router
from app.api.routes.assets import router as assets_router
from app.api.routes.voices import router as voices_router
from app.api.routes.translate import router as translate_router
from app.api.routes.websearch import router as websearch_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.oauth import router as oauth_router
from app.api.routes.confirmations import router as confirmations_router
from app.api.routes.feishu import router as feishu_router
from app.api.routes.generation import router as generation_router
from app.api.routes.health import router as health_router
from app.api.routes.hooks import router as hooks_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.fonts import router as fonts_router
from app.api.routes.luts import router as luts_router
from app.api.routes.plugins import router as plugins_router
from app.api.routes.projects import router as projects_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.sequences import router as sequences_router
from app.api.routes.settings import router as settings_router
from app.api.routes.shares import router as shares_router
from app.api.routes.publish import router as publish_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.job_worker import router as job_worker_router
from app.api.routes.browser_worker import router as browser_worker_router
from app.api.routes.publish_worker import router as publish_worker_router
from app.api.routes.boards import router as boards_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.workspaces import router as workspaces_router
from app.core.config import settings
from app.core.i18n import normalize_locale, set_current_locale
from app.api.deps import require_worker_key
from app.core.logging import configure_logging
from app.core.worker_key import issue_worker_key
from app.core.db import SessionLocal
from app.db.migrations import init_db

logger = logging.getLogger(__name__)
from app.api.deps.auth import get_current_user
from app.domain.permissions import NotVisible, PermissionDenied
from app.domain.assets import reconcile_broken_media_info
from app.domain.agent.host import reconcile_orphaned_agent_sessions
from app.domain.browser import reconcile_browser_state
from app.domain.jobs import reconcile_orphaned_jobs, register_external_kind
from app.domain.assets.proxies import reconcile_missing_proxies
from app.workers.scheduler import start_scheduler_loop, stop_scheduler_loop


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()  # 先配好日志,后续启动步骤才追溯得到
    logger.info("Open Studio backend starting (host=%s port=%s)", settings.backend_host, settings.backend_port)
    init_db()
    # 「配置从数据库读」「代理怎么算」这两道缝装在 _wire_seams(导入期),不在这里 —— 见那里的注释。
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
        from app.integrations.feishu.service import autostart_enabled_bots, notify_interrupted_chats, stop_all_connections

        # 被重启打断的飞书会话:把中断说明发回原聊天。只写进库的话,在飞书里发消息的那个人
        # 只看到一片沉默 —— 和"还在处理中"分辨不出来,于是一直等。
        with SessionLocal() as db:
            notified = notify_interrupted_chats(db)
        if notified:
            logger.info("notified %d feishu chat(s) about a turn interrupted by restart", notified)

        autostart_enabled_bots()
    logger.info("Open Studio backend ready")
    yield
    logger.info("Open Studio backend shutting down")
    stop_scheduler_loop()
    if settings.feishu_autostart:
        stop_all_connections()


def _prepare_network() -> None:
    """把库里的出站代理设置装进本进程的环境变量,后端自己的 httpx 调用随即生效。

    放在这里而不是 init_db:**这不是迁移,是启动装配** —— 它把库里已有的设置装进本进程的
    环境,每次启动都要做一遍,而迁移是"把老数据改成新形状",跑过就不该再跑。组装根本来就是
    干这个的。(早先的理由写的是"core.db 不能 import 领域层"——迁移搬去 app/db/migrations
    之后那条已经不成立了,但结论不变。)

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
        # 重试次数同理:进程级状态,启动时从库里装配一次。
        from app.db.models import AiRuntimeConfig
        from app.core.http_retry import set_max_retries

        runtime = db.get(AiRuntimeConfig, "default")
        if runtime is not None:
            set_max_retries(runtime.max_retries)


def _install_permission_handlers(app: FastAPI) -> None:
    """把授权层的领域异常翻成 HTTP 状态码。

    授权规则住在 `domain/permissions`(它必须能被飞书回调这类非 HTTP 入口调用,所以不能抛
    HTTPException)。翻译收在这一处,**29 个调用点一行都不用改** —— 它们照旧只写
    `ensure_workspace_perm(...)`。

    两个状态码都是**故意**的:不是成员给 404 而不是 403,因为 403 等于告诉他"这个 id 存在"。
    """

    @app.exception_handler(NotVisible)
    async def _not_visible(_request: Request, exc: NotVisible) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc) or "Not found"})

    @app.exception_handler(PermissionDenied)
    async def _denied(_request: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})


def _wire_seams() -> None:
    """把各条接缝的实现登记进去。**这是组装根**,也是唯一知道"谁实现谁"的地方。

    在导入期做而不是在 lifespan 里:「谁实现这道缝」是一件静态的组装事实,不是运行时状态。
    放在 lifespan 里的话,任何不跑 lifespan 的入口(TestClient、脚本、worker)拿到的就是
    一个半装配的系统 —— 而症状是运行到某一行才抛"没有装配",离原因很远。

    这些 install 只写注册表,不碰 IO,导入期做是安全的。
    """
    # 任务干完之后把回执送回发起它的那次对话。方向是反的:任务域不认识智能体,
    # 是智能体在这里把自己登记进去(见 domain/agent/receipts)。
    from app.domain.agent import receipts as agent_receipts
    # 插件与素材库之间那道缝同理 —— 两边各自都不认识对方(见 plugins/media_bridge)。
    from app.domain.assets import plugin_bridge as asset_plugin_bridge
    # 画板上生成的产出要落回画布 —— 同样是「任务不认识画板,画板认识任务」。
    from app.domain import boards as board_receipts
    # 「TTS 配置从哪儿读」:ai/runtime 是基础设施,不认识数据库,默认只读环境变量,
    # 真正那份由这里喂进去(见 ai/runtime/config.use_source)。
    #
    # 这一条曾经装在 lifespan 里,于是它正是上面那段话说的那个坑:不跑 lifespan 的入口
    # (TestClient、脚本)拿到的是**环境变量那份默认值**,而用户存进库的引擎/下载源/fish
    # 目录被无声顶掉 —— 表现是设置页 PUT 成功、回读还是旧的 f5-tts,一句错都不报。
    # 装的只是一个 callable(load 到真正 get() 时才碰库),所以不需要等 init_db。
    from app.ai.runtime import config as tts_runtime_config
    from app.domain.voices import tts_settings
    # 同一条道理:sidecar 是基础设施,不认识"网络配置存在哪张表"。
    from app.ai.sidecar import adapters as sidecar_adapters
    from app.domain.network import subprocess_env_for_child

    agent_receipts.install()
    asset_plugin_bridge.install()
    board_receipts.install()
    tts_runtime_config.use_source(tts_settings.load)
    sidecar_adapters.use_proxy_source(subprocess_env_for_child)


_wire_seams()


def create_app() -> FastAPI:
    app = FastAPI(title="Open Studio API", version="0.1.0", lifespan=lifespan)
    _install_permission_handlers(app)
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
    @app.middleware("http")
    async def _carry_locale(request, call_next):  # type: ignore[no-untyped-def]
        """把这次请求的语言放进 ContextVar,序列化那一层照它翻(见 core/i18n)。

        **放在中间件而不是各路由里**:任务消息由十几个接口返回,每处各取一次请求头就是同一个问题
        十几个答案 —— 漏一个,那一屏的任务就还是另一种语言。
        """
        set_current_locale(normalize_locale(request.headers.get("accept-language")))
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "null",                    # Electron shell (file://)
            "http://localhost:5173",   # Vite dev server
            "http://127.0.0.1:5173",
            # 第二套开发实例(.claude/launch.json 的 frontend-demo + backend-demo):同一份代码另起
            # 一对前后端,用来在不碰你正在用的那套数据的前提下看界面。少了这两条它只能拿到 CORS 错误。
            "http://localhost:5273",
            "http://127.0.0.1:5273",
            "http://localhost:8800",   # backend serving the built frontend
            "http://127.0.0.1:8800",
        ],
        # Chrome MV3 side panels have their own opaque extension origin. Keep this deliberately
        # narrower than ``chrome-extension://.*``: a real extension id is exactly 32 chars from
        # a-p. CORS only permits the browser to read a response; every useful route still requires
        # the user's bearer session and workspace authorization.
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
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
    app.include_router(generation_router, prefix="/api", dependencies=protected)
    app.include_router(scheduler_router, prefix="/api", dependencies=protected)
    app.include_router(workflows_router, prefix="/api", dependencies=protected)
    app.include_router(boards_router, prefix="/api", dependencies=protected)
    app.include_router(publish_router, prefix="/api", dependencies=protected)
    app.include_router(settings_router, prefix="/api", dependencies=protected)
    app.include_router(shares_router, prefix="/api", dependencies=protected)
    app.include_router(admin_router, prefix="/api", dependencies=protected)
    app.include_router(confirmations_router, prefix="/api", dependencies=protected)
    app.include_router(feishu_router, prefix="/api", dependencies=protected)
    app.include_router(plugins_router, prefix="/api", dependencies=protected)
    app.include_router(agent_router, prefix="/api", dependencies=protected)
    app.include_router(session_groups_router, prefix="/api", dependencies=protected)
    app.include_router(agent_tools_router, prefix="/api", dependencies=protected)
    app.include_router(agent_credentials_router, prefix="/api", dependencies=protected)
    app.include_router(agent_browser_router, prefix="/api", dependencies=protected)
    app.include_router(browser_profiles_router, prefix="/api", dependencies=protected)
    return app


app = create_app()
