"""供应商是不是活着,以及打过去要多久。

**为什么值得单独做**:配置错了和服务没起,在界面上此前是同一种表现 —— 什么都没有,直到
真去生成一次才在任务失败里看到一句 502。本地类端点(Ollama / LM Studio)尤其如此:
它们最常见的故障就是"忘了启动",而这件事一秒钟就能测出来。

**探针路径由 ProviderDefinition 声明**,不在这里按名字写死一张表 ——
那种表和 providers.py 里的预设一定会漂移。没有声明的走 OpenAI 兼容的 `/models`,那是这些
端点里唯一算得上通用的只读入口。

**订阅计划(OAuth)不探**:它们没有我们持有的 base_url,端点在 pi 的 Provider 定义里;
真要探就得替每一家再抄一遍地址。它们的"通不通"已经由授权状态和额度查询回答了,这里返回
supported=False,界面据此不显示这一列,而不是显示一个假的"离线"。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.core.i18n import tr
from app.ai.model_catalog import catalog_headers
from app.domain.providers.credentials import ResolvedConnection
from app.core import outbound_guard
from app.core.http_retry import RetryingClient
from app.domain.providers.presets import catalog_protocol, provider_definition

#: 探活要快。这不是业务请求 —— 慢到几秒的端点,用户想知道的也正是"它慢"。
PROBE_TIMEOUT_SECONDS = 6

#: 没有声明时的默认探针:OpenAI 兼容端点通用的只读入口。
DEFAULT_HEALTH_PATH = "/models"


@dataclass(frozen=True)
class HealthResult:
    #: False = 这类档案没法探(订阅计划)。界面据此整列不显示。
    supported: bool
    online: bool = False
    latency_ms: int | None = None
    #: 失败原因,已裁短。成功时为空串。
    detail: str = ""


def _probe_declared(kind: str, profile: ResolvedConnection) -> HealthResult:
    """定义点名的探针。**失败是结果不是异常**(任何错都记成离线,细节带上),延迟照样量。"""
    impl = _custom_probe(kind)
    started = time.monotonic()
    try:
        # 探针实现收 (profile) —— 各家要的东西不一样(钥匙、appid、base_url 都可能在)。
        outcome = impl(profile)  # type: ignore[operator]
    except Exception as exc:
        return HealthResult(supported=True, online=False, detail=_short(str(exc) or exc.__class__.__name__))
    latency = int((time.monotonic() - started) * 1000)
    if outcome == "credential_rejected":
        return HealthResult(supported=True, online=True, latency_ms=latency, detail=tr("providerHealth_credentialRejected"))
    return HealthResult(supported=True, online=True, latency_ms=latency)


def health_path_for(vendor: str) -> str:
    definition = provider_definition(vendor)
    return definition.health_path if definition and definition.health_path else DEFAULT_HEALTH_PATH


#: 探针种类 → 实现(在适配器里;「怎么跟它说话」住适配器,这里只登记名字,延迟装载免得
#: 探个活就把全部适配器 import 一遍)。定义里点名了却没登记的,是 bug,测试钉着。
_PROBE_IMPLEMENTATIONS = {
    "volcano_tts": "app.ai.providers.adapters.bytedance.volcano.speech:probe_connection",
    "volcano_podcast": "app.ai.providers.adapters.bytedance.volcano.podcast:probe_connection",
}


def _custom_probe(kind: str) -> object:
    import importlib

    target = _PROBE_IMPLEMENTATIONS.get(kind, "")
    if not target:
        raise ValueError(f"health probe {kind!r} has no registered implementation (add it to _PROBE_IMPLEMENTATIONS)")
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


def probe(profile: ResolvedConnection) -> HealthResult:
    """打一次探针。**任何失败都是结果而不是异常** —— 探活本身失败就是"离线"这个答案。"""
    if profile.auth_type == "oauth":
        return HealthResult(supported=False)
    definition = provider_definition(profile.vendor)
    if definition and definition.health_probe:
        return _probe_declared(definition.health_probe, profile)
    base = (profile.base_url or "").strip().rstrip("/")
    if not base:
        # 没有 base_url 又不是订阅制:多半是还没配完,说不出在线与否。
        return HealthResult(supported=False)
    url = base + health_path_for(profile.vendor)
    # 鉴权头按这家目录说的那种话给:Gemini 认 `x-goog-api-key`,把 AI Studio 的 Key 当 Bearer 发过去会被回 401 ——
    # 界面上就成了一行「凭据被拒」,而钥匙明明是对的。
    headers = catalog_headers(catalog_protocol(profile.vendor), profile.api_key)
    started = time.monotonic()
    try:
        # 探活**不重试**:重试会把"慢"和"不通"都拉长成一个数字,而这里要的恰恰是当下这一次
        # 的真实往返。用 RetryingClient 但把次数压到 0,是为了继续吃到统一的代理/超时配置。
        with RetryingClient(timeout=PROBE_TIMEOUT_SECONDS, max_retries=0) as client:
            response = client.get(url, headers=headers)
        latency = int((time.monotonic() - started) * 1000)
    except httpx.HTTPError as exc:
        return HealthResult(supported=True, online=False, detail=_short(str(exc) or exc.__class__.__name__))
    except outbound_guard.OutboundBlocked as exc:
        #: 这个地址不许去(多人共用的部署里,连接填的内网地址要部署管理员先放行):说清为什么、怎么放行,不说「离线」。
        return HealthResult(supported=True, online=False, detail=str(exc))
    # 401/403 说明**端点是通的**,只是凭据不对 —— 这与"服务没起"是两回事,得分开说。
    if response.status_code in (401, 403):
        return HealthResult(supported=True, online=True, latency_ms=latency, detail=tr("providerHealth_credentialRejected"))
    if response.status_code >= 400:
        return HealthResult(
            supported=True, online=False, latency_ms=latency, detail=f"HTTP {response.status_code}"
        )
    return HealthResult(supported=True, online=True, latency_ms=latency)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text[:160]
