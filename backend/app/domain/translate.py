"""Text translation with two backends:

- **google**: Google's free (unofficial) translate endpoint — no API key, good enough for a
  quick subtitle pass, but it translates cue by cue with no context.
- **ai**: an LLM through the workspace's provider profile — slower and billed, but it reads
  the sentence rather than the words. Same call shape, so a caller only picks `engine`.

Both live here so every caller (workflow translate node, editor subtitle panel) gets the same
two choices from one place. Kept dependency-light (httpx only).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from app.core.usage_scope import run_in_scope
from app.domain.ai_chat import AiChatError, ChatTarget, chat, target_for
from app.domain import ai_retry
from app.domain.usage import BillableCall, billable

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 30
# Translating a subtitle track means one independent network round-trip per cue, so they run
# concurrently rather than one after another. Bounded, not unbounded: Google's free endpoint
# rate-limits a burst, and a 200-cue track would otherwise open 200 sockets at once.
_MAX_PARALLEL = 8

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


def resolve_ai_provider(db, profile_id: str | None, user_id: str | None) -> ChatTarget:
    from sqlalchemy import select

    from app.db.models import ProviderProfile
    from app.domain import provider_credentials

    profile = None
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        profile = db.scalars(
            select(ProviderProfile).where(ProviderProfile.enabled.is_(True)).order_by(ProviderProfile.created_at)
        ).first()
    if profile is None or not profile.enabled:
        raise TranslateError("translateErr_noProvider")
    resolved = provider_credentials.resolve(db, profile, user_id)
    if resolved is None:
        raise TranslateError("translateErr_noCredential", name=profile.name)
    try:
        return target_for(db, resolved)
    except AiChatError as exc:
        raise TranslateError(str(exc)) from exc


def ai_translate(db, text: str, target: str, profile_id: str | None, user_id: str | None) -> str:
    """Translate via an enabled AI provider (LLM). Reused by the workflow node + the API."""
    if not text.strip():
        return ""
    return ai_translate_with(resolve_ai_provider(db, profile_id, user_id), text, target)


def ai_translate_with(
    provider: ChatTarget,
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
            provider,
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout=_TIMEOUT * 2,
            client=client,
            call=call,
            label="AI 翻译",
        ).strip()
    except AiChatError as exc:
        raise TranslateError(str(exc)) from exc


def translate(db, text: str, target: str, *, user_id: str | None, engine: str = "google", profile_id: str | None = None) -> str:
    """Dispatch to the requested engine."""
    if engine == "ai":
        return ai_translate(db, text, target, profile_id, user_id)
    return google_translate(text, target)


def google_translate(text: str, target: str, source: str = "auto", client: httpx.Client | None = None) -> str:
    """Free Google translate. Returns the translation, or "" for empty input."""
    if not text.strip():
        return ""
    try:
        response = (client or httpx).get(
            _GOOGLE_URL,
            params={"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TranslateError(f"Google 翻译失败: {exc}") from exc
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
) -> list[str]:
    """Translate a batch, running the round-trips concurrently.

    Each cue is an independent network call, so a subtitle track used to cost
    len(texts) × latency — about ten seconds for a typical track. They now overlap.

    Two things are deliberately done before the pool starts: the provider is read out of the DB
    (a Session is single-threaded), and one httpx.Client is created so the batch shares
    connections instead of repeating the TLS handshake per cue.
    """
    if not texts:
        return []
    provider = resolve_ai_provider(db, profile_id, user_id) if engine == "ai" else None
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

    # 共享 client 用 RetryingClient 而不是裸 httpx.Client:共享连接是为了省掉每条字幕一次 TLS
    # 握手,但不该因此丢掉重试 —— 设置页那句「连接断开/超时/限流时自动重试」管的是所有 AI 调用。
    # 经模块引用而不是 from-import:全项目只有 ai_retry.RetryingClient 一个打桩点,
    # 直接 import 进来会让它变成第二个,测试就得两处都打。
    with ai_retry.RetryingClient(timeout=_TIMEOUT * 2) as client:
        if provider is None:  # google:免费端点,不产生供应商用量,不开记账
            run(lambda item: (item[0], google_translate(item[1], target, client=client)))
            return results
        # 整批记**一条**账:一条字幕轨几百句,逐句记会把 Token 图淹掉,而用户想知道的是
        # "这次翻译花了多少"。
        with billable(db, capability="chat", operation="translate_batch") as call:
            run(lambda item: (item[0], ai_translate_with(provider, item[1], target, client=client, call=call)))
    return results
