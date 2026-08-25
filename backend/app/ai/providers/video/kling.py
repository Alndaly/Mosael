from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
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
    LAST_FRAME,
    first_frame_value,
    source_value,
    metering_from_request,
    provider_http_error,
)

"""
Kling video adapter:
text2video / image2video task creation → task polling → download video URL.
Official Kling accounts use AccessKey + SecretKey JWT auth. Some compatible
gateways accept a plain Bearer token; both paths are supported by the resolved
provider profile without branching in the runner.
"""

KLING_BASE = "https://api.klingai.com"
DEFAULT_MODEL_ID = "kling-v3"


def resolve_model(request: GenerationRequest, context: ProviderContext) -> str:
    if request.model != "kling":
        return request.model
    return context.default_model or DEFAULT_MODEL_ID


def build_submit_payload(request: GenerationRequest, context: ProviderContext | None = None) -> dict[str, Any]:
    model = resolve_model(request, context or ProviderContext(None, "kuaishou", "", default_model=""))
    duration = str(int(float(request.parameters.get("duration_seconds", 5))))
    resolution = str(request.parameters.get("resolution", "720p"))
    payload: dict[str, Any] = {
        "model_name": model,
        "prompt": request.prompt,
        "mode": str(request.parameters.get("mode") or ("pro" if resolution == "1080p" else "std")),
        "aspect_ratio": str(request.parameters.get("aspect_ratio", "16:9")),
        "duration": duration,
    }
    if request.negative_prompt:
        payload["negative_prompt"] = request.negative_prompt
    for key in ("cfg_scale", "camera_control", "external_task_id"):
        if request.parameters.get(key) not in (None, ""):
            payload[key] = request.parameters[key]

    first_frame = first_frame_value(request)
    if first_frame:
        payload["image"] = str(first_frame)
    # 尾帧走 image_tail(可灵把首尾帧拆成两个字段,而不是一个带 role 的数组)。
    # 只给尾帧不给首帧是不成立的 —— 那条接口是 image2video,首帧是它的必填项。
    last_frame = source_value(request, LAST_FRAME)
    if first_frame and last_frame:
        payload["image_tail"] = str(last_frame)
    return payload


def endpoint_for(request: GenerationRequest) -> str:
    return "/v1/videos/image2video" if first_frame_value(request) else "/v1/videos/text2video"


def extract_video_url(task_payload: dict[str, Any]) -> str | None:
    code = task_payload.get("code")
    if code not in (None, 0):
        raise ProviderError(f"Generation failed: {task_payload.get('message') or code}")

    data = task_payload.get("data") if isinstance(task_payload.get("data"), dict) else task_payload
    status = str(data.get("task_status", "")).lower()
    if status in ("submitted", "processing", "running", "queued"):
        return None
    if status in ("failed", "fail", "canceled", "cancelled"):
        message = data.get("task_status_msg") or data.get("message") or status
        raise ProviderError(f"Generation failed: {message}")
    if status != "succeed":
        return None

    result = data.get("task_result") or data.get("result") or {}
    candidates: list[Any] = [
        result.get("video_url") if isinstance(result, dict) else None,
        result.get("url") if isinstance(result, dict) else None,
    ]
    videos = result.get("videos") if isinstance(result, dict) else None
    if isinstance(videos, list):
        for video in videos:
            if isinstance(video, dict):
                candidates.extend([video.get("url"), video.get("video_url")])
    for candidate in candidates:
        if candidate:
            return str(candidate)
    raise ProviderError("Provider returned success without a video URL")


class KlingProvider(GenerationProvider):
    name = "kuaishou"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("Kling Access Key/API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or KLING_BASE).rstrip("/")
        endpoint = endpoint_for(request)
        headers = {"Authorization": auth_header(context), "Content-Type": "application/json"}
        try:
            with RetryingClient(base_url=base_url, timeout=60, headers=headers, follow_redirects=True) as client:
                submit = client.post(endpoint, json=build_submit_payload(request, context))
                submit.raise_for_status()
                data = submit.json().get("data") or {}
                task_id = data.get("task_id") or submit.json().get("task_id") or ""
                if not task_id:
                    raise ProviderError("Provider did not return a task id")

                url, poll_payload = poll_until_ready(client, f"{endpoint}/{task_id}", extract_video_url)

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                download = client.get(url)
                download.raise_for_status()
                target.write_bytes(download.content)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("Kling request failed", exc, context.api_key)) from exc


def auth_header(context: ProviderContext) -> str:
    secret_key = str(context.extra.get("secret_key") or "")
    if not secret_key:
        return f"Bearer {context.api_key}"
    now = int(time.time())
    token = _jwt_hs256(
        {"iss": context.api_key, "exp": now + 1800, "nbf": now - 5},
        secret_key,
    )
    return f"Bearer {token}"


def _jwt_hs256(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join([_b64url_json(header), _b64url_json(payload)])
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _b64url_json(value: dict[str, Any]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
