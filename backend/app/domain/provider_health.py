"""供应商是不是活着,以及打过去要多久。

**为什么值得单独做**:配置错了和服务没起,在界面上此前是同一种表现 —— 什么都没有,直到
真去生成一次才在任务失败里看到一句 502。本地类端点(ComfyUI / Ollama / LM Studio)尤其如此:
它们最常见的故障就是"忘了启动",而这件事一秒钟就能测出来。

**探针路径由 vendor 声明**(VENDOR_PRESETS 的 `health_path`),不在这里按名字写死一张表 ——
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

from app.domain.provider_credentials import ResolvedProvider
from app.domain.ai_retry import RetryingClient
from app.domain.providers import VENDOR_PRESETS

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


def health_path_for(vendor: str) -> str:
    preset = VENDOR_PRESETS.get(vendor) or {}
    declared = preset.get("health_path")
    return str(declared) if isinstance(declared, str) and declared else DEFAULT_HEALTH_PATH


def probe(profile: ResolvedProvider) -> HealthResult:
    """打一次探针。**任何失败都是结果而不是异常** —— 探活本身失败就是"离线"这个答案。"""
    if profile.auth_type == "oauth":
        return HealthResult(supported=False)
    base = (profile.base_url or "").strip().rstrip("/")
    if not base:
        # 没有 base_url 又不是订阅制:多半是还没配完,说不出在线与否。
        return HealthResult(supported=False)
    url = base + health_path_for(profile.vendor)
    headers = {"Authorization": f"Bearer {profile.api_key}"} if profile.api_key else {}
    started = time.monotonic()
    try:
        # 探活**不重试**:重试会把"慢"和"不通"都拉长成一个数字,而这里要的恰恰是当下这一次
        # 的真实往返。用 RetryingClient 但把次数压到 0,是为了继续吃到统一的代理/超时配置。
        with RetryingClient(timeout=PROBE_TIMEOUT_SECONDS, max_retries=0) as client:
            response = client.get(url, headers=headers)
        latency = int((time.monotonic() - started) * 1000)
    except httpx.HTTPError as exc:
        return HealthResult(supported=True, online=False, detail=_short(str(exc) or exc.__class__.__name__))
    # 401/403 说明**端点是通的**,只是凭据不对 —— 这与"服务没起"是两回事,得分开说。
    if response.status_code in (401, 403):
        return HealthResult(supported=True, online=True, latency_ms=latency, detail="凭据被拒")
    if response.status_code >= 400:
        return HealthResult(
            supported=True, online=False, latency_ms=latency, detail=f"HTTP {response.status_code}"
        )
    return HealthResult(supported=True, online=True, latency_ms=latency)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text[:160]
