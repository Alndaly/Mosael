"""出站 HTTP 的重试策略。

**住在 core 而不是 domain**:它是一个 `httpx.Client` 子类加几个纯函数,没有一行数据库、
没有一个领域概念 —— 而它有 13 处引用在 `ai/` 里。放在 domain 会让 `ai → domain` 平白多出
13 条边,把两个包缠成互相依赖(ai 需要 domain 的重试,domain 需要 ai 的适配器),而那个环
除了逼人写函数内延迟导入之外没有任何好处。

次数存进程级状态、改完即时生效:调用点散在十几个适配器里,不少拿不到 db 会话。
"""

from __future__ import annotations

import random
import time

import httpx

from app.core import abort, outbound_guard

#: 默认重试次数(不含首次)。与 db.models.AiRuntimeConfig.max_retries 的列默认值一致。
DEFAULT_MAX_RETRIES = 3
#: 上限。封顶是为了一次限流不至于被拖成几分钟的静默重试。
MAX_RETRIES_CAP = 10

#: 退避基数与封顶。封顶是为了让并发的多个节点不至于把一次限流拖成半分钟的静默等待。
_BASE_SECONDS = 0.6
_MAX_SLEEP_SECONDS = 8.0

_max_retries = DEFAULT_MAX_RETRIES


def auth_headers(api_key: str | None) -> dict[str, str]:
    """Bearer 头 —— **空密钥不发这个头**。

    `f"Bearer {''}"` 的值是 `"Bearer "`(带尾随空格),而那是一个**非法头值**:h11 在发送时
    直接抛 `LocalProtocolError: Illegal header value b'Bearer '`。本地 / 无鉴权端点
    (Ollama、LM Studio、vLLM)正是空密钥的那一批。

    **住在这里是因为它有过第二处。** `ai_chat` 那边写对了、还写了理由,而
    `ai/model_catalog.fetch_models` 不知道那一处存在,无条件发头 —— 于是抛的异常落进一个
    `except Exception`(端点不可达和不实现 /models 都只是「没有目录」),被当成「这个端点
    没有模型」,还往缓存里写一条失败记录,每 60 秒重试一次并再次失败。

    四处后果全是静默的,而且看着都像"本来就该这样":设置页的模型选择器对本地端点永远是空的;
    价格预填拿不到目录报价;`sidecar_provider` 的 `cached_model` 恒为 None,于是一个 128K 的
    本地 qwen3 按 32000 的回退窗口提前四倍开始压缩 —— 设置页显示的 `context_window_source`
    是 `"fallback"`,**它说的是真话,只是没说"我压根问不出来"**。

    判据:加第三个 OpenAI 兼容调用点时,用不用再想一遍这件事。
    """
    key = (api_key or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def clamp_max_retries(value: int) -> int:
    """夹到 [0, MAX_RETRIES_CAP]:0 = 不重试。"""
    return max(0, min(int(value), MAX_RETRIES_CAP))


def set_max_retries(value: int) -> None:
    """设置页写入后调用(经 domain/ai_runtime)。"""
    global _max_retries
    _max_retries = clamp_max_retries(value)


def current_max_retries() -> int:
    return _max_retries


def is_retryable_status(status: int) -> bool:
    """429(限流)与 5xx(过载/网关)是瞬时状态,值得重试;4xx 是请求本身的问题,重试无益。

    这只回答「这个状态码是不是瞬时的」;**能不能重发**还要看方法,见 `status_resend_is_safe`。
    """
    return status == 429 or 500 <= status < 600


#: 重发不会多做一遍的方法(HTTP 语义上幂等)。
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

#: 对方**明说了没处理这一次**的状态码:限流(429)、暂时不接(503)、过载拒单(529)。只有它们,非幂等的请求才重发。
_NOT_PROCESSED_STATUSES = frozenset({429, 503, 529})


def status_resend_is_safe(request: httpx.Request, status: int) -> bool:
    """收到这个状态码之后再发一遍,会不会让供应商多做(多收)一次。

    **非幂等请求只在对方明说「没处理」时重发**(429 / 503 / 529)。500、502、504 和 Cloudflare 的 52x 说的是
    「中间某一层没等到 / 没拿到回答」,不是「源站没做」:中转站在 Cloudflare 后面跑一张慢图,源站过 100 秒还没答,
    CF 回 524,源站照样把图做完、照样扣费。此前这几种一律重发,一次点击最多扣四次;网关 502 时异步提交建出两个
    远端任务,只有后一个被跟踪(见 docs/adr/0019 修订)。它们和读超时同一个道理(见 `resend_is_safe`)。
    幂等的请求(轮询的 GET)照旧遇 5xx 就重发。
    """
    if not is_retryable_status(status):
        return False
    if request.method.upper() in _IDEMPOTENT_METHODS:
        return True
    return status in _NOT_PROCESSED_STATUSES


def resend_is_safe(request: httpx.Request, exc: httpx.RequestError) -> bool:
    """这次失败之后再发一遍,会不会让供应商多做(多收)一次。

    **读超时不重发非幂等请求。** 读超时的意思是请求已经送到、对方在做,只是没在我们等的时间里答完 ——
    一次大 JSON 的对话、一次生成提交,对方多半照样做完并计费。此前一律重发(最多再 3 次),于是一次慢回答
    变成四次全价的调用,而用户只看到一个超时。连不上、连接池等不到这类**请求根本没出门**的失败,重发是安全的;
    GET 这类幂等请求读超时也照旧重发。
    """
    if request.method.upper() in _IDEMPOTENT_METHODS:
        return True
    return not isinstance(exc, httpx.ReadTimeout)


#: 请求送到了、回答断在半路:读超时之外,连接在回答中途断掉(对面掉线、回了半截)也是这一类。
_ANSWER_LOST = (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError)
#: 网关替源站回的「我没等到」:502 / 504,和 Cloudflare 的 520–527、530(源站照样在做)。源站自己回的 500 不算 ——
#: 那是它说「我这儿出错了」,多半没做成。
_GATEWAY_GAVE_UP = frozenset({502, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530})


def sent_but_unanswered(exc: BaseException) -> bool:
    """这次失败是不是「非幂等请求送到了、没等到回答」—— 对方做没做不知道,多半在做、会扣钱。

    和 `resend_is_safe` / `status_resend_is_safe` 同一个判据的另一面:那边据此**不重发**,这里据此**不说成当场被拒**。
    读超时、回答中途断线,或者网关回了「没等到」(502 / 504 / Cloudflare 52x:中间一层没等到,源站照样在做)。连不上、连接池
    等不到、对方明说没处理(429 / 503 / 529)、4xx 都是「没做」。GET 这类幂等请求(轮询、下载)不算 —— 那不是付费的那一下。

    顺着 `__cause__` / `__context__` 找:适配器把 httpx 的异常包成了自己的错误再抛(`raise … from exc`)。
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            return current.request.method.upper() not in _IDEMPOTENT_METHODS and status in _GATEWAY_GAVE_UP
        if isinstance(current, _ANSWER_LOST):
            try:
                method = current.request.method.upper()
            except RuntimeError:  # 没挂请求的(手工抛的):不知道是哪种请求,不猜
                return False
            return method not in _IDEMPOTENT_METHODS
        current = current.__cause__ or current.__context__
    return False


def backoff_seconds(attempt: int) -> float:
    """指数退避 + 少量抖动。抖动是为了让同时失败的多个请求不要在同一刻一起重击供应商。"""
    return min(_BASE_SECONDS * 2**attempt, _MAX_SLEEP_SECONDS) + random.uniform(0, 0.4)


class RetryingClient(abort.AbortableClient):
    """会对瞬时失败自动重试的 httpx.Client。**后端往外发 HTTP 请求一律用它**(tests/test_outbound_requests_pass_one_gate
    钉着):它缺省就装着出站检查(core/outbound_guard.GuardedTransport),每一跳都过同一道闸。

    重试放在 `send()` 而不是包一层函数:适配器们用的是 `with httpx.Client(...) as c` 这种
    写法,换个类名就全都覆盖到了,不必去改每一处调用姿势。

    **流式响应也会被重试**:失败的那次响应会先关掉再重来,不会泄连接。但**请求体若是生成器
    就不能重试** —— httpx 的请求体只能消费一次。目前所有 AI 调用传的都是 json= 或 bytes,
    真出现流式上传时应显式传 max_retries=0。

    `origin`:地址是谁定的(见 outbound_guard.Origin)。缺省是「部署配的」—— 供应商、内置服务、连接里填的地址,
    和它们回给我们去取的东西;别人给的地址(用户填的参考图链接、分享链接)要明说 `Origin.GIVEN`。
    `proxy` / `trust_env=False` 照 httpx 的意思:明说的代理 / 直连;都不给就照进程的代理设置。
    """

    def __init__(
        self, *args, max_retries: int | None = None, origin: outbound_guard.Origin = outbound_guard.Origin.CONFIGURED,
        **kwargs,
    ) -> None:
        self._max_retries = max_retries
        if "transport" not in kwargs:
            route: outbound_guard.Route = outbound_guard.FOLLOW_ENVIRONMENT
            if "proxy" in kwargs:
                route = kwargs.pop("proxy")
            elif kwargs.get("trust_env") is False:
                route = None
            options = {key: kwargs.pop(key) for key in outbound_guard.TRANSPORT_OPTIONS if key in kwargs}
            kwargs["transport"] = outbound_guard.GuardedTransport(origin, route=route, **options)
            #: 代理由那道闸按同一份环境变量定(只认进程的变量,不认操作系统的代理设置;本机回连永远直连)。
            kwargs["trust_env"] = False
        super().__init__(*args, **kwargs)

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:  # type: ignore[override]
        limit = self._max_retries if self._max_retries is not None else _max_retries
        attempts = max(1, limit + 1)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                #: 取消了就不再发、在途的当场断(见 abort.AbortableClient),那一句不重试。
                response = super().send(request, **kwargs)
            except abort.RequestAborted:
                raise
            except httpx.RequestError as exc:
                # 连接断开 / 超时 / DNS:末次才抛,其余退避后再来。
                if last or not resend_is_safe(request, exc):
                    raise
            else:
                if last or not status_resend_is_safe(request, response.status_code):
                    return response
                # 不读完就丢会占着连接,而这条响应我们只关心状态码。
                response.close()
            time.sleep(backoff_seconds(attempt))
        raise AssertionError("unreachable: the last attempt always returns or raises")  # 仅为类型收敛


def post(url: str, *, max_retries: int | None = None, **kwargs) -> httpx.Response:
    """一次性的带重试 POST。给那些原本写 `httpx.post(...)` 的调用点。"""
    with RetryingClient(max_retries=max_retries, timeout=kwargs.pop("timeout", 60)) as client:
        return client.post(url, **kwargs)


def get(url: str, *, max_retries: int | None = None, **kwargs) -> httpx.Response:
    with RetryingClient(max_retries=max_retries, timeout=kwargs.pop("timeout", 60)) as client:
        return client.get(url, **kwargs)
