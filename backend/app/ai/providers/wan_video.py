from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.domain.ai_retry import RetryingClient

from app.ai.providers.base import (
    poll_until_ready,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    first_frame_value,
    metering_from_request,
    provider_http_error,
)
from app.ai.providers.qwen_image import (
    DASHSCOPE_BASE,
    download_result_asset,
    resolve_dashscope_base,
)

"""阿里云百炼(DashScope)的通义万相视频生成。

和同目录的 qwen_image 是**同一套异步任务协议**:提交拿 task_id → 轮询 `/api/v1/tasks/{id}`
→ 从终态里取一个预签名 OSS 地址下载。所以下载(不带 Authorization,否则 OSS 签名校验会变)
直接复用它的,不另写一份 —— 同一家的两条能力在这些地方不该有两种行为。轮询的节奏则跟着
base.poll_until_ready 走,六家共用一份。

只有两处是视频独有的:提交路径,以及结果字段是 `output.video_url` 而不是 `output.results[].url`。
"""

SUBMIT_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"

#: 终态。轮询到这两个就别再等了 —— 等下去只会耗满超时,而失败原因此刻就在手上。
_TERMINAL_FAILURES = ("FAILED", "CANCELED", "UNKNOWN")


#: 档位名 → 万相收的像素对。生成面板的**视频**分支发的是 `resolution`(720p 这种档位名),
#: 那是按火山/可灵那几家的形状定的;万相收的是像素对,直接把 "720p" 当尺寸发过去会被拒。
#: 竖屏没有单独的档位名可选,所以这里只映射横屏 —— 要竖屏就在 size 里显式写 `720*1280`。
_RESOLUTION_SIZES = {"480p": "832*480", "720p": "1280*720", "1080p": "1920*1080"}


def resolve_size(parameters: dict[str, Any]) -> str:
    """把界面给的尺寸归一成万相收的 `宽*高`。

    三种来源都要接住:显式的 `size`(可能写成 `1280x720`)、档位名 `resolution`、以及都没给。
    都没给就**不发这个字段** —— 让百炼用它自己的默认,而不是我们替它猜一个。
    """
    raw = str(parameters.get("size") or "").strip()
    if raw:
        return raw.replace("x", "*")
    label = str(parameters.get("resolution") or "").strip().lower()
    return _RESOLUTION_SIZES.get(label, "")


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    """把内部请求翻成万相的提交体。

    图生视频与文生视频**走同一个端点**,区别只是 input 里多一个首帧图 —— 这一点和火山
    Seedance / MiniMax 那两家不同(它们各自有独立路径或独立的 content 数组),所以这里不做
    路径分支,只在 input 上加字段。
    """
    parameters: dict[str, Any] = {}
    size = resolve_size(request.parameters)
    if size:
        parameters["size"] = size
    duration = request.parameters.get("duration_seconds") or request.parameters.get("duration")
    if duration is not None:
        parameters["duration"] = int(duration)
    if request.parameters.get("seed") is not None:
        parameters["seed"] = int(request.parameters["seed"])

    payload: dict[str, Any] = {"model": request.model, "input": {"prompt": request.prompt}}
    if request.negative_prompt:
        payload["input"]["negative_prompt"] = request.negative_prompt
    # 首帧图:**先看参数里的 url,再回落本地文件** —— 这是仓库里既有的约定
    # (seedance / kling 都是这么取的),而生成面板的视频分支发的正是 `first_frame_url`。
    # 只读 source_files 的话,界面上填的首帧会被静默忽略,图生视频退化成文生视频。
    first_frame = first_frame_value(request)
    if first_frame:
        payload["input"]["img_url"] = first_frame
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

                url, poll_payload = poll_until_ready(client, f"/api/v1/tasks/{task_id}", extract_video_url)

                target = output_dir / "generated.mp4"
                download_result_asset(url, target)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("DashScope request failed", exc, context.api_key)) from exc


__all__ = ["WanVideoProvider", "build_submit_payload", "extract_video_url", "SUBMIT_PATH", "DASHSCOPE_BASE"]
