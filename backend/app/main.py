from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import math

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from fastapi import Depends

from app.api.routes.agent import router as agent_router
from app.api.routes.session_groups import router as session_groups_router
from app.api.routes.agent_credentials import router as agent_credentials_router
from app.api.routes.agent_tools import router as agent_tools_router
from app.api.routes.agent_browser import router as agent_browser_router
from app.api.routes.browser_profiles import router as browser_profiles_router
from app.api.routes.asr import router as asr_router
from app.api.routes.denoise import router as denoise_router
from app.api.routes.documents import router as documents_router
from app.api.routes.separation import router as separation_router
from app.api.routes.assets import router as assets_router
from app.api.routes.entities import router as entities_router
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
from app.api.routes.scenes import router as scenes_router
from app.api.routes.blender import router as blender_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.sequences import router as sequences_router
from app.api.routes.settings import router as settings_router
from app.api.routes.shares import router as shares_router
from app.api.routes.publish import router as publish_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.collaboration import router as collaboration_router
from app.api.routes.job_worker import router as job_worker_router
from app.api.routes.browser_worker import router as browser_worker_router
from app.api.routes.publish_worker import router as publish_worker_router
from app.api.routes.boards import router as boards_router
from app.api.routes.notes import router as notes_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.workspaces import router as workspaces_router
from app.core.config import allowed_hosts, settings
from app.api.middleware import NEW_JOBS_HEADER, AnnounceNewJobs, AnswerCrashes, CarryLocale
from app.api.deps import require_worker_key
from app.core.logging import configure_logging
from app.core.rate_limit import install_rate_limiting
from app.core.worker_key import issue_worker_key
from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.migrations import init_db

logger = logging.getLogger(__name__)
from app.api.deps.auth import get_current_user
from app.domain.permissions import NotVisible, PermissionDenied
from app.domain.assets import AssetProjectError
from app.domain.assets.importer import AssetFileTypeError
from app.domain.notes import NoteDomainError
from app.domain.scenes.operations import SceneDomainError
from app.domain.entities import EntityDomainError
from app.domain.blender.bridge import BlenderDomainError
from app.domain.assets import reconcile_broken_media_info
from app.domain.agent.host import reconcile_orphaned_agent_sessions
from app.domain.blender.bridge import reconcile_orphaned_transfers as reconcile_blender_transfers
from app.domain.jobs import register_external_kind
from app.domain.restart import reconcile_after_restart
from app.domain.assets.proxies import reconcile_missing_proxies
from app.workers.scheduler import start_scheduler_loop, stop_scheduler_loop



@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()  # 先配好日志,后续启动步骤才追溯得到
    logger.info("Mosael backend starting (host=%s port=%s)", settings.backend_host, settings.backend_port)
    # 主密钥先取:桌面版由 Electron 经标准输入交来(见 core/secrets_at_rest),在启动时读掉,不留到某次
    # 解密时才在随便哪条线程里去读;读不到在这里就报出来。
    from app.core.secrets_at_rest import master_key

    master_key()
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
    # 启动收尾是一次用例:下面几个函数只改对象,这一段正常结束时一起提交(见 core/unit_of_work)。
    with unit_of_work() as db:
        # 重启杀掉一切进程内的线程/子进程/连接,**在调用之前就落库的那些「进行中」的行
        # 自己不会醒过来**。谁来收尾登记在 domain/restart 的那张表上,由一条棘轮按 ORM
        # 推导出「哪些表需要登记」——此前是四个手写的调用,而第五、第六处照样漏了。
        settled = reconcile_after_restart(db)
        # 卡在 running 的智能体会话拨回 idle,否则前端永远「思考中」。它不按表登记:
        # 要收的不止 agent_sessions 一张(那一轮留下的确认卡也要作废)。
        reconcile_orphaned_agent_sessions(db)
        # Backfill preview proxies for any videos missing one (best-effort).
        reconcile_missing_proxies(db)
        # 修复 remux 上线前导入的坏素材(直录 webm 缺时长/缩略图/波形)。
        reconcile_broken_media_info(db)
    # Blender 互通留在磁盘上(transfer.json),推导不出来,所以单列 —— 同一条规矩的第六处。
    settled["blender_transfers"] = reconcile_blender_transfers()
    for table, count in settled.items():
        if count:
            logger.info("reconciled %d orphaned %s left by a previous restart", count, table)
    # 插件生成供应商(ComfyUI 等)的模型清单在后台刷一遍,之后隔一会儿看一眼指纹:ComfyUI 里新存的工作流,
    # 一分钟内就在选择器里。后台做:一台没开的 ComfyUI 不该拖慢启动(见 generation/plugin_connections)。
    from app.domain.plugins import catalog_watch

    catalog_watch.start_watching()
    # 本机引擎「装好了没有」要起子进程 import 一遍才知道(funasr、demucs 各一两秒),答案进程内缓存。启动后在后台
    # 先探一遍:「设置 → 能力提供方」、转写 / 分离的下拉第一次打开时不必现等 —— 开发态每改一次代码后端就重启,
    # 那一页每次都白屏好几秒(用户:「要加载很久,会有很长时间的白屏」)。
    _warm_engine_probes()
    if settings.scheduler_enabled:
        start_scheduler_loop()
        logger.info("scheduler loop started")
    if settings.feishu_autostart:
        from app.integrations.feishu.connections import autostart_enabled_bots, stop_all_connections
        from app.integrations.feishu.inbound import notify_interrupted_chats

        # 被重启打断的飞书会话:把中断说明发回原聊天。只写进库的话,在飞书里发消息的那个人
        # 只看到一片沉默 —— 和"还在处理中"分辨不出来,于是一直等。
        with SessionLocal() as db:
            notified = notify_interrupted_chats(db)
        if notified:
            logger.info("notified %d feishu chat(s) about a turn interrupted by restart", notified)

        autostart_enabled_bots()
    # 壳交了 pid 就盯着它:壳被强杀时后端不留成孤儿占着端口(见 core/lifeline)。
    from app.core.lifeline import watch_parent_from_env

    watch_parent_from_env()
    logger.info("Mosael backend ready")
    yield
    logger.info("Mosael backend shutting down")
    catalog_watch.stop_watching()
    stop_scheduler_loop()
    if settings.feishu_autostart:
        stop_all_connections()
    # 常驻的识别 / 合成进程(一个就是几 GB 权重)跟着后端一起走。
    from app.ai.runtime import asr_daemon, tts_daemon

    asr_daemon.shutdown_pool()
    tts_daemon.shutdown_pool()


def _warm_engine_probes() -> None:
    """后台把本机引擎的就绪探测跑一遍,填上各自的缓存(见 lifespan 里那段)。探不出来只记日志:那是「没装」,不是错。"""
    import threading

    from app.ai.providers.registry import DENOISE_ADAPTERS, SEPARATION_ADAPTERS
    from app.ai.runtime import asr_models
    from app.domain.voices.transcription import LOCAL_ENGINES

    def probe() -> None:
        from app.media.render_executor import ffmpeg_has_libass

        #: 没有 libass 的 ffmpeg(Homebrew 的 core 版)烧不了 ASS:文字只能走浏览器渲 PNG 那条路。启动时记一笔,
        #: 真导出时 ensure_text_can_burn 会在建任务之前把话说清楚。
        if not ffmpeg_has_libass(settings.ffmpeg):
            logger.warning("ffmpeg %s has no libass (subtitles filter); text burn-in relies on the browser path", settings.ffmpeg)
        for engine in LOCAL_ENGINES:
            asr_models.resolve_engine_python(engine)
        for adapter in (*DENOISE_ADAPTERS.values(), *SEPARATION_ADAPTERS.values()):
            try:
                adapter.runtime_ready()
            except Exception:  # noqa: BLE001 — 探测失败 = 跑不起来,由用到它的地方说
                logger.debug("engine probe %s failed", adapter.engine_id, exc_info=True)

    threading.Thread(target=probe, name="engine-probes", daemon=True).start()


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
        from app.domain import ai_runtime

        ai_runtime.apply_to_process(db)
        # 内网访问的允许名单同理(见 domain/outbound_allowlist)。
        from app.domain import outbound_allowlist

        outbound_allowlist.apply_to_process(db)


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

    @app.exception_handler(NoteDomainError)
    async def _note_error(_request: Request, exc: NoteDomainError) -> JSONResponse:
        """笔记领域的异常按它自己声明的状态码翻。

        和上面两个装在一处、理由也一样:笔记不只从 `routes/notes` 进来 —— 画板保存要校验
        引用的文档、工作流知识节点要读它。收在边界,那些调用方就不必反过来 catch
        HTTPException 再翻回自己的领域错误。
        """
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(AssetProjectError)
    async def _asset_project_error(_request: Request, exc: AssetProjectError) -> JSONResponse:
        """素材要挂的项目不在这个工作区。入库有十几个入口(上传、按路径、从链接、插件交回的
        文件……),判断收在 assets/project_scope 一处,翻成 422 也收在这一处。"""
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(AssetFileTypeError)
    async def _asset_file_type_error(_request: Request, exc: AssetFileTypeError) -> JSONResponse:
        """素材库不收这种文件(ADR 0031)。和上面同一个理由:入库的入口很多,判断在 assets/importer 一处,翻成 415 也在这一处。"""
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(SceneDomainError)
    async def _scene_error(_request: Request, exc: SceneDomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(EntityDomainError)
    async def _entity_error(_request: Request, exc: EntityDomainError) -> JSONResponse:
        """资产库的异常按它自己声明的状态码翻(404 / 409 / 422)。"""
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(BlenderDomainError)
    async def _blender_error(_request: Request, exc: BlenderDomainError) -> JSONResponse:
        """Blender 互通:502 说的是**上游**没响应,不是调用方请求有错。"""
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """校验失败的 422。**自己渲染,因为默认那份渲染不出来。**

        FastAPI 默认会把出错的原值回显进错误体,而 Starlette 的 JSONResponse 用
        `allow_nan=False` 编码(对的 —— NaN 不是合法 JSON)。于是"请求里有个 NaN"这件事的
        结局是编码器抛异常、客户端收到 500:一个**因为拒绝得对而崩掉**的响应,而 500 会让人
        以为是服务端坏了,去查完全不相干的地方。

        所以把原值过一遍:非有限的数换成它的字面写法(照样看得出是 NaN 还是 Infinity),
        其余原样。不整个丢掉 input —— 少了它,"哪个字段不对"要靠 loc 自己拼。
        """

        def safe(value: object) -> object:
            if isinstance(value, float) and not math.isfinite(value):
                return repr(value)
            if isinstance(value, dict):
                return {key: safe(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [safe(item) for item in value]
            return value

        return JSONResponse(status_code=422, content={"detail": safe(exc.errors())})


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
    # 工作流一次运行开的浏览器会话,随这次运行落终态而关(成功、失败、取消)——
    # 同样是「任务不认识浏览器,浏览器认识任务」。
    from app.domain import browser as browser_sessions
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
    from app.ai.sidecar import pi_client
    from app.domain.network import subprocess_env_for_child
    # 插件可以是生成供应商(ADR 0020):生成域把「实例变了就对齐连接」(能力表的 generation 那一项)和
    # 「plugin:<包> 的 Adapter」登记进来。插件域不认识生成域,ai/providers 的 registry 也不认识插件 —— 两头都是在这里接上的。
    from app.domain.generation import plugin_connections
    # 插件可以在运行时报出工具(ComfyUI:每张工作流一个);清单刷新之后,存着的老节点由工作流域改写。
    from app.domain.plugins import dynamic_tools
    from app.domain.workflows import plugin_references
    from app.domain.boards import plugin_references as board_plugin_references

    # 宿主能力的契约(ADR 0031 §5):各项能力的宿主侧把自己登记进能力表,设置页照表列出每一项。
    from app.domain import capabilities
    from app.domain import documents
    from app.domain.generation import public_links
    from app.domain import audio_capabilities
    from app.domain.voices import transcription
    from app.domain import translate
    from app.domain.voices import speech

    capabilities.register(public_links.CAPABILITY)
    capabilities.register(documents.CAPABILITY)
    capabilities.register(audio_capabilities.DENOISE)
    capabilities.register(audio_capabilities.SEPARATION)
    capabilities.register(transcription.CAPABILITY)
    capabilities.register(translate.CAPABILITY)
    capabilities.register(speech.CAPABILITY)
    # 生成、工具清单也在这张表里(ADR 0032 §1:只剩一张),只是不参与挑选;表里挂着插件实例变了之后宿主侧怎么
    # 对齐的钩子。插件域不 import 能力表,由这里把查钩子的函数交给它的转发器。
    from app.domain.plugins import host_capabilities
    from app.domain.plugins.manifest import GENERATION, TOOLS

    capabilities.register(plugin_connections.CAPABILITY)
    from app.domain import model_library

    capabilities.register(model_library.CAPABILITY)
    from app.domain import workflow_library

    capabilities.register(workflow_library.CAPABILITY)
    capabilities.register(capabilities.Capability(
        name=TOOLS, label_key="capability_tools", description_key="capability_tools", pickable=False,
        on_instance_change=dynamic_tools.refresh,
    ))
    host_capabilities.use_table(capabilities.instance_hooks)
    # 调用类能力的收尾(ADR 0033 §3):智能体、工作流直接调了认领文档解析的工具,结果存成那份文档的一次解析。
    from app.domain.documents import extraction as document_extraction

    capabilities.register_finish(documents.DOCUMENT_PARSE, document_extraction.finish_plugin_call)
    # 「用在哪」(ADR 0032 §4):宿主界面入口各自登记;工作流节点、智能体工具现扫各自的注册表。
    documents.register_uses()
    public_links.register_uses()
    audio_capabilities.register_uses()
    transcription.register_uses()
    translate.register_uses()
    speech.register_uses()
    #: 生成、工具清单不走挑法(没有候选、没有默认),用在哪也照样说得出。
    from app.core.i18n import fragment

    capabilities.register_use(capabilities.Use(GENERATION, "app", fragment("capUse_generationModels")))
    capabilities.register_use(capabilities.Use(TOOLS, "app", fragment("capUse_pluginTools")))
    model_library.register_uses()
    workflow_library.register_uses()
    from app.domain.agent.confirmable import registry as confirmable_registry
    from app.domain.workflows import capability_uses as workflow_capability_uses

    capabilities.register_use_finder(workflow_capability_uses.capability_uses)
    capabilities.register_use_finder(confirmable_registry.capability_uses)
    agent_receipts.install()
    plugin_connections.install()
    plugin_references.install()
    board_plugin_references.install()
    asset_plugin_bridge.install()
    board_receipts.install()
    browser_sessions.install()
    tts_runtime_config.use_source(tts_settings.load)
    pi_client.use_proxy_source(subprocess_env_for_child)


_wire_seams()


#: FastAPI 0.142 起自带 OpenTelemetry:默认读 OTEL_* 环境变量、自己挂上导出器。Mosael 是装在用户电脑上的应用,
#: 请求路径、报错原文和堆栈都不该因为某个依赖带进了 SDK、用户环境里又恰好设了导出地址就被发出去 —— 全部关掉。
TELEMETRY_OFF = {"auto_configure": False, "tracing": False, "metrics": False, "logs": False}


def create_app() -> FastAPI:
    app = FastAPI(title="Mosael API", version="0.1.0", lifespan=lifespan, telemetry=TELEMETRY_OFF)
    _install_permission_handlers(app)
    install_rate_limiting(app, settings)
    # 这几层都是纯 ASGI(见 api/middleware 的说明:包在大文件响应外面的 BaseHTTPMiddleware
    # 会让拖视频进度条慢好几倍)。
    # 最先加 = 最里层:它答出来的 500 还要经过 CORS(和语言),见 AnswerCrashes 的说明。
    app.add_middleware(AnswerCrashes)
    app.add_middleware(CarryLocale)
    app.add_middleware(AnnounceNewJobs)
    # Auth is bearer-token (no cookies) and the packaged Electron shell loads the frontend
    # from file://, whose fetches carry Origin: null — hence an explicit "null" here rather
    # than a same-origin policy.
    #
    # NOT "*": a wildcard switches off the browser's origin check on every reply, and the
    # routes that carry no user session are what that check is standing in front of.
    #
    # The hole this comment used to describe — an unauthenticated publish-worker channel that
    # any page could call AND READ THE REPLY of, exposing publish tasks and account proxy
    # strings with credentials in them — is closed. All three worker routers are mounted
    # behind require_worker_key (a per-process secret written to the data directory, which a
    # web page cannot read), and the webhook trigger compares a per-task secret.
    #
    # What stays open by nature is /api/auth. On a first-run empty database, or on a
    # deployment that set MOSAEL_OPEN_REGISTRATION, register succeeds for anyone who can reach
    # the port — and under a wildcard any page the user happened to be browsing could mint
    # itself a session here and read the token back.
    #
    # This bounds disclosure, not side effects: a plain cross-origin POST still reaches the
    # handler even when the browser refuses to hand back the body. Naming the origins we
    # actually ship from is also what keeps the next route that ships open by mistake from
    # being readable by every page at once.
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
            # 后端自己托管打包好的前端时的来源。**端口跟着 settings 走** —— 它是可配的
            # (MOSAEL_BACKEND_PORT),而这两行此前写死 8800:换了端口就只剩 CORS 错误,
            # 而错误信息里不会提到端口,查起来要绕一圈。
            f"http://localhost:{settings.backend_port}",
            f"http://127.0.0.1:{settings.backend_port}",
            # 部署到服务器时额外允许的来源(MOSAEL_CORS_ORIGINS,逗号分隔)。上面那份是照桌面端
            # 写死的;前端本来就能指向任意后端(设置里的「服务端地址」),而"几个人共用一台
            # 服务器"这件事此前卡在这份写死的名单上。**要哪个域名写哪个域名,不接受 `*`** ——
            # 理由见上面那段:/api/auth 按性质开放,通配符下任何页面都能在这里给自己开个号。
            *[one.strip().rstrip("/") for one in settings.cors_origins.split(",") if one.strip()],
        ],
        # Chrome MV3 side panels have their own opaque extension origin. Keep this deliberately
        # narrower than ``chrome-extension://.*``: a real extension id is exactly 32 chars from
        # a-p. CORS only permits the browser to read a response; every useful route still requires
        # the user's bearer session and workspace authorization.
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        # 跨源时浏览器默认只让页面读到几个基础响应头;这个要点名放行,前端才看得见。
        expose_headers=[NEW_JOBS_HEADER],
    )
    # 名单里的 `null` 只给打包版的界面(file://)用;任何网页里的 sandboxed iframe 也是 `null`。桌面版在 CORS
    # **外面**再加一道:null 来源必须带主密钥派生的壳令牌(见 core/shell_origin)。后加的中间件在外层,先于 CORS 生效。
    if settings.local_desktop:
        from app.core.shell_origin import ShellOriginGuard

        app.add_middleware(ShellOriginGuard)
    # Host 头必须是本机的名字(或部署者在 MOSAEL_ALLOWED_HOSTS 里写的):挡 DNS rebinding —— 一个把自己的域名
    # 解析到 127.0.0.1 的网页,发出的请求 Host 是它自己的域名。
    allowed = allowed_hosts()
    if allowed:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)

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
    app.include_router(separation_router, prefix="/api", dependencies=protected)
    app.include_router(denoise_router, prefix="/api", dependencies=protected)
    app.include_router(documents_router, prefix="/api", dependencies=protected)
    app.include_router(voices_router, prefix="/api", dependencies=protected)
    app.include_router(translate_router, prefix="/api", dependencies=protected)
    app.include_router(websearch_router, prefix="/api", dependencies=protected)
    app.include_router(luts_router, prefix="/api", dependencies=protected)
    app.include_router(fonts_router, prefix="/api", dependencies=protected)
    app.include_router(sequences_router, prefix="/api", dependencies=protected)
    app.include_router(jobs_router, prefix="/api", dependencies=protected)
    app.include_router(notifications_router, prefix="/api", dependencies=protected)
    app.include_router(collaboration_router, prefix="/api", dependencies=protected)
    app.include_router(generation_router, prefix="/api", dependencies=protected)
    app.include_router(blender_router, prefix="/api", dependencies=protected)
    app.include_router(scenes_router, prefix="/api", dependencies=protected)
    app.include_router(entities_router, prefix="/api", dependencies=protected)
    app.include_router(scheduler_router, prefix="/api", dependencies=protected)
    app.include_router(workflows_router, prefix="/api", dependencies=protected)
    app.include_router(boards_router, prefix="/api", dependencies=protected)
    app.include_router(notes_router, prefix="/api", dependencies=protected)
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
