from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.contracts.generation import (
    poll_until_ready,
    GenerationAdapter,
    GenerationRequest,
    GenerationResult,
    GenerationAdapterContext,
    GenerationAdapterError,
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    REFERENCE_AUDIO,
    first_frame_value,
    source_values,
    metering_from_request,
    adapter_http_error,
)
from app.ai.providers.media_transfer import download_to_path

"""
ByteDance Seedance adapter.

Seedance 1.x 和 2.x **都**跑在火山方舟的 /api/v3 上,同一把密钥、同一条路径,
参数是平铺的 JSON 字段而不是提示词后缀。

此前这里还有一条通往 LAS(operator.las.cn-beijing)的分支,给 seedance-1 用。2026-08-27
真机核过:拿方舟密钥打 LAS 一律 401 —— 那是另一套凭据,而设置里只让用户配一份火山密钥,
所以那条分支**从来没有真正跑通过**;同一把密钥打方舟的 doubao-seedance-1-0-pro-250528
则是正常出片的。分支连同 LAS_BASE 一起删掉,不留回落。
"""

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
TASKS_PATH = "/contents/generations/tasks"
DEFAULT_MODEL_ID = "doubao-seedance-2-0-260128"


def _is_seedance2(model: str) -> bool:
    return "seedance-2" in model


def resolve_seedance_model(request: GenerationRequest, context: GenerationAdapterContext | None = None) -> str:
    return (request.model or (context.configured_model_id if context else "") or DEFAULT_MODEL_ID).strip()


def resolve_seedance_base(model: str, context: GenerationAdapterContext) -> str:
    return (context.base_url or ARK_BASE).rstrip("/")


#: 每个角色在 content 数组里长什么样。接口的类型白名单是它自己报的:
#: `supported values are: text, image_url, audio_url, video_url and draft_task`。
_CONTENT_KINDS = {
    FIRST_FRAME: "image_url",
    LAST_FRAME: "image_url",
    REFERENCE_IMAGE: "image_url",
    REFERENCE_VIDEO: "video_url",
    REFERENCE_AUDIO: "audio_url",
}
_CONTENT_ROLES = (FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO, REFERENCE_AUDIO)


def build_submit_payload(request: GenerationRequest, context: GenerationAdapterContext | None = None) -> dict[str, Any]:
    model = resolve_seedance_model(request, context)
    duration = int(float(request.parameters.get("duration_seconds", 5)))
    resolution = str(request.parameters.get("resolution", "720p"))
    # **不写死 16:9。** 官方文档:2.5 / 2.0 系列 / 1.5 pro 的 ratio 默认就是 `adaptive`
    # (按任务类型和输入内容自动适配),写死 16:9 等于替模型做了它本来会自己做的选择 ——
    # 而且做反了:文生视频想要竖屏的人拿到的是横的。用户没指定时**不传这个字段**,
    # 让模型用它自己的默认;指定了就照发。
    ratio = str(request.parameters.get("aspect_ratio") or "").strip()
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt.strip()}]
    # content 数组按 `role` 区分每一份素材是干什么的,这正是接口自己的形状。
    #
    # **每个角色都可能有多份**:参考图能给九张、参考视频三段、参考音频三段(上限见
    # domain/generation/catalog 的 source_limits,数字是接口自己报的)。此前这里走的是单数的
    # source_value,九张参考图只发得出第一张 —— 不报错,只是效果不对。
    #
    # seedance-1 不认 role,那一档只发首帧(多发也没有字段承载它们)。
    roles = _CONTENT_ROLES if _is_seedance2(model) else (FIRST_FRAME,)
    first_frame = first_frame_value(request)
    for role in roles:
        kind = _CONTENT_KINDS[role]
        for value in source_values(request, role):
            item: dict[str, Any] = {"type": kind, kind: {"url": str(value)}}
            if _is_seedance2(model):
                item["role"] = role
            content.append(item)
    payload: dict[str, Any] = {
        "model": model,
        "content": content,
        "watermark": False,
        "duration": duration,
        "resolution": resolution,
    }
    # 有首帧时不传:文档说首帧/首尾帧生视频「模型自动保持输出视频宽高比和 first_frame 一致」,
    # 传了反而会触发裁剪(居中裁)。
    if ratio and not first_frame:
        payload["ratio"] = ratio
    # 这两项只由 1.x 描述符暴露，但 Adapter 仍按“给了就原样发送”处理。
    # 特别注意 camera_fixed=False 也是一个有意义的显式值，不能用 truthy 判断吞掉。
    if request.parameters.get("seed") is not None:
        payload["seed"] = int(request.parameters["seed"])
    if request.parameters.get("camera_fixed") is not None:
        payload["camera_fixed"] = bool(request.parameters["camera_fixed"])
    if request.parameters.get("generate_audio") is not None:
        payload["generate_audio"] = bool(request.parameters["generate_audio"])
    return payload


def extract_video_url(task_payload: dict[str, Any]) -> str | None:
    status = str(task_payload.get("status", "")).lower()
    if status == "succeeded":
        url = (
            task_payload.get("video_url")
            or (task_payload.get("output") or {}).get("video_url")
            or (task_payload.get("content") or {}).get("video_url")
        )
        if not url:
            raise GenerationAdapterError("Provider returned success without a video URL")
        return str(url)
    if status in ("failed", "cancelled", "canceled", "expired"):
        raise GenerationAdapterError(f"Generation failed with status {status}")
    return None


class SeedanceAdapter(GenerationAdapter):
    vendor_id = "bytedance"
    media_kind = "video"

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("ARK API key is not configured (settings → 生成服务)")
        model = resolve_seedance_model(request, context)
        base_url = resolve_seedance_base(model, context)
        headers = {"Authorization": f"Bearer {context.api_key}"}
        try:
            with RetryingClient(base_url=base_url, timeout=30, headers=headers) as client:
                submit = client.post(TASKS_PATH, json=build_submit_payload(request, context))
                submit.raise_for_status()
                task_id = submit.json().get("id") or ""
                if not task_id:
                    raise GenerationAdapterError("Provider did not return a task id")

                url, poll_payload = poll_until_ready(client, f"{TASKS_PATH}/{task_id}", extract_video_url)

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                download_to_path(url, target)
                return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise GenerationAdapterError(adapter_http_error("ARK request failed", exc, context.api_key)) from exc
