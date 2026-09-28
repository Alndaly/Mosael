"""翻译是一项**宿主能力**(ADR 0032 第三步),两个内置提供方加上插件:

- `builtin:google`:Google 免费(非官方)端点 —— 不要密钥,字幕过一遍够用,但逐句直译、不看上下文;没定默认时用它;
- `builtin:chat`:用户连接上的对话模型 —— 慢、要花钱,但读的是整句。可以带「哪条连接 / 哪个模型」两个参数
  (工作流节点、画板里的那两格),不带就用第一条可用的对话连接;
- 认领 `translation` 的插件连接:协议是一批句子进、同样条数的译文出(见 translate_many)。

挑哪一家走能力表那一份挑法(`capabilities.pick`),所以工作流翻译节点、剪辑页字幕翻译、配音流水线拿到的是同一组
选择。此前是 `engine: google | ai` 写死在节点、接口的正则和字幕面板里,插件插不进来。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time
from typing import Literal

import httpx

from app.core.i18n import LocalizedError
from app.domain import capabilities
from app.domain.capabilities import Builtin, Capability, CapabilityUnavailable, Provider
from app.domain.plugins.manifest import TRANSLATION
from app.core.usage_scope import run_in_scope
from app.domain.ai_chat import AiChatError, ChatTarget, chat, target_for
from app.core import http_retry
from app.domain.usage import BillableCall, billable, once

#: 调用方在哪条执行通道上(见 ai_chat.target_for 的 surface)。
ChatSurface = Literal["direct", "automation"]

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


class TranslateError(LocalizedError, RuntimeError):
    """带 key 的错误。

    领域里不拼句子 —— 存 key + 参数,出口(路由)按请求方语言翻。上游 AiChatError 用
    `TranslateError.relay` 转述,**带着它的 key 和参数** —— 此前是 `TranslateError(str(exc))`,
    上游那句话在转述那一刻就翻成了缺省语言的字。
    """


class TranslateProviderUnavailable(CapabilityUnavailable, TranslateError):
    """挑不出能用的翻译实现。仍是 TranslateError —— 翻译的调用方照样接得住。"""


GOOGLE = "builtin:google"
CHAT = "builtin:chat"

CAPABILITY = Capability(
    name=TRANSLATION,
    label_key="capability_translation",
    description_key="capability_translation_desc",
    error=TranslateProviderUnavailable,
    unknown_key="translateErr_unknownProvider",
    incomplete_key="translateErr_providerNotReady",
    builtins=(
        Builtin(id=GOOGLE, name_key="translateEngine_google"),
        #: 要花钱,不替他自动挑;定成默认或点名才用。
        Builtin(id=CHAT, name_key="translateEngine_chat", automatic=False),
    ),
    #: 文字交给插件(多半是云端、多半计费)必须是他自己定过的。
    auto_single=False,
)


def register_uses() -> None:
    """宿主界面上用到翻译的入口(ADR 0032 §4)。工作流节点由注册表现扫。"""
    from app.core.i18n import fragment
    from app.domain.capabilities import Use, register_use

    register_use(Use(TRANSLATION, "app", fragment("capUse_subtitleTranslate")))


def language_label(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def resolve_ai_chat_target(
    db, profile_id: str | None, user_id: str | None, model: str = "", *, surface: ChatSurface = "direct"
) -> ChatTarget:
    """`surface` 是调用方所在的执行通道(见 ai_chat.target_for):工作流节点是 automation ——
    订阅授权的连接经网关可用,和 LLM 节点一样;界面上的翻译接口是 direct。"""
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
        return target_for(db, resolved, model=model, surface=surface)
    except AiChatError as exc:
        raise TranslateError.relay(exc) from exc


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
        raise TranslateError.relay(exc) from exc


def translate(
    db,
    text: str,
    target: str,
    *,
    user_id: str | None,
    engine: str = "",
    profile_id: str | None = None,
    model: str = "",
    surface: ChatSurface = "direct",
) -> str:
    """翻一句。`engine` 是提供方 id,空 = 按这个人的默认;`profile_id` / `model` 只对 `builtin:chat` 有意义。

    **AI 那条就是只有一句的批量。** 此前它另有一份 `ai_translate`:解析目标、调 chat —— 唯独
    没带记账,于是工作流翻译节点的每一次 AI 调用在账上都是隐身的,而批量那条一直记着。
    同一件事两份实现,漏的那一份不会报错。现在记账、连接解析只在 translate_many 里。
    """
    return translate_many(
        db, [text], target, user_id=user_id, engine=engine, profile_id=profile_id, model=model, surface=surface
    )[0]


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
    http = client or http_retry.RetryingClient(timeout=_TIMEOUT)
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
    engine: str = "",
    profile_id: str | None = None,
    model: str = "",
    surface: ChatSurface = "direct",
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
    provider = capabilities.pick(db, user_id, CAPABILITY, engine or None)
    indexed = [(i, text) for i, text in enumerate(texts) if text.strip()]
    results = [""] * len(texts)
    if not indexed:
        return results
    if not provider.builtin:
        for (index, _text), translated in zip(indexed, _plugin_translate(db, provider, [text for _i, text in indexed], target),
                                              strict=True):
            results[index] = translated
        return results
    chat_target = resolve_ai_chat_target(db, profile_id, user_id, model, surface=surface) if provider.id == CHAT else None

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
        with http_retry.RetryingClient(timeout=_TIMEOUT * 2, max_retries=0) as client:
            last_started = 0.0
            for index, text in indexed:
                wait = _GOOGLE_MIN_INTERVAL_SECONDS - (time.monotonic() - last_started)
                if wait > 0:
                    time.sleep(wait)
                last_started = time.monotonic()
                results[index] = google_translate(text, target, client=client)
        return results

    # AI 供应商是有正式配额的 API，保留并发与通用重试策略。
    # 共享连接只对直连有意义:订阅授权走网关(sidecar),没有调用方 HTTP 连接可复用。
    with http_retry.RetryingClient(timeout=_TIMEOUT * 2) as client:
        shared = None if chat_target.execution_surface == "gateway" else client
        # 整批记**一条**账:一条字幕轨几百句,逐句记会把 Token 图淹掉,而用户想知道的是
        # "这次翻译花了多少"。
        with billable(db, capability="chat", operation="translate_batch",
                      idempotency_key=once("translate_batch")) as call:
            run(lambda item: (item[0], ai_translate_with(chat_target, item[1], target, client=shared, call=call)))
    return results


def _plugin_translate(db, provider: Provider, texts: list[str], target: str) -> list[str]:
    """认领 `translation` 的插件连接:入 `{"texts": [...], "target": 语言代码, "source": "auto"}`,
    出 `{"texts": [...]}`,条数和顺序都得对得上 —— 对不上整批作废,不把错位的译文写进字幕轨。"""
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.runtime import PluginRuntimeError
    from app.domain.plugins.tools import invoke_host

    translated: list[str] = []

    def collect(output: dict, _scratch) -> dict:
        got = output.get("texts")
        if not isinstance(got, list) or len(got) != len(texts) or not all(isinstance(one, str) for one in got):
            raise TranslateError("translateErr_pluginBadOutput", plugin=provider.name, expected=len(texts),
                                 got=len(got) if isinstance(got, list) else 0)
        translated.extend(got)
        return {"texts": len(got)}

    try:
        invoke_host(db, provider.id, TRANSLATION, {"texts": texts, "target": target, "source": "auto"}, collect=collect)
    except (PluginDomainError, PluginRuntimeError) as exc:
        raise TranslateError("translateErr_pluginFailed", plugin=provider.name, detail=str(exc)[:500]) from exc
    return translated
