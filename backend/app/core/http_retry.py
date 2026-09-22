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

#: 默认重试次数(不含首次)。与 db.models.AiRuntimeConfig.max_retries 的列默认值一致。
DEFAULT_MAX_RETRIES = 3

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


def set_max_retries(value: int) -> None:
    """设置页写入后调用。夹到 [0, 10]:0 = 不重试。"""
    global _max_retries
    _max_retries = max(0, min(int(value), 10))


def current_max_retries() -> int:
    return _max_retries


def is_retryable_status(status: int) -> bool:
    """429(限流)与 5xx(过载/网关)是瞬时状态,值得重试;4xx 是请求本身的问题,重试无益。"""
    return status == 429 or 500 <= status < 600


def backoff_seconds(attempt: int) -> float:
    """指数退避 + 少量抖动。抖动是为了让同时失败的多个请求不要在同一刻一起重击供应商。"""
    return min(_BASE_SECONDS * 2**attempt, _MAX_SLEEP_SECONDS) + random.uniform(0, 0.4)


class RetryingClient(httpx.Client):
    """会对瞬时失败自动重试的 httpx.Client。

    重试放在 `send()` 而不是包一层函数:适配器们用的是 `with httpx.Client(...) as c` 这种
    写法,换个类名就全都覆盖到了,不必去改每一处调用姿势。

    **流式响应也会被重试**:失败的那次响应会先关掉再重来,不会泄连接。但**请求体若是生成器
    就不能重试** —— httpx 的请求体只能消费一次。目前所有 AI 调用传的都是 json= 或 bytes,
    真出现流式上传时应显式传 max_retries=0。
    """

    def __init__(self, *args, max_retries: int | None = None, **kwargs) -> None:
        self._max_retries = max_retries
        super().__init__(*args, **kwargs)

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:  # type: ignore[override]
        limit = self._max_retries if self._max_retries is not None else _max_retries
        attempts = max(1, limit + 1)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = super().send(request, **kwargs)
            except httpx.RequestError:
                # 连接断开 / 超时 / DNS:末次才抛,其余退避后再来。
                if last:
                    raise
            else:
                if last or not is_retryable_status(response.status_code):
                    return response
                # 不读完就丢会占着连接,而这条响应我们只关心状态码。
                response.close()
            time.sleep(backoff_seconds(attempt))
        raise AssertionError("unreachable: 末次必定返回或抛出")  # 仅为类型收敛


def post(url: str, *, max_retries: int | None = None, **kwargs) -> httpx.Response:
    """一次性的带重试 POST。给那些原本写 `httpx.post(...)` 的调用点。"""
    with RetryingClient(max_retries=max_retries, timeout=kwargs.pop("timeout", 60)) as client:
        return client.post(url, **kwargs)


def get(url: str, *, max_retries: int | None = None, **kwargs) -> httpx.Response:
    with RetryingClient(max_retries=max_retries, timeout=kwargs.pop("timeout", 60)) as client:
        return client.get(url, **kwargs)
