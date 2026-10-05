"""百炼 DashScope 原生 API 的连接:根地址,和异步任务接口的客户端。

同一个百炼连接的 base_url 往往填的是对话用的 `https://dashscope.aliyuncs.com/compatible-mode/v1`
—— 那是 OpenAI 兼容端点。图像、视频、语音、音频走的是**原生**路径 `/api/v1/services/aigc/...`,
直接往后拼会得到 `…/compatible-mode/v1/api/v1/services/…`,一个必然 404 的地址。所以能力文件
一律从这里取根地址,不各自再剥一遍。
"""

from __future__ import annotations

import httpx

from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationAdapterError
from app.core.http_retry import RetryingClient

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
_COMPATIBLE_MODE = "/compatible-mode/v1"


def native_base(base_url: str | None) -> str:
    """把连接上的 base_url 归一到原生 API 根:认得出 compatible-mode 就剥掉,自定义代理原样放行。"""
    base = (base_url or "").strip().rstrip("/")
    return base.removesuffix(_COMPATIBLE_MODE) if base else DASHSCOPE_BASE


def failure_detail(response: httpx.Response) -> str:
    """一个失败的回包里百炼说的那句原话:`HTTP 400 · code: message`;不是 JSON(OSS 的 XML、网关的 HTML)就只有状态码。

    `raise_for_status` 抛出的那句只有状态行和地址 —— 「音色不存在」「前缀太长」这类能让人行动的原话在回包正文里。
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}
    said = ": ".join(part for part in (str(body.get("code") or "").strip(), str(body.get("message") or "").strip()) if part)
    return f"HTTP {response.status_code} · {said}" if said else f"HTTP {response.status_code}"


def task_api_base(context: GenerationAdapterContext) -> str:
    """异步任务接口(文生图、万相视频)的根。

    它不看连接的 base_url:那一格是给对话填的,可能是某个只代理了 compatible-mode 的网关。
    要换只能显式写在 `dashscope_base_url` / `generation_base_url` 里。
    """
    configured = str(context.options.get("dashscope_base_url") or context.options.get("generation_base_url") or "").strip()
    return (configured or DASHSCOPE_BASE).rstrip("/")


def async_task_client(context: GenerationAdapterContext, *, timeout: float) -> RetryingClient:
    """提交和查询异步任务用的客户端(`X-DashScope-Async: enable`)。"""
    if not context.api_key:
        raise GenerationAdapterError("providerErr_apiKeyMissing", vendor="DashScope")
    headers = {"Authorization": f"Bearer {context.api_key}", "X-DashScope-Async": "enable"}
    return RetryingClient(base_url=task_api_base(context), timeout=timeout, headers=headers)
