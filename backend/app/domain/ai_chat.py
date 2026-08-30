"""对话补全(`/chat/completions`)的唯一实现。

以前这段抄了八份:翻译、发布文案、知识库图谱抽取、提示词优化、工作流 AI 编辑、素材分析、
工作流 LLM 节点,各自拼一次请求、各自解析一次 `choices[0]`。八份抄件不会一起演进,已经分出来
的差异:

  - **重试**:只有一半挂了 RetryingClient。同一个端点抖一下,工作流的 LLM 节点自己扛过去了,
    翻译、发布文案、图谱抽取直接报错 —— 而设置页那句「连接断开/超时/限流时自动重试」对用户
    是一句承诺,不是一个按模块生效的开关。
  - **密钥泄漏**:只有素材分析记得脱敏。其余几处把异常原文塞进错误消息,而 httpx 的异常文本
    里带着请求头 —— API key 就这样进了任务日志和界面提示。
  - **空密钥**:只有提示词优化处理了「本地端点无鉴权」。其余几处发 `Bearer `(尾随空格),
    httpx 判定为非法头值直接抛,而报错内容和鉴权毫无关系,查半天才想到是密钥没填。
  - **用量**:一条都不记。首页那张 Token 图和成本统计因此是漏的,且漏得没有提示。
    (记账本身不在这里 —— 它归 domain/usage.billable;这里只负责把 token 报进去。)

温度、超时、是否强制 JSON 这些**确实**该因用途而异,所以它们是参数;上面那四件不该。

## 为什么入参是 ChatTarget 而不是 ProviderProfile

因为有调用点跑在工作线程上(字幕整批翻译、知识库图谱抽取)。SQLAlchemy 的 Session 属于单个
线程,在工作线程上碰 ORM 对象的属性可能触发懒加载,那是一场竞态。翻译模块早就想明白了这点
并自己定义了一个脱离 Session 的 provider 结构;这里把那个做法推广开 —— **在有 Session 的线程
上 resolve 一次,之后只带着纯数据走**。

顺带修掉一个已有的矛盾:知识库的 `_extract_with` 文档写着「no Session, so it is safe to run on
a worker thread」,函数体里却调了 `object_session(profile)` 去解析模型名。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale, t
from app.domain.provider_credentials import ResolvedProvider
from app.core import http_retry as ai_retry
from app.domain import provider_models
from app.domain.usage import BillableCall

logger = logging.getLogger(__name__)

#: 默认超时。本地模型冷启动可能很慢,所以调用方普遍会往上调而不是往下调。
DEFAULT_TIMEOUT_SECONDS = 60.0


class AiChatError(RuntimeError):
    """一次对话补全失败。消息已脱敏,可以直接展示给用户或写进任务日志。"""


@dataclass(frozen=True)
class ChatTarget:
    """一次对话调用需要知道的全部信息,**不含任何 ORM 对象** —— 可以安全地跨线程传递。"""

    base_url: str
    api_key: str
    model: str
    profile_id: str = ""
    vendor: str = ""
    name: str = ""


def target_for(db: Session, profile: ResolvedProvider, *, model: str = "") -> ChatTarget:
    """在**持有 Session 的线程上**把一条连接解析成可跨线程的调用目标。

    model 留空时按这条连接的 chat 能力解析;解析不出来当场报错,而不是发一个空 model 让供应商
    回一句看不懂的 400。
    """
    resolved = model or provider_models.model_id_for(db, profile, "chat")
    if not resolved:
        raise AiChatError(t("aiChat_noChatModel", get_current_locale(), name=profile.name))
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
) -> str:
    """跑一次对话补全,返回助手消息的文本。

    client 给了就复用它(整批字幕共用连接,省掉每条一次 TLS 握手);此时重试由该 client 决定。
    call 给了就把 token 计量报进那次记账(见 domain/usage.billable)。
    """
    payload: dict[str, Any] = {"model": target.model, "messages": messages, "temperature": temperature}
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    # extra 给的是这次调用**额外**要发的采样参数(top_p / seed / stop / json_schema 形式的
    # response_format 等)。工作流的 LLM 节点把这些开放给了用户,而其余调用点用不上 ——
    # 与其把十来个参数提到签名上,不如让需要的那一处显式传进来。
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in ("model", "messages")})
    payload["messages"] = _satisfy_json_mode(payload.get("messages") or [], payload.get("response_format"))
    url = f"{target.base_url.rstrip('/')}/chat/completions"
    headers = _auth_headers(target.api_key)

    try:
        if client is not None:
            response = client.post(url, headers=headers, json=payload, timeout=timeout)
        else:
            response = ai_retry.post(url, headers=headers, json=payload, timeout=timeout, max_retries=max_retries)
        response.raise_for_status()
        body = response.json()
        content = str(body["choices"][0]["message"]["content"])
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

    if call is not None:
        call.describe(provider=target.vendor, model=target.model, provider_profile_id=target.profile_id or None)
        call.meter_openai_tokens(body.get("usage"))
    return content


#: OpenAI 兼容接口的硬性要求:用 `response_format: json_object` 时,**提示词里必须出现
#: "json" 这个词**,否则直接 400。deepseek、月之暗面等跟着 OpenAI 的实现都照做。
_JSON_MODE_HINT = "Respond with a single valid JSON object."


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


def _auth_headers(api_key: str) -> dict[str, str]:
    """空密钥(本地 / 无鉴权端点)不发 Authorization —— 否则 'Bearer ' 是非法头值,httpx 直接抛。"""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


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


