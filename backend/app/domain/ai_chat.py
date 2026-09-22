"""对话补全(`/chat/completions`)的唯一实现。

以前这段抄在多个地方:翻译、发布文案、提示词优化、工作流 AI 编辑、素材分析和
工作流 LLM 节点,各自拼一次请求、各自解析一次 `choices[0]`。这些抄件不会一起演进,已经分出来
的差异:

  - **重试**:只有一半挂了 RetryingClient。同一个端点抖一下,工作流的 LLM 节点自己扛过去了,
    翻译和发布文案直接报错 —— 而设置页那句「连接断开/超时/限流时自动重试」对用户
    是一句承诺,不是一个按模块生效的开关。
  - **密钥泄漏**:只有素材分析记得脱敏。其余几处把异常原文塞进错误消息,而 httpx 的异常文本
    里带着请求头 —— API key 就这样进了任务日志和界面提示。
  - **空密钥**:只有提示词优化处理了「本地端点无鉴权」。其余几处发 `Bearer `(尾随空格),
    httpx 判定为非法头值直接抛,而报错内容和鉴权毫无关系,查半天才想到是密钥没填。
  - **用量**:一条都不记。首页那张 Token 图和成本统计因此是漏的,且漏得没有提示。
    (记账本身不在这里 —— 它归 domain/usage.billable;这里只负责把 token 报进去。)

温度、超时、是否强制 JSON 这些**确实**该因用途而异,所以它们是参数;上面那四件不该。

## 为什么入参是 ChatTarget 而不是 ProviderProfile

因为有调用点跑在工作线程上(例如字幕整批翻译)。SQLAlchemy 的 Session 属于单个
线程,在工作线程上碰 ORM 对象的属性可能触发懒加载,那是一场竞态。翻译模块早就想明白了这点
并自己定义了一个脱离 Session 的 provider 结构;这里把那个做法推广开 —— **在有 Session 的线程
上 resolve 一次,之后只带着纯数据走**。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale, t
from app.domain.provider_credentials import ResolvedConnection
from app.core import http_retry as ai_retry
from app.domain import provider_models
from app.domain.usage import BillableCall

logger = logging.getLogger(__name__)

#: 默认超时。本地模型冷启动可能很慢,所以调用方普遍会往上调而不是往下调。
DEFAULT_TIMEOUT_SECONDS = 60.0


#: 降级发生时叫一下:`(从哪一档, 到哪一档, 为什么)`。
DowngradeReporter = Callable[[str, str, str], None]


def _report_downgrade(
    reporter: DowngradeReporter | None,
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str,
) -> None:
    """降级说出来。报告器自己抛异常不该把这一轮弄失败 —— 它只是旁路的诊断。"""
    if reporter is None:
        return
    from_tier, to_tier = response_format_tier(before), response_format_tier(after)
    if from_tier == to_tier:
        return
    try:
        reporter(from_tier, to_tier, reason)
    except Exception:  # noqa: BLE001 — 诊断通道不该反过来弄坏被诊断的那件事
        logger.warning("降级回调抛了异常,已忽略", exc_info=True)


class AiChatError(RuntimeError):
    """一次对话补全失败。消息已脱敏,可以直接展示给用户或写进任务日志。"""


@dataclass(frozen=True)
class ChatTarget:
    """一次对话调用需要知道的全部信息,**不含任何 ORM 对象** —— 可以安全地跨线程传递。"""

    base_url: str
    api_key: str = field(repr=False)
    model: str
    profile_id: str = ""
    vendor: str = ""
    name: str = ""
    execution_surface: Literal["direct", "gateway"] = "direct"
    gateway_provider: dict[str, Any] | None = field(default=None, repr=False)
    gateway_api_base: str = ""
    gateway_token: str = field(default="", repr=False)
    #: 这个端点能不能把 JSON Schema 当成**生成时的硬约束**。`None` = 不知道(照发,被拒了再降级)。
    #: 见 domain/structured_output。
    structured_output: bool | None = None
    #: 这一轮最多能出多少 token —— `model_limits.resolve` 合并出来的那个数
    #: (用户在模型设置里填的 → 供应商目录 → 内置表 → 回退)。
    #:
    #: **在此之前这条通道一个字节都发不出去。** 用户在「模型设置」里填「最大输出 Token」,
    #: 那个值只进两个地方:拼给 pi 的 payload,和设置页自己回显的那几行。而设置页那一行
    #: 写的是「运行时真正会用的数」—— 这句话在智能体那条路上是真的,在直连这八个调用点上
    #: 是假的,而界面上两者长得一模一样。
    max_output_tokens: int | None = None


def target_for(
    db: Session,
    profile: ResolvedConnection,
    *,
    model: str = "",
    surface: Literal["direct", "automation"] = "direct",
) -> ChatTarget:
    """在**持有 Session 的线程上**把一条连接解析成可跨线程的调用目标。

    model 留空时按这条连接的 chat 能力解析;解析不出来当场报错,而不是发一个空 model 让供应商
    回一句看不懂的 400。
    """
    resolved = model or provider_models.model_id_for(db, profile, "chat")
    if not resolved:
        raise AiChatError(t("aiChat_noChatModel", get_current_locale(), name=profile.name))
    if profile.auth_type == "oauth" and surface == "automation":
        if not profile.oauth_credential or not profile.owner_user_id:
            raise AiChatError(t("aiChat_oauthRequired", get_current_locale(), name=profile.name))
        from app.core.config import settings
        from app.core.security import mint_service_session
        from app.domain.provider_runtime import sidecar_provider

        return ChatTarget(
            base_url="",
            api_key="",
            model=resolved,
            profile_id=profile.id,
            vendor=profile.vendor or "",
            name=profile.name,
            execution_surface="gateway",
            max_output_tokens=_max_output_tokens(db, profile, resolved),
            gateway_provider=sidecar_provider(db, profile, resolved),
            gateway_api_base=f"http://{settings.backend_host}:{settings.backend_port}",
            # 短期服务令牌只给 sidecar 回写**这个人自己的** OAuth 刷新结果；不发给浏览器。
            gateway_token=mint_service_session(db, profile.owner_user_id),
            structured_output=_structured_output(db, profile, resolved),
        )
    #: **地址空着就在这儿说清楚。** 不拦的话拼出来的是 "/chat/completions",httpx 抛的是
    #: 「Request URL is missing an 'http://' or 'https://' protocol」—— 用户看到这句,
    #: 完全想不到要去设置里补一个服务地址。而且这是所有调用方共用的一层,拦在这里全都受益。
    if not (profile.base_url or "").strip():
        # 订阅授权(Kimi Code 这类 OAuth 连接)**没有服务地址可填** —— 端点、模型目录都在 pi 的
        # Provider 定义里,后端只递身份(host.resolve_chat_provider)。指人去设置里填地址是把他
        # 引向一条走不通的修复路径:填了 base_url 也没有 api_key,依然调不通。
        if profile.auth_type == "oauth":
            raise AiChatError(t("aiChat_agentOnly", get_current_locale(), name=profile.name))
        raise AiChatError(t("aiChat_noBaseUrl", get_current_locale(), name=profile.name))
    return ChatTarget(
        base_url=profile.base_url,
        api_key=profile.api_key or "",
        model=resolved,
        profile_id=profile.id,
        vendor=profile.vendor or "",
        name=profile.name,
        structured_output=_structured_output(db, profile, resolved),
        max_output_tokens=_max_output_tokens(db, profile, resolved),
    )


def _max_output_tokens(db: Session, profile: ResolvedConnection, model: str) -> int | None:
    """这一轮的输出上限 —— 和智能体那条路走**同一个** `model_limits.resolve`。

    `resolve` 的文档写着「唯一的合并处」,那句话是成立的:问题从来不是有第二处合并,
    而是**有一条通道根本不经过它**。这个函数就是让它经过。
    """
    from app.domain import model_limits, provider_models
    from app.ai.model_catalog import cached_model

    row = provider_models.get_model(db, profile.id, model)
    catalog = cached_model(profile.base_url or "", profile.api_key or "", model)
    return model_limits.resolve(
        model_id=model,
        base_url=profile.base_url or "",
        vendor=profile.vendor or "",
        override_window=getattr(row, "context_window", None),
        override_output=getattr(row, "max_output_tokens", None),
        catalog_window=catalog.context_window if catalog else None,
        catalog_output=catalog.max_output_tokens if catalog else None,
        # 用户在模型设置里勾的「推理模型」。查证不到这个模型的思考行为时,就听他的 ——
        # 中转/本地端点上挂的推理模型全靠这一格。
        reasoning=getattr(row, "reasoning", None),
    ).effective_max_output_tokens


def _structured_output(db: Session, profile: ResolvedConnection, model: str) -> bool | None:
    """这个端点支不支持 json_schema:用户在模型设置里填的优先,没填就用查证过的结论。

    取不到模型行也不算错 —— 没配置过的模型照样能用,只是没有任何覆盖。
    """
    from app.domain import provider_models, structured_output

    row = provider_models.get_model(db, profile.id, model)
    return structured_output.effective_support(
        profile.vendor or "", getattr(row, "structured_output", None)
    )


def chat(
    target: ChatTarget,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    json_object: bool = False,
    extra: dict[str, Any] | None = None,
    max_retries: int | None = None,
    client: httpx.Client | None = None,
    call: BillableCall | None = None,
    label: str = "AI 调用",
    allow_response_format_fallback: bool = False,
    on_downgrade: DowngradeReporter | None = None,
) -> str:
    """跑一次对话补全,返回助手消息的文本。

    client 给了就复用它(整批字幕共用连接,省掉每条一次 TLS 握手);此时重试由该 client 决定。
    call 给了就把 token 计量报进那次记账(见 domain/usage.billable)。
    allow_response_format_fallback 只供会在本地继续解析/校验 JSON 的调用方开启。

    on_downgrade 在**每一次降级发生时**被叫一下。降级本身是对的(不这么做就是一个用户看不懂
    的 400),坏的是它**一声不吭**:这一轮实际跑在三档中的哪一档,此前没有任何地方说得出来。
    后果不是"少一条日志" —— 调用方在本地做的那次 Schema 校验,于是在「本来就没有硬约束」和
    「有硬约束却违反了」这两种完全不同的情况下报同一句话,用户以为是模型笨,而不是那份图纸
    从来没被强制执行过。
    """
    payload: dict[str, Any] = {"model": target.model, "messages": messages, "temperature": temperature}
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    # extra 给的是这次调用**额外**要发的采样参数(top_p / seed / stop / json_schema 形式的
    # response_format 等)。工作流的 LLM 节点把这些开放给了用户,而其余调用点用不上 ——
    # 与其把十来个参数提到签名上,不如让需要的那一处显式传进来。
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in ("model", "messages")})
    # DeepSeek V4 默认开启 high thinking，而 max_tokens 同时覆盖推理与最终正文。长逐字稿的
    # 结构化任务会出现“推理耗尽预算、HTTP 200、content 为空”；这种调用的契约是最终 JSON，
    # 不是展示思考过程，所以默认关闭思考，把预算完整留给可解析结果。显式传入 thinking 时尊重调用方。
    if (
        target.vendor.strip().lower() == "deepseek"
        and isinstance(payload.get("response_format"), dict)
        and payload["response_format"].get("type") in {"json_schema", "json_object"}
    ):
        payload.setdefault("thinking", {"type": "disabled"})
    # **`setdefault`**:工作流 LLM 节点上那一格(executors/ai.py)是更具体的意图,它先说了算;
    # 没人说过时,才用模型设置里那个数 —— 而不是让供应商拿它自己的默认值(通常小得多)决定。
    if target.max_output_tokens:
        payload.setdefault("max_tokens", target.max_output_tokens)
    payload["messages"] = _satisfy_json_mode(payload.get("messages") or [], payload.get("response_format"))
    if target.execution_surface == "gateway":
        return _chat_gateway(
            target,
            payload,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
            call=call,
            label=label,
            allow_response_format_fallback=allow_response_format_fallback,
            on_downgrade=on_downgrade,
        )
    url = f"{target.base_url.rstrip('/')}/chat/completions"
    headers = ai_retry.auth_headers(target.api_key)
    if call is not None:
        call.describe(provider=target.vendor, model=target.model, provider_profile_id=target.profile_id or None)

    try:
        while True:
            if client is not None:
                response = client.post(url, headers=headers, json=payload, timeout=timeout)
            else:
                response = ai_retry.post(url, headers=headers, json=payload, timeout=timeout, max_retries=max_retries)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                fallback = (
                    _response_format_fallback_payload(payload, response)
                    if allow_response_format_fallback
                    else None
                )
                if fallback is None:
                    raise
                _report_downgrade(on_downgrade, payload, fallback, "供应商明确拒绝了这一档")
                payload = fallback
                continue
            body = response.json()
            # 空 content 也可能已经消耗了推理 token；每个 200 尝试都累计到同一条账，而不是
            # 只记最终可见答案。BillableCall.meter 明确定义为可多次累加。
            if call is not None:
                call.meter_openai_tokens(body.get("usage"))
            raw_content = body["choices"][0]["message"]["content"]
            content = "" if raw_content is None else str(raw_content)
            if allow_response_format_fallback and not content.strip():
                fallback = _downgrade_response_format_payload(payload)
                if fallback is not None:
                    _report_downgrade(on_downgrade, payload, fallback, "这一档下返回了空正文")
                    payload = fallback
                    continue
            break
    except httpx.HTTPStatusError as exc:
        raise AiChatError(_sanitize(f"{label}失败:{_provider_detail(exc.response, target.model)}", target.api_key)) from exc
    except httpx.RequestError as exc:
        # 带上「已重试 N 次」:同样是连不上,试过四次和只试了一次对用户是两件事 ——
        # 前者该去查网络或供应商,后者可能只是手滑填错了地址。
        tried = max_retries if max_retries is not None else ai_retry.current_max_retries()
        suffix = f",已重试 {tried} 次仍失败" if client is None and tried > 0 else ""
        raise AiChatError(_sanitize(f"{label}失败(网络/连接{suffix}):{exc}", target.api_key)) from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AiChatError(_sanitize(f"{label}失败:供应商返回的结构不认识({exc})", target.api_key)) from exc

    return content


_GATEWAY_IMAGE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$", re.DOTALL)
_GATEWAY_MAX_IMAGES = 8
_GATEWAY_MAX_ENCODED_BYTES = 8 * 1024 * 1024


def _gateway_prompt(messages: list[dict[str, Any]]) -> tuple[str, str, list[dict[str, str]]]:
    """Normalize OpenAI-shaped messages into the sidecar's stateless completion Interface."""
    systems: list[str] = []
    turns: list[tuple[str, str]] = []
    images: list[dict[str, str]] = []
    encoded = 0
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
                elif part.get("type") == "image_url" and len(images) < _GATEWAY_MAX_IMAGES:
                    image_url = part.get("image_url")
                    url = image_url.get("url") if isinstance(image_url, dict) else image_url
                    match = _GATEWAY_IMAGE.match(str(url or ""))
                    if match and encoded + len(match.group(2)) <= _GATEWAY_MAX_ENCODED_BYTES:
                        encoded += len(match.group(2))
                        images.append({"mimeType": match.group(1), "data": match.group(2)})
        text = "\n".join(one for one in texts if one).strip()
        if role == "system":
            if text:
                systems.append(text)
        elif text:
            turns.append((role, text))
    if len(turns) == 1 and turns[0][0] == "user":
        prompt = turns[0][1]
    else:
        labels = {"user": "用户", "assistant": "助手"}
        prompt = "\n\n".join(f"【{labels.get(role, role)}】\n{text}" for role, text in turns)
    return "\n\n".join(systems), prompt, images


def _chat_gateway(
    target: ChatTarget,
    payload: dict[str, Any],
    *,
    timeout: float,
    max_retries: int | None,
    client: httpx.Client | None,
    call: BillableCall | None,
    label: str,
    allow_response_format_fallback: bool = False,
    on_downgrade: DowngradeReporter | None = None,
) -> str:
    """订阅授权那条路。**降级链和直连那条是同一条。**

    此前这里整个没有降级:`chat()` 在任何 fallback 逻辑之前就 return 到这儿,
    连 `allow_response_format_fallback` 都没往下传。后果是同一个工作流 LLM 节点、同一份配置,
    连 API Key 连接会优雅降级,连订阅授权就是一个硬 400 —— **而界面上这两种连接长得一样**。
    静默忽略一个「我已经允许你降级」的承诺,是最坏的一种处理。
    """
    if client is not None:
        raise AiChatError(f"{label}失败:OAuth Gateway 不支持复用调用方 HTTP 连接")
    from app.ai.sidecar.adapters import AdapterError, gateway_complete

    # **在发请求之前说清这条账是谁的**,和直连那条对齐。原先放在成功之后,于是调用失败时
    # 那条账没有 provider / model,会落进 `UsageSummary.unpriced` 里那堆"没能定价"的记录 ——
    # 而那一栏存在的意义恰恰是告诉用户"你少配了哪条价格规则",混进根本不该在那儿的行之后,
    # 它就不再说得清任何事。
    if call is not None:
        call.describe(provider=target.vendor, model=target.model, provider_profile_id=target.profile_id or None)

    try:
        while True:
            system_prompt, prompt, images = _gateway_prompt(payload.get("messages") or [])
            sampling = {
                key: value
                for key, value in payload.items()
                if key not in {"model", "messages", "temperature", "max_tokens", "max_completion_tokens"}
            }
            options: dict[str, Any] = {
                "temperature": payload.get("temperature"),
                "maxRetries": max_retries if max_retries is not None else ai_retry.current_max_retries(),
                "timeoutMs": max(1, int(timeout * 1000)),
            }
            max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens")
            if max_tokens is not None:
                options["maxTokens"] = int(max_tokens)
            if sampling:
                options["samplingParams"] = sampling
            try:
                result = gateway_complete(
                    system_prompt=system_prompt,
                    prompt=prompt,
                    images=images,
                    provider=target.gateway_provider or {},
                    model=target.model,
                    api_base=target.gateway_api_base,
                    token=target.gateway_token,
                    options=options,
                    timeout=timeout,
                )
            except AdapterError as exc:
                fallback = (
                    _downgrade_response_format_payload(payload)
                    if allow_response_format_fallback and _rejects_response_format(str(exc))
                    else None
                )
                if fallback is None:
                    raise AiChatError(_sanitize(f"{label}失败:{exc}", target.gateway_token)) from exc
                _report_downgrade(on_downgrade, payload, fallback, "供应商明确拒绝了这一档")
                payload = fallback
                continue
            if allow_response_format_fallback and not (result.text or "").strip():
                fallback = _downgrade_response_format_payload(payload)
                if fallback is not None:
                    _report_downgrade(on_downgrade, payload, fallback, "这一档下返回了空正文")
                    payload = fallback
                    continue
            break
    finally:
        if target.gateway_token:
            from app.core.db import SessionLocal
            from app.core.security import revoke_session

            with SessionLocal() as db:
                revoke_session(db, target.gateway_token)
                db.commit()
    if call is not None:
        usage = result.usage or {}
        call.meter(
            input_tokens=int(usage.get("input") or usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output") or usage.get("output_tokens") or 0),
            raw=usage,
        )
    return result.text


#: OpenAI 兼容接口的硬性要求:用 `response_format: json_object` 时,**提示词里必须出现
#: "json" 这个词**,否则直接 400。deepseek、月之暗面等跟着 OpenAI 的实现都照做。
_JSON_MODE_HINT = "Respond with a single valid JSON object."
#: 「这条消息里已经带着 JSON 契约了」。降级路径据此不再另贴一份 —— 工作流的 LLM 节点在发请求
#: 之前就会把 Schema 贴进去(见 workflows/executors/ai._schema_for_prompt),两边各贴一次的话,
#: 同一份 Schema 会在一次请求里出现两遍,白烧几千 token。
JSON_CONTRACT_MARKER = "Mosael response-format compatibility contract"
_JSON_FALLBACK_MARKER = JSON_CONTRACT_MARKER


def _satisfy_json_mode(messages: list[dict[str, Any]], response_format: Any) -> list[dict[str, Any]]:
    """JSON 模式下,保证提示词里出现 "json"。

    这条约束是接口方定的,不是模型的偏好 —— 不满足时拿到的是一个 400,而不是一个凑合的
    回答。此前四个调用点各自拼提示词,谁都没管它:工作流的 LLM 节点把 response_format
    开放给了用户,而用户的提示词里当然不会无缘无故提到 json,于是选了 JSON 模式就 400。

    **只在缺的时候补一句**,而且补在 system 那一侧:改用户写的那段话会改变他的意图,
    而这一句说的正是 JSON 模式本来就要求的事,不增加任何新约束。
    """
    if not isinstance(response_format, dict) or response_format.get("type") not in ("json_object", "json_schema"):
        return messages
    if any("json" in str(one.get("content") or "").lower() for one in messages):
        return messages
    return [{"role": "system", "content": _JSON_MODE_HINT}, *messages]


#: 结构化输出的三档,从强到弱。**降级就是在这条链上往右走一步。**
RESPONSE_FORMAT_TIERS = ("json_schema", "json_object", "text")


def response_format_tier(payload: dict[str, Any]) -> str:
    """这份 payload 此刻在哪一档。没有 response_format 就是纯文本。"""
    current = payload.get("response_format")
    if isinstance(current, dict) and current.get("type") in {"json_schema", "json_object"}:
        return str(current["type"])
    return "text"


def _rejects_response_format(detail: str) -> bool:
    """这段错误文本说的是「我不支持 response_format」吗。

    两条通道(直连 HTTP / OAuth 网关)都要问这个问题,所以收敛成一处 —— 原先只有直连那边有,
    于是同一个 LLM 节点连 API Key 时优雅降级、连订阅授权时是一个硬 400。
    """
    lowered = detail.lower()
    if "response_format" not in lowered:
        return False
    return any(
        phrase in lowered
        for phrase in ("unavailable", "not supported", "unsupported", "must be one of")
    )


def _response_format_fallback_payload(payload: dict[str, Any], response: httpx.Response) -> dict[str, Any] | None:
    """供应商明确不支持结构化输出时，逐级降级而不丢失 JSON 契约。

    json_schema → json_object → 纯文本。只处理可识别的能力错误；Schema 写错、鉴权失败等普通
    400 仍原样抛出。调用方必须继续解析（并在有 Schema 时本地校验）结果，才可开启此策略。
    """
    current = payload.get("response_format")
    if not isinstance(current, dict) or current.get("type") not in {"json_schema", "json_object"}:
        return None
    if response.status_code != 400:
        return None
    detail = response.text.lower()
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail += " " + str(error.get("message") or "").lower()
        elif error:
            detail += " " + str(error).lower()
    if not _rejects_response_format(detail):
        return None

    return _downgrade_response_format_payload(payload)


def _downgrade_response_format_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """把结构化输出逐级降级，并在提示词中保留原始 JSON 契约。"""
    current = payload.get("response_format")
    if not isinstance(current, dict) or current.get("type") not in {"json_schema", "json_object"}:
        return None

    messages = list(payload.get("messages") or [])
    if not any(_JSON_FALLBACK_MARKER in str(one.get("content") or "") for one in messages):
        json_schema = current.get("json_schema") if current.get("type") == "json_schema" else None
        schema = json_schema.get("schema") if isinstance(json_schema, dict) else None
        contract = (
            "The provider cannot enforce response_format. Return only one valid JSON object that "
            "matches this JSON Schema exactly; do not use Markdown fences:\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            if isinstance(schema, dict)
            else "The provider cannot enforce response_format. Return only one valid JSON object; "
            "do not use Markdown fences or explanatory text."
        )
        messages = [{"role": "system", "content": f"{_JSON_FALLBACK_MARKER}.\n{contract}"}, *messages]

    fallback = dict(payload)
    if current.get("type") == "json_schema":
        fallback["response_format"] = {"type": "json_object"}
        fallback["messages"] = _satisfy_json_mode(messages, fallback["response_format"])
    else:
        fallback.pop("response_format", None)
        fallback["messages"] = messages
    return fallback


def _sanitize(message: str, credential: str | None) -> str:
    """错误消息会进任务日志和界面提示,而 httpx 的异常文本里带着请求头。"""
    text = message
    if credential:
        text = text.replace(credential, "***")
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", text)
    text = re.sub(r"(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._-]+", r"\1***", text, flags=re.IGNORECASE)
    return text[:500]


def _provider_detail(response: httpx.Response, model: str) -> str:
    """把供应商的 4xx/5xx 响应体提炼成人看得懂的一行 —— 否则只剩个裸状态码,查不出根因。"""
    detail = response.text.strip()
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            detail = str(err["message"])
        elif isinstance(err, str) and err:
            detail = err
    return f"{response.status_code} {detail[:300]}（模型 {model}）"
