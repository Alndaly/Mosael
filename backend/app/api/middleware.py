"""挂在每个请求上的几层中间件。**一律写成纯 ASGI,不用 `@app.middleware("http")`。**

`@app.middleware("http")`(Starlette 的 BaseHTTPMiddleware)会把响应体放进一条内存管道,
在另一个任务里转发。对 JSON 无所谓;对素材文件这种大响应就是灾难:浏览器拖视频进度条时,
每次跳转都会中止上一个按范围读取的请求、开一个新的,而中止之后管道那头还在一块块往下推,
直到发现对面没了才停。实测一个 370MB 的录屏,三层这样的中间件让单次跳转从 0.03–6 秒
拉长到 0.2–14.5 秒。纯 ASGI 中间件只是在同一个任务里原样转发 send/receive,对方一断就停。
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.asgi import adding_headers
from app.core.i18n import normalize_locale, set_current_locale, tr
from app.domain.jobs import stop_watching_new_jobs, watch_new_jobs

#: 「这次请求建了几个任务」的响应头。前端的 api/transport 认这个名字。
NEW_JOBS_HEADER = "X-Mosael-New-Jobs"


class CarryLocale:
    """把这次请求的语言放进 ContextVar,序列化那一层照它翻(见 core/i18n)。

    **放在中间件而不是各路由里**:任务消息由十几个接口返回,每处各取一次请求头就是同一个问题
    十几个答案 —— 漏一个,那一屏的任务就还是另一种语言。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            set_current_locale(normalize_locale(Headers(scope=scope).get("accept-language")))
        await self.app(scope, receive, send)


class AnnounceNewJobs:
    """这次请求建了任务,就在响应头上说一声,前端据此立刻刷新任务列表(见 jobs.watch_new_jobs)。

    放在中间件而不是各路由里,理由同 CarryLocale:建任务的接口有几十个,各自记得通知就是
    几十处要记得的事 —— 漏掉的那些,任务要等下一轮轮询才出现在任务中心。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        created, token = watch_new_jobs()

        def headers() -> dict[str, str]:
            return {NEW_JOBS_HEADER: str(len(created))} if created else {}

        try:
            await self.app(scope, receive, adding_headers(send, headers))
        finally:
            stop_watching_new_jobs(token)


class AnswerCrashes:
    """未处理的异常就地答成一个 JSON 500,**在 CORS 那层里面**。

    不这么做的话,异常一路冒到 Starlette 最外层的 ServerErrorMiddleware —— 它在 CORS 外面,
    回的 500 不带 Access-Control-Allow-Origin。浏览器于是连状态码都不给页面看,fetch 直接
    失败,前端只能说「127.0.0.1:8800 连不上」:一个后端 bug 被说成了网络问题(线上:Blender
    「发送当前场景」因为一个 AttributeError 连着报了好几次「连不上」,而后端一直好好的)。

    必须是**最里层**的中间件(最先 add_middleware),这样它的回复还会经过 CORS 和语言那两层。

    答完**照样把异常往外抛**:外层的 ServerErrorMiddleware 看到响应已经发出,只记日志(uvicorn
    控制台里还是那份完整堆栈),不会再回第二次;测试客户端也照样拿得到原异常。响应已经开始发了
    就不答,直接放手 —— 那时候没法再换状态码。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking)
        except Exception:
            if not started:
                await JSONResponse(status_code=500, content={"detail": tr("routeErr_internal")})(scope, receive, send)
            raise


__all__ = ["AnnounceNewJobs", "AnswerCrashes", "CarryLocale", "NEW_JOBS_HEADER"]

