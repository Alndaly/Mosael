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
    metering_from_request,
    provider_http_error,
)

"""
ByteDance Seedance adapter.

Seedance 2.x runs on Volcano ARK's /api/v3 content-generation tasks endpoint.
Seedance 1.x is still served by the older LAS operator endpoint. Both contracts
take generation parameters as JSON fields, not prompt suffixes.
"""

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
LAS_BASE = "https://operator.las.cn-beijing.volces.com/api/v1"
TASKS_PATH = "/contents/generations/tasks"
DEFAULT_MODEL_ID = "doubao-seedance-2-0-260128"


def _is_seedance1(model: str) -> bool:
    return "seedance-1" in model


def _is_seedance2(model: str) -> bool:
    return "seedance-2" in model


def resolve_seedance_model(request: GenerationRequest, context: ProviderContext | None = None) -> str:
    return (request.model or (context.default_model if context else "") or DEFAULT_MODEL_ID).strip()


def resolve_seedance_base(model: str, context: ProviderContext) -> str:
    configured = (context.base_url or ARK_BASE).rstrip("/")
    if _is_seedance1(model) and configured == ARK_BASE:
        return LAS_BASE
    return configured


def build_submit_payload(request: GenerationRequest, context: ProviderContext | None = None) -> dict[str, Any]:
    model = resolve_seedance_model(request, context)
    duration = int(float(request.parameters.get("duration_seconds", 5)))
    resolution = str(request.parameters.get("resolution", "720p"))
    ratio = str(request.parameters.get("aspect_ratio", "16:9"))
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt.strip()}]
    # 三家共用的约定,住在 base 里 —— 这里此前是整段抄写的。
    first_frame = first_frame_value(request)
    if first_frame:
        image: dict[str, Any] = {"type": "image_url", "image_url": {"url": str(first_frame)}}
        if _is_seedance2(model):
            image["role"] = "first_frame"
        content.append(image)
    payload: dict[str, Any] = {
        "model": model,
        "content": content,
        "watermark": False,
        "duration": duration,
        "resolution": resolution,
    }
    if not first_frame:
        payload["ratio"] = ratio
    if request.parameters.get("generate_audio"):
        payload["generate_audio"] = True
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
            raise ProviderError("Provider returned success without a video URL")
        return str(url)
    if status in ("failed", "cancelled", "canceled", "expired"):
        raise ProviderError(f"Generation failed with status {status}")
    return None


class SeedanceProvider(GenerationProvider):
    name = "bytedance"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("ARK API key is not configured (settings → 生成服务)")
        model = resolve_seedance_model(request, context)
        base_url = resolve_seedance_base(model, context)
        headers = {"Authorization": f"Bearer {context.api_key}"}
        try:
            with RetryingClient(base_url=base_url, timeout=30, headers=headers) as client:
                submit = client.post(TASKS_PATH, json=build_submit_payload(request, context))
                submit.raise_for_status()
                task_id = submit.json().get("id") or ""
                if not task_id:
                    raise ProviderError("Provider did not return a task id")

                url, poll_payload = poll_until_ready(client, f"{TASKS_PATH}/{task_id}", extract_video_url)

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                with client.stream("GET", url) as download:
                    download.raise_for_status()
                    with target.open("wb") as out:
                        for chunk in download.iter_bytes():
                            out.write(chunk)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("ARK request failed", exc, context.api_key)) from exc
