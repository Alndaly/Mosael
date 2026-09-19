"""Text translation with two backends:

- **google**: Google's free (unofficial) translate endpoint — no API key, good enough for a
  quick subtitle pass, but it translates cue by cue with no context.
- **ai**: an LLM through the user's provider connection — slower and billed, but it reads
  the sentence rather than the words. Same call shape, so a caller only picks `engine`.

Both live here so every caller (workflow translate node, editor subtitle panel) gets the same
two choices from one place. Kept dependency-light (httpx only).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time

import httpx

from app.core.usage_scope import run_in_scope
from app.domain.ai_chat import AiChatError, ChatTarget, chat, target_for
from app.core import http_retry as ai_retry
from app.domain.usage import BillableCall, billable

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 30
# AI 供应商的字幕请求有限并发；Google 免费端点走下面的单通道节流。
_MAX_PARALLEL = 8
# 免费端点会按客户端标识、出口或突发频率拒绝请求。请求本身通常比这个间隔慢，但本地代理
# 命中快速链路时仍要把起始时间摊开；它不是供应商 API，不能把并发当成稳定能力。
_GOOGLE_MIN_INTERVAL_SECONDS = 0.35

# Target languages surfaced in the UI (google codes; the AI path takes the same codes as hints).
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("zh-CN", "简体中文"),
    ("zh-TW", "繁體中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("ru", "Русский"),
)
_LANG_NAMES = dict(LANGUAGES)


class TranslateError(RuntimeError):
    """带 key 的错误。

    领域里不拼句子 —— 存 key + 参数,出口(路由)按请求方语言翻。`str(exc)` 仍给一句默认语言的
    人话,好让日志和不走 HTTP 的调用方(工作流节点)有东西可看;上游 AiChatError 转过来的消息
    不是 key,`t` 查不到就原样返回,正好。
    """

    def __init__(self, key: str, **params: object) -> None:
        from app.core.i18n import DEFAULT_LOCALE, t

        self.key = key
        self.params = params
        super().__init__(t(key, DEFAULT_LOCALE, **params))


def language_label(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def resolve_ai_chat_target(db, profile_id: str | None, user_id: str | None, model: str = "") -> ChatTarget:
    from app.domain import provider_credentials
    from app.domain.providers import find_enabled_connection, first_enabled_connection

    profile = (
        find_enabled_connection(db, "", profile_id, owner_user_id=user_id)
        if profile_id
        else first_enabled_connection(db, owner_user_id=user_id)
    )
    if profile is None or not profile.enabled:
        raise TranslateError("translateErr_noProvider")
    resolved = provider_credentials.resolve_connection(db, profile, user_id)
    if resolved is None:
        raise TranslateError("translateErr_noCredential", name=profile.name)
    try:
        # model 留空 = 按这条连接的 chat 能力解析(target_for 自己做)。给了就用给的那个:
        # 一条连接上常常有好几个模型,而"用哪个模型翻译"和"用哪条连接"是两个问题。
        return target_for(db, resolved, model=model)
    except AiChatError as exc:
        raise TranslateError(str(exc)) from exc


def ai_translate(db, text: str, target: str, profile_id: str | None, user_id: str | None, model: str = "") -> str:
    """Translate via an enabled AI provider (LLM). Reused by the workflow node + the API."""
    if not text.strip():
        return ""
    return ai_translate_with(resolve_ai_chat_target(db, profile_id, user_id, model), text, target)


def ai_translate_with(
    chat_target: ChatTarget,
    text: str,
    target: str,
    client: httpx.Client | None = None,
    call: BillableCall | None = None,
) -> str:
    if not text.strip():
        return ""
    prompt = (
        f"Translate the following text into {language_label(target)} ({target}). "
        f"Output only the translation, no explanations or quotes.\n\n{text}"
    )
    try:
        return chat(
            chat_target,
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout=_TIMEOUT * 2,
            client=client,
            call=call,
            label="AI 翻译",
        ).strip()
    except AiChatError as exc:
        raise TranslateError(str(exc)) from exc


def translate(
    db,
    text: str,
    target: str,
    *,
    user_id: str | None,
    engine: str = "google",
    profile_id: str | None = None,
    model: str = "",
) -> str:
    """Dispatch to the requested engine."""
    if engine == "ai":
        return ai_translate(db, text, target, profile_id, user_id, model)
    return google_translate(text, target)


def google_translate(text: str, target: str, source: str = "auto", client: httpx.Client | None = None) -> str:
    """Free Google translate. Returns the translation, or "" for empty input.

    **没给 client 时自己开一个会重试的。** 批量那条路(`translate_many`)一直用
    `RetryingClient`,而逐句那条(工作流的翻译节点,一句一次调用)走的是裸 `httpx.get` ——
    于是同一个 429,在批量里退避重试、在节点里当场失败。设置页那句「连接断开/超时/限流时
    自动重试」管的是所有 AI 调用,这里漏了一条缝。免费端点按 IP 限流,而一条字幕轨就是
    几十上百次调用,正好是最需要重试的地方。
    """
    if not text.strip():
        return ""
    own = client is None
    http = client or ai_retry.RetryingClient(timeout=_TIMEOUT)
    try:
        response = http.get(
            _GOOGLE_URL,
            # `gtx` 是旧的匿名客户端标识。2026-09 起，Google 会跨多个出口统一把它打到
            # Sorry/429，而同一请求用 Chrome 字典客户端仍正常返回；不要再把这种响应误判成
            # 某一个代理 IP 被封。
            params={"client": "dict-chrome-ex", "sl": source, "tl": target, "dt": "t", "q": text},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        # **不要把 exc 原样拼进去。** httpx 的这句话带着完整 URL,而 URL 里是整段被百分号
        # 编码的原文 —— 真机上用户看到的是一屏 %E5%B7%A5%E4%BD%9C,错误本身淹在里面。
        status = exc.response.status_code
        if status == 429:
            raise TranslateError("translateErr_googleRateLimited") from exc
        raise TranslateError("translateErr_googleHttp", status=status) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise TranslateError("translateErr_googleUnreachable", reason=type(exc).__name__) from exc
    finally:
        if own:
            http.close()
    # data[0] = list of [translated_segment, original_segment, ...]; join the translated parts.
    segments = data[0] if isinstance(data, list) and data else []
    return "".join(seg[0] for seg in segments if isinstance(seg, list) and seg and seg[0])


def translate_many(
    db,
    texts: list[str],
    target: str,
    *,
    user_id: str | None,
    engine: str = "google",
    profile_id: str | None = None,
    model: str = "",
) -> list[str]:
    """Translate a batch, running the round-trips concurrently.

    AI 供应商的各句调用可以并行。Google 免费端点则必须串行并限制请求起始频率：它会按客户
    端标识、出口或突发流量拒绝请求，8 路并发可能把本来可用的路径打进
    ``Sorry / unusual traffic``，随后连单请求都会持续 429。

    Two things are deliberately done before the pool starts: the chat target is resolved from the DB
    (a Session is single-threaded), and one httpx.Client is created so the batch shares
    connections instead of repeating the TLS handshake per cue.
    """
    if not texts:
        return []
    chat_target = resolve_ai_chat_target(db, profile_id, user_id, model) if engine == "ai" else None
    indexed = [(i, text) for i, text in enumerate(texts) if text.strip()]
    results = [""] * len(texts)
    if not indexed:
        return results

    workers = min(_MAX_PARALLEL, len(indexed))

    def run(translate_one) -> None:
        # run_in_scope:contextvars 不会自动跨进工作线程,而记账归属就在里面。
        # map() 在消费时抛出第一个异常,所以一条失败仍然让整批失败 —— 调用方本来就是整批应用的。
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, translated in pool.map(run_in_scope(translate_one), indexed):
                results[index] = translated

    if chat_target is None:  # google:免费端点,不产生供应商用量,不开记账
        # 429 后立刻停：通用 RetryingClient 的指数重试适合有正式配额的供应商 API，但 Google
        # 免费端点会把同一出口的并发重试视为更多异常流量。共享连接仍保留，省掉逐句 TLS 握手。
        with ai_retry.RetryingClient(timeout=_TIMEOUT * 2, max_retries=0) as client:
            last_started = 0.0
            for index, text in indexed:
                wait = _GOOGLE_MIN_INTERVAL_SECONDS - (time.monotonic() - last_started)
                if wait > 0:
                    time.sleep(wait)
                last_started = time.monotonic()
                results[index] = google_translate(text, target, client=client)
        return results

    # AI 供应商是有正式配额的 API，保留并发与通用重试策略。
    with ai_retry.RetryingClient(timeout=_TIMEOUT * 2) as client:
        # 整批记**一条**账:一条字幕轨几百句,逐句记会把 Token 图淹掉,而用户想知道的是
        # "这次翻译花了多少"。
        with billable(db, capability="chat", operation="translate_batch") as call:
            run(lambda item: (item[0], ai_translate_with(chat_target, item[1], target, client=client, call=call)))
    return results
