"""MosaelCloud 的 HTTP 装配:同源校验、错误形状、账号与社区分享路由。

**只走同源反代,不做 CORS。** 官网的浏览器端只请求自己域名下的 `/api/cloud/v1/*`,由 Caddy
(生产)或 Next.js 的 rewrite(本地开发)转给本服务。理由写在 `docs/CLOUD_ACCOUNTS.md`:
第一方 cookie 只有在同源时才是第一方的;开了 CORS + `SameSite=None` 反而把 CSRF 面放大。
"""

from __future__ import annotations

from collections.abc import Mapping
from threading import Event, Thread
from time import monotonic, sleep
from urllib.parse import urlsplit

import httpx2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from cloud.api.admin import router as admin_router
from cloud.api.auth import router as accounts_router
from cloud.api.device_tokens import router as device_tokens_router
from cloud.api.mfa import router as mfa_router
from cloud.api.notifications import router as notifications_router
from cloud.api.orders import router as orders_router
from cloud.api.oauth import router as oauth_router
from cloud.api.profile import router as profile_router
from cloud.api.shares import router as shares_router
from cloud.gateway.api import router as gateway_router
from cloud.gateway.jobs_api import router as jobs_router
from cloud.config import API_PREFIX, CloudConfig
from cloud.db import Database
from cloud.errors import CloudError, message
from cloud.models import CloudIpBan, now
from cloud.mailer import CodeSender, SmtpCodeSender
from cloud.sms import PhoneCodeSender, TencentSmsSender
from cloud.oauth import OAuthProvider, default_providers
from cloud.payments.base import PaymentChannel
from cloud.payments.registry import channels_from_config
from cloud.generation.storage import ArtifactStorage, LocalArtifactStorage, R2ArtifactStorage
from cloud.generation.openai_images import ADAPTER as OPENAI_IMAGES
from cloud.generation.kling import ADAPTER as KLING_VIDEO
from cloud.generation.seedance import ADAPTER as SEEDANCE_VIDEO
from cloud.generation import adapters as generation_adapters
from cloud.generation.service import run_one
from cloud.domain import orders as order_domain

#: 会改状态的请求方法。只有带 cookie 的浏览器端点需要过同源闸。
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_of(value: str) -> str:
    """`Origin` 或 `Referer` → `scheme://host[:port]`。`null`、空串、坏地址都给空串。"""
    if not value or value.strip().lower() == "null":
        return ""
    split = urlsplit(value.strip())
    if not split.scheme or not split.netloc:
        return ""
    return f"{split.scheme}://{split.netloc}"


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": message(code)},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def client_ip(request: Request) -> str:
    """真实客户端 IP:经过 nginx 时取 X-Forwarded-For 的最后一跳(nginx 追加的那一项)。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


def _cross_site(request: Request, config: CloudConfig) -> bool:
    """浏览器明确说 cross-site,或者 Origin/Referer 落在别的站点。

    **没有 Origin 也不拦**:curl、桌面端、服务间调用都没有它,而这道闸保护的是"浏览器会自己
    带上 cookie 的写请求" —— 那些请求一定会带 Origin。缺头等于"不是浏览器",不是"绕过"。
    """
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return True
    candidate = request.headers.get("origin") or request.headers.get("referer") or ""
    if not candidate:
        return False
    return _origin_of(candidate) not in config.allowed_origins


def create_app(
    config: CloudConfig | None = None,
    *,
    code_sender: CodeSender | None = None,
    sms_sender: PhoneCodeSender | None = None,
    oauth_providers: Mapping[str, OAuthProvider] | None = None,
    upstream_transport: httpx2.BaseTransport | None = None,
    payment_channels: Mapping[str, PaymentChannel] | None = None,
) -> FastAPI:
    """装配 HTTP 应用。

    `code_sender` / `oauth_providers` / `upstream_transport`(网关连上游模型服务用的传输)/ `payment_channels`(支付渠道)
    是测试 / 嵌入用的注入点:
    不传就用真实实现。**没有
    "开发环境自动跳过验证 / 自动连第三方"的开关** —— 没配 SMTP 时发码接口会明确报错,
    没配 OAuth 凭据时入口明确报"没启用";测试注入假实现,不连外网。
    """
    resolved = config or CloudConfig.from_env()
    resolved.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(resolved.resolved_database_url)
    # 表结构只有一条来源:migrations/ 里的脚本。启动即升到 head,不另走 create_all。
    database.migrate()

    app = FastAPI(
        title="MosaelCloud",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.config = resolved
    app.state.db = database
    app.state.code_sender = code_sender or SmtpCodeSender(resolved)
    app.state.sms_sender = sms_sender or TencentSmsSender(resolved)
    app.state.upstream_transport = upstream_transport
    #: 配了商户凭据的支付渠道(见 payments/registry);一个都没有就是这个部署还没开在线购买。
    app.state.payment_channels = (
        dict(payment_channels) if payment_channels is not None else channels_from_config(resolved)
    )
    app.state.oauth_providers = (
        dict(oauth_providers) if oauth_providers is not None else default_providers()
    )
    app.state.artifact_storage: ArtifactStorage = (
        R2ArtifactStorage(
            account_id=resolved.r2_account_id,
            access_key_id=resolved.r2_access_key_id,
            secret_access_key=resolved.r2_secret_access_key,
            bucket=resolved.r2_bucket,
            public_base_url=resolved.r2_public_base_url,
        )
        if resolved.r2_configured
        else LocalArtifactStorage(resolved.data_dir / "media")
    )
    generation_adapters.register(OPENAI_IMAGES)
    generation_adapters.register(KLING_VIDEO)
    generation_adapters.register(SEEDANCE_VIDEO)

    @app.middleware("http")
    async def same_origin_and_headers(request: Request, call_next):
        path = request.url.path.rstrip("/")
        if (
            path.startswith(API_PREFIX)
            and not path.startswith(f"{API_PREFIX}/admin")
            and path != f"{API_PREFIX}/health"
        ):
            with database.session() as db:
                if db.get(CloudIpBan, client_ip(request)) is not None:
                    return _error(403, "ip_banned")
        if (
            request.method in UNSAFE_METHODS
            and path.startswith(API_PREFIX)
            and _cross_site(request, resolved)
        ):
            return _error(403, "cross_site_request")
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith(API_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(CloudError)
    async def cloud_error(_request: Request, failure: CloudError) -> JSONResponse:
        return JSONResponse(failure.body(), status_code=failure.status_code, headers={"Cache-Control": "no-store"})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _failure: RequestValidationError) -> JSONResponse:
        return _error(422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, failure: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(failure.status_code)
        if code is None:
            return _error(failure.status_code, "internal_error" if failure.status_code >= 500 else "invalid_request")
        return _error(failure.status_code, code)

    @app.get(f"{API_PREFIX}/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(accounts_router, prefix=API_PREFIX)
    app.include_router(admin_router, prefix=API_PREFIX)
    app.include_router(oauth_router, prefix=API_PREFIX)
    app.include_router(profile_router, prefix=API_PREFIX)
    app.include_router(shares_router, prefix=API_PREFIX)
    app.include_router(notifications_router, prefix=API_PREFIX)
    app.include_router(device_tokens_router, prefix=API_PREFIX)
    app.include_router(mfa_router, prefix=API_PREFIX)
    app.include_router(gateway_router, prefix=API_PREFIX)
    app.include_router(jobs_router, prefix=API_PREFIX)
    app.include_router(orders_router, prefix=API_PREFIX)

    if resolved.worker_enabled:
        stop = Event()

        def work() -> None:
            last_reconcile = 0.0
            while not stop.is_set():
                if monotonic() - last_reconcile >= 60:
                    last_reconcile = monotonic()
                    with app.state.db.session() as reconcile_db:
                        try:
                            order_domain.reconcile_pending(
                                reconcile_db, app.state.payment_channels, at=now()
                            )
                            reconcile_db.commit()
                        except Exception:  # noqa: BLE001 —— 对账失败不能拖垮生成 worker
                            reconcile_db.rollback()
                with app.state.db.session() as db:
                    try:
                        handled = run_one(
                            db,
                            config=resolved,
                            adapters=generation_adapters.all(),
                            storage=app.state.artifact_storage,
                        )
                    except Exception:  # noqa: BLE001 —— worker 不能因为一条坏任务退出
                        db.rollback()
                        handled = False
                if not handled:
                    sleep(2)

        app.state.worker_stop = stop
        app.state.worker_thread = Thread(target=work, name="generation-worker", daemon=True)
        app.state.worker_thread.start()

    return app
