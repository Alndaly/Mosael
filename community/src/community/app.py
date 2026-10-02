"""社区服务的 FastAPI 应用。

中间件(由外到内):
1. 请求上下文:按 Accept-Language 定这次说哪种语言(和格式包共用同一个 ContextVar)、记一行不带查询串的访问日志、
   补安全头(`nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy`)。
2. 请求大小上限:按路由给上限(JSON 16 MB、插件包 64 MB、画板文件 200 MB …),先看 Content-Length,
   没有 Content-Length 的边读边数。
3. 写请求限速:同一 IP 每分钟的写请求数。**进程内计数** —— 多个 worker 各数各的,所以它只是一道粗闸;
   真正要数准的(短信、密码失败、设备码)在数据库里数(见 sms.py、security.py)。

CORS 不开:官网和 API 同源(`/api/community/*` 反代到这里),没有跨站调用。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from community.api import admin, auth, items, me, public, shares
from community.config import API_PREFIX, Settings, load_settings
from community.context import Context
from community.errors import ApiError, human_size, render
from community.logs import configure_logging, log_event
from community.storage import LocalStorage, attachment, media_type_of
from mosael_formats.i18n import CURRENT_LOCALE, DEFAULT_LOCALE, LOCALES

logger = logging.getLogger("community.access")

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
]


def negotiate_locale(header: str | None) -> str:
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip().lower()
        primary = tag.split("-")[0]
        if primary in LOCALES:
            return primary
    return DEFAULT_LOCALE


class RequestContextMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        token = CURRENT_LOCALE.set(negotiate_locale(headers.get("accept-language")))
        request_id = headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                existing = {key.lower() for key, _ in message.get("headers", [])}
                extra = [(key, value) for key, value in SECURITY_HEADERS if key not in existing]
                extra.append((b"x-request-id", request_id.encode("latin-1")))
                if b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            CURRENT_LOCALE.reset(token)
            client = scope.get("client") or ("", 0)
            log_event(
                logger,
                "request",
                method=scope.get("method"),
                path=scope.get("path"),  # 不带查询串:本地上传地址的签名在查询串里
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                ip=client[0],
                request_id=request_id,
            )


class BodyTooLarge(ApiError):
    def __init__(self, limit: int) -> None:
        super().__init__(413, "body_too_large", limit=human_size(limit))


class BodyLimitMiddleware:
    def __init__(self, app: Any, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    def limit_for(self, method: str, path: str) -> int:
        s = self.settings
        rest = path[len(API_PREFIX):] if path.startswith(API_PREFIX) else path
        slack = s.cover_max_bytes + 1024 * 1024  # 表单里的封面和其它字段
        if method == "PUT" and rest.startswith("/uploads/"):
            return s.share_max_file_bytes
        if method == "POST" and rest.startswith("/plugins") and (rest == "/plugins" or rest.endswith("/versions")):
            return s.plugin_max_bytes + slack
        if method == "POST" and rest.startswith("/workflows") and (rest == "/workflows" or rest.endswith("/versions")):
            return s.workflow_max_bytes + slack
        return s.json_body_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("method", ""), scope.get("path", ""))
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    error = BodyTooLarge(limit)
                    response = JSONResponse(error.payload(), status_code=413)
                    await response(scope, receive, send)
                    return
        seen = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge(limit)
            return message

        await self.app(scope, limited_receive, send)


class WriteRateLimitMiddleware:
    """同一 IP 每分钟的写请求数(进程内滑动窗口)。见模块说明:这是一道粗闸,不是账本。"""

    def __init__(self, app: Any, per_minute: int) -> None:
        self.app = app
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS") or self.per_minute <= 0:
            await self.app(scope, receive, send)
            return
        ip = (scope.get("client") or ("", 0))[0]
        now = time.monotonic()
        with self.lock:
            window = self.hits.setdefault(ip, deque())
            while window and now - window[0] > 60:
                window.popleft()
            limited = len(window) >= self.per_minute
            if not limited:
                window.append(now)
            if len(self.hits) > 50_000:  # 别让一次扫描把内存吃满
                self.hits = {key: value for key, value in self.hits.items() if value and now - value[-1] <= 60}
        if limited:
            error = ApiError(429, "rate_limited")
            response = JSONResponse(error.payload(), status_code=429, headers={"Retry-After": "60"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _validation_fields(exc: RequestValidationError) -> str:
    fields = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path", "header")]
        fields.append(".".join(location) or "body")
    return ", ".join(dict.fromkeys(fields)) or "body"


def create_app(settings: Settings | None = None, *, context: Context | None = None) -> FastAPI:
    settings = settings or (context.settings if context else load_settings())
    if context is None:
        configure_logging(settings.log_level, settings.log_format)
        problems = settings.problems()
        if problems:
            raise RuntimeError("社区服务的生产配置不完整:\n  " + "\n  ".join(problems))
        if settings.development:
            # 本地开发:启动时把库升到最新,不用先记得跑 migrate。生产由部署步骤显式跑(见 docs/DEPLOY_COMMUNITY.md)。
            from community.cli import migrate

            Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
            migrate(settings.database_url)
        context = Context.build(settings)

    app = FastAPI(
        title="Mosael Community",
        version="1",
        #: FastAPI 0.142 起自带 OpenTelemetry,默认读 OTEL_* 环境变量自己挂导出器;社区服务不往外发遥测,全部关掉。
        telemetry={"auto_configure": False, "tracing": False, "metrics": False, "logs": False},
        docs_url=None if settings.production else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if settings.production else f"{API_PREFIX}/openapi.json",
    )
    app.state.ctx = context

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.payload(), status_code=exc.status, headers=exc.headers or None)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        error = ApiError(422, "invalid_request", fields=_validation_fields(exc))
        return JSONResponse(error.payload(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(exc.status_code, "invalid_request")
        payload = {"error": {"code": code, "message": render(code, None, fields=str(exc.detail))}}
        return JSONResponse(payload, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("community.error").exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(ApiError(500, "internal_error").payload(), status_code=500)

    @app.get(f"{API_PREFIX}/health", include_in_schema=False)
    def health() -> dict:
        return {"ok": True}

    if settings.serve_media and isinstance(context.storage, LocalStorage):
        prefix = settings.media_url_prefix.rstrip("/")

        @app.get(f"{prefix}/{{key:path}}", include_in_schema=False)
        def media(key: str) -> FileResponse:
            """开发环境由服务自己出本地存储的文件;生产由反代出(Caddyfile 里同样的头)。"""
            storage = context.storage
            assert isinstance(storage, LocalStorage)
            try:
                path = storage.path_of(key)
            except ValueError as exc:
                raise ApiError(404, "not_found") from exc
            if not path.is_file():
                raise ApiError(404, "not_found")
            headers = {"Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "public, max-age=3600"}
            if key.startswith("files/"):
                headers["Content-Disposition"] = attachment(path.name)
            return FileResponse(path, media_type=media_type_of(path.name), headers=headers)

    for router in (
        auth.router,
        me.router,
        items.workflows_router,
        items.plugins_router,
        items.assets_router,
        shares.router,
        public.router,
        admin.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    app.add_middleware(WriteRateLimitMiddleware, per_minute=settings.write_requests_per_minute)
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    return app


def app_factory() -> FastAPI:
    """uvicorn 的入口:`uvicorn community.app:app_factory --factory`。"""
    return create_app()


__all__ = ["BodyLimitMiddleware", "create_app", "app_factory", "negotiate_locale"]
