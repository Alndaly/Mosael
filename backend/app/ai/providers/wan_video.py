from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.domain.ai_retry import RetryingClient

from app.ai.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    image_file_to_data_url,
    metering_from_request,
    provider_http_error,
)
from app.ai.providers.qwen_image import (
    DASHSCOPE_BASE,
    POLL_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    download_result_asset,
    resolve_dashscope_base,
)

"""阿里云百炼(DashScope)的通义万相视频生成。

和同目录的 qwen_image 是**同一套异步任务协议**:提交拿 task_id → 轮询 `/api/v1/tasks/{id}`
→ 从终态里取一个预签名 OSS 地址下载。所以轮询间隔、超时、下载(不带 Authorization,否则 OSS
签名校验会变)这几样直接复用它的,不另写一份 —— 同一家的两条能力在这些地方不该有两种行为。

只有两处是视频独有的:提交路径,以及结果字段是 `output.video_url` 而不是 `output.results[].url`。
"""

SUBMIT_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"

#: 终态。轮询到这两个就别再等了 —— 等下去只会耗满超时,而失败原因此刻就在手上。
_TERMINAL_FAILURES = ("FAILED", "CANCELED", "UNKNOWN")


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    """把内部请求翻成万相的提交体。

    图生视频与文生视频**走同一个端点**,区别只是 input 里多一个首帧图 —— 这一点和火山
    Seedance / MiniMax 那两家不同(它们各自有独立路径或独立的 content 数组),所以这里不做
    路径分支,只在 input 上加字段。
    """
    parameters: dict[str, Any] = {}
    size = str(request.parameters.get("size") or request.parameters.get("resolution") or "").strip()
    if size:
        # 万相和 qwen-image 一样用 `宽*高`,而界面上到处写的是 `1280x720`。
        parameters["size"] = size.replace("x", "*")
    duration = request.parameters.get("duration_seconds") or request.parameters.get("duration")
    if duration is not None:
        parameters["duration"] = int(duration)
    if request.parameters.get("seed") is not None:
        parameters["seed"] = int(request.parameters["seed"])

    payload: dict[str, Any] = {"model": request.model, "input": {"prompt": request.prompt}}
    if request.negative_prompt:
        payload["input"]["negative_prompt"] = request.negative_prompt
    # 首帧图:本地文件转 data URL(与 qwen-image 的编辑模式同一条路),省掉一次外部图床。
    if request.source_files:
        payload["input"]["img_url"] = image_file_to_data_url(request.source_files[0])
    if parameters:
        payload["parameters"] = parameters
    return payload


def extract_video_url(task_payload: dict[str, Any]) -> str | None:
    """终态取地址;还没结束返回 None(继续轮询);失败直接抛。

    **不认识的状态一律当作"还没结束"**,而不是当作失败:百炼后来加的中间态(比如排队细分)
    要是被当成失败,用户看到的是一次本来会成功的生成被判死。
    """
    output = task_payload.get("output") or {}
    status = str(output.get("task_status") or "")
    if status == "SUCCEEDED":
        url = output.get("video_url")
        if url:
            return str(url)
        # 少数模型把结果放进 results 数组,和 qwen-image 的形状一致。
        for result in output.get("results") or []:
            if isinstance(result, dict) and result.get("video_url"):
                return str(result["video_url"])
            if isinstance(result, dict) and result.get("url"):
                return str(result["url"])
        raise ProviderError("Provider returned success without a result URL")
    if status in _TERMINAL_FAILURES:
        message = str(output.get("message") or task_payload.get("message") or "").strip()
        raise ProviderError(f"Generation failed with status {status}" + (f": {message}" if message else ""))
    return None


class WanVideoProvider(GenerationProvider):
    name = "alibaba"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("DashScope API key is not configured (settings → 生成服务)")
        headers = {"Authorization": f"Bearer {context.api_key}", "X-DashScope-Async": "enable"}
        try:
            with RetryingClient(base_url=resolve_dashscope_base(context), timeout=60, headers=headers) as client:
                submit = client.post(SUBMIT_PATH, json=build_submit_payload(request))
                submit.raise_for_status()
                task_id = ((submit.json().get("output") or {}).get("task_id")) or ""
                if not task_id:
                    raise ProviderError("Provider did not return a task id")

                deadline = time.time() + POLL_TIMEOUT_SECONDS
                url: str | None = None
                poll_payload: dict[str, Any] = {}
                while time.time() < deadline:
                    poll = client.get(f"/api/v1/tasks/{task_id}")
                    poll.raise_for_status()
                    poll_payload = poll.json()
                    url = extract_video_url(poll_payload)
                    if url:
                        break
                    time.sleep(POLL_INTERVAL_SECONDS)
                if not url:
                    raise ProviderError("Generation timed out")

                target = output_dir / "generated.mp4"
                download_result_asset(url, target)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("DashScope request failed", exc, context.api_key)) from exc


__all__ = ["WanVideoProvider", "build_submit_payload", "extract_video_url", "SUBMIT_PATH", "DASHSCOPE_BASE"]
