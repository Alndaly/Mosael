from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.base import (
    poll_until_ready,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    first_frame_value,
    source_values,
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    SOURCE_VIDEO,
    FIRST_CLIP,
    DRIVING_AUDIO,
    metering_from_request,
    provider_http_error,
)
from app.ai.providers.alibaba.image import (
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


#: 档位名 → 万相收的像素对。
#:
#: 生成面板现在按模型声明发 `size`(像素对),所以正常路径不走这张表。留着是给**工作流节点**
#: 兜底:那里的参数是自由填的(见 domain/workflows 的 params 说明,"取值随模型而定"),
#: 有人照着别家的习惯写 `resolution: 720p` 是完全可能的 —— 与其让百炼回一句看不懂的
#: `size is not supported`,不如认下这几个众所周知的档位名。
#:
#: 只映射横屏:竖屏没有对应的档位名,要竖屏就在 size 里显式写 `720*1280`。
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


#: 万相 2.7 起,输入素材走 `input.media` 数组;2.6 及更早只认一个 `input.img_url` 首帧。
#:
#: 这不是我们的历史包袱,是**两代模型两份契约**,所以写成一句可以回答的问题,而不是散在
#: 各处的 if。判断放在这里的代价是新一代上线要改一行;放在调用方的代价是漏掉一处不会报错 ——
#: 提交照样 200,任务终态才回 `Field required: input.media`。
_MEDIA_ARRAY_PREFIXES = ("wan2.7", "wan2.8", "wan3")

#: 视频编辑走的也是同一条路径、同一个 media 数组,只是模型名不带代号后缀 —— 显式列出来,
#: 免得哪天前缀规则改了把它漏掉(漏掉的下场是提交 200、终态 `Field required: input.media`)。
_MEDIA_ARRAY_MODELS = ("wan2.7-videoedit",)

#: media 数组里的 type。大部分角色名和我们内部的一样,只有**被编辑的那段视频**例外:
#: 万相把它叫 `video`,而我们叫 `source_video` —— 内部不能也叫 video,那个词在这里
#: 什么都指(参考视频是视频,续写的片段也是视频),读的人分不出哪个是哪个。
_MEDIA_TYPES = {
    FIRST_FRAME: "first_frame",
    LAST_FRAME: "last_frame",
    REFERENCE_IMAGE: "reference_image",
    REFERENCE_VIDEO: "reference_video",
    FIRST_CLIP: "first_clip",
    SOURCE_VIDEO: "video",
    DRIVING_AUDIO: "driving_audio",
}
_MEDIA_ROLES = tuple(_MEDIA_TYPES)


def uses_media_array(model: str) -> bool:
    name = str(model or "").strip().lower()
    return name.startswith(_MEDIA_ARRAY_PREFIXES) or name in _MEDIA_ARRAY_MODELS


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    """把内部请求翻成万相的提交体。

    图生视频与文生视频**走同一个端点**,区别只是 input 里多一个首帧图 —— 这一点和火山
    Seedance / MiniMax 那两家不同(它们各自有独立路径或独立的 content 数组),所以这里不做
    路径分支,只在 input 上加字段。
    """
    provider_options: dict[str, Any] = {}
    if uses_media_array(request.model):
        # 2.7 按**清晰度档**出片,不收 `宽*高`:传 size 会被终态拒成
        # `Invalid input format, expected format like '480*832'` 或
        # `Input should be '1080P' or '720P'`。比例单独走 aspect_ratio。
        resolution = str(request.parameters.get("resolution") or "").strip()
        if resolution:
            provider_options["resolution"] = resolution.upper()
        ratio = str(request.parameters.get("aspect_ratio") or "").strip()
        if ratio:
            # Wan 2.7 calls this field `ratio` (not the domain-facing `aspect_ratio`).
            # Keeping the translation at the Adapter seam lets every caller use one
            # canonical parameter name without leaking provider vocabulary upward.
            provider_options["ratio"] = ratio
    else:
        size = resolve_size(request.parameters)
        if size:
            provider_options["size"] = size
    duration = request.parameters.get("duration_seconds")
    if duration is not None:
        provider_options["duration"] = int(duration)
    if request.parameters.get("seed") is not None:
        provider_options["seed"] = int(request.parameters["seed"])

    payload: dict[str, Any] = {"model": request.model, "input": {"prompt": request.prompt}}
    if request.negative_prompt:
        payload["input"]["negative_prompt"] = request.negative_prompt
    if uses_media_array(request.model):
        media = [
            {"type": _MEDIA_TYPES[role], "url": str(value)}
            for role in _MEDIA_ROLES
            for value in source_values(request, role)
        ]
        if media:
            payload["input"]["media"] = media
    else:
        # 首帧图:**先看参数里的 url,再回落本地文件** —— 这是仓库里既有的约定
        # (seedance / kling 都是这么取的),而生成面板的视频分支发的正是 `first_frame_url`。
        # 只读 source_files 的话,界面上填的首帧会被静默忽略,图生视频退化成文生视频。
        first_frame = first_frame_value(request)
        if first_frame:
            payload["input"]["img_url"] = first_frame
    if provider_options:
        payload["parameters"] = provider_options
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
                return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("DashScope request failed", exc, context.api_key)) from exc


__all__ = ["WanVideoProvider", "build_submit_payload", "extract_video_url", "SUBMIT_PATH", "DASHSCOPE_BASE"]
