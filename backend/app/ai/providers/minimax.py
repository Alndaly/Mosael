from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.base import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    REFERENCE_AUDIO,
    source_value,
    source_values,
    poll_until_ready,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    image_file_to_data_url,
    metering_from_request,
    provider_http_error,
)
from app.ai.providers.media_transfer import download_to_path

"""
MiniMax 海螺(Hailuo)视频生成。

**走 v2 而不是 v1**:v1 是 `POST /v1/video_generation` → 轮询拿 `file_id` → 再打
`/v1/files/retrieve` 换下载地址,三段;v2 把结果直接放进查询响应的 `content.url`,
少一次往返也少一处会过期的中间态。H3(2026-07 发布)只在 v2 上提供。

**请求体是多模态数组而不是平铺字段**:提示词、首帧、参考图都是 `content` 里的一项,
靠 `role` 区分("first_frame" / "reference_image" …)。这与 Seedance 的平铺 JSON 不同,
所以没法共用 payload 构造。

**图生视频时 ratio 必须是 adaptive**:官方文档明确规定——文生视频必填具体比例且不能是
adaptive,图生视频则恒为 adaptive(画面比例由首帧决定)。传错会被直接拒。
"""

BASE_URL = "https://api.minimaxi.com"
SUBMIT_PATH = "/v2/video_generation"
QUERY_PATH = "/v2/query/video_generation"
DEFAULT_MODEL_ID = "MiniMax-H3"

#: 终态。轮询看到这些就停,不再等超时。
TERMINAL_FAILURES = ("failed", "cancelled", "canceled", "expired")


def resolve_model(request: GenerationRequest, context: ProviderContext | None = None) -> str:
    return (request.model or (context.default_model if context else "") or DEFAULT_MODEL_ID).strip()


#: 每个角色在 content 数组里的类型。白名单是接口自己报的:
#: `allowed: text|image_url|video_url|audio_url`,而且它会校验类型和 role 配不配对
#: (`role="first_frame" invalid for type="video_url"`)。
_CONTENT_KINDS = {
    FIRST_FRAME: "image_url",
    LAST_FRAME: "image_url",
    REFERENCE_IMAGE: "image_url",
    REFERENCE_VIDEO: "video_url",
    REFERENCE_AUDIO: "audio_url",
}
_CONTENT_ROLES = (FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO, REFERENCE_AUDIO)


def build_submit_payload(request: GenerationRequest, context: ProviderContext) -> dict[str, Any]:
    """把内部的生成请求翻成 MiniMax 的多模态 content 数组。"""
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
    # content 数组按 role 区分每一份素材的用途 —— 这是接口自己的形状(文件顶上那段注释说的
    # 就是它)。**每个角色都可能有多份**:参考图九张、参考视频三段、参考音频三段,上限见
    # domain/generation/catalog 的 source_limits。此前这里走单数的 source_value,挂了九张
    # 参考图也只发得出第一张。
    for role in _CONTENT_ROLES:
        kind = _CONTENT_KINDS[role]
        for value in source_values(request, role):
            content.append({"type": kind, "role": role, kind: {"url": str(value)}})
    first_frame = source_value(request, FIRST_FRAME)
    payload: dict[str, Any] = {"model": resolve_model(request, context), "content": content}

    duration = request.parameters.get("duration_seconds")
    if duration:
        # 范围由 domain/generation 的模型描述符统一校验。Adapter 只翻译，不能把用户要的
        # 99 秒静默改成 15 秒；那会让任务“成功”却交付错误结果。
        payload["duration"] = int(duration)
    resolution = request.parameters.get("resolution")
    if resolution:
        payload["resolution"] = str(resolution)
    # 图生视频恒为 adaptive(比例由首帧决定);文生视频必须给具体比例。
    payload["ratio"] = "adaptive" if first_frame else str(request.parameters.get("aspect_ratio") or "16:9")
    return payload


def extract_video_url(payload: dict[str, Any]) -> str | None:
    """成功时取下载地址;终态失败直接抛,不要等到超时才说话。"""
    task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
    status = str(task.get("status") or "").lower()
    if status in TERMINAL_FAILURES:
        detail = task.get("error") or payload.get("base_resp") or status
        raise ProviderError(f"MiniMax 视频生成失败:{detail}")
    content = task.get("content")
    if isinstance(content, dict) and content.get("url"):
        return str(content["url"])
    return None


class MiniMaxVideoProvider(GenerationProvider):
    name = "minimax"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("MiniMax 视频生成需要 API Key,请在设置 → AI 视频里配置")
        base_url = (context.base_url or BASE_URL).rstrip("/")
        # 档案里填的常是对话用的 `.../v1`,而视频在 `/v2` 下。截掉版本段按官方路径重新拼,
        # 免得用户为了视频再建一个只有 base_url 不同的档案。
        for suffix in ("/v1", "/v2"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
        try:
            with RetryingClient(base_url=base_url, timeout=30, headers=headers) as client:
                submit = client.post(SUBMIT_PATH, json=build_submit_payload(request, context))
                submit.raise_for_status()
                submitted = submit.json()
                task_id = submitted.get("task_id") or (submitted.get("task") or {}).get("id") or ""
                if not task_id:
                    raise ProviderError(f"MiniMax 没有返回任务 id:{str(submitted)[:200]}")

                url, poll_payload = poll_until_ready(
                    client, f"{QUERY_PATH}/{task_id}", extract_video_url,
                    timed_out_message="MiniMax 视频生成超时",
                )

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                download_to_path(url, target, timeout=120)
                return GenerationResult(
                    output_paths=[target], usage=metering_from_request(request), raw_usage=poll_payload
                )
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("MiniMax 请求失败", exc, context.api_key)) from exc
