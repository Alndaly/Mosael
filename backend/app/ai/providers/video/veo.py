from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.base import (
    FIRST_FRAME,
    poll_until_ready,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    image_file_to_base64,
    metering_from_request,
    provider_http_error,
)

"""
Google Veo adapter via Gemini long-running prediction:
predictLongRunning → poll operation → download video URI.
"""

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL_ID = "veo-3.1-generate-preview"


def resolve_model(request: GenerationRequest, context: ProviderContext) -> str:
    if request.model != "veo":
        return request.model
    return context.default_model or DEFAULT_MODEL_ID


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    instance: dict[str, Any] = {"prompt": request.prompt}
    image_base64 = request.parameters.get("first_frame_base64") or request.parameters.get("image_base64")
    if image_base64:
        instance["image"] = {
            "inlineData": {
                "mimeType": str(request.parameters.get("first_frame_mime_type") or "image/png"),
                "data": str(image_base64),
            }
        }

    parameters: dict[str, Any] = {"numberOfVideos": 1}
    if request.parameters.get("aspect_ratio"):
        parameters["aspectRatio"] = str(request.parameters["aspect_ratio"])
    if request.parameters.get("duration_seconds"):
        parameters["durationSeconds"] = str(int(float(request.parameters["duration_seconds"])))
    if request.parameters.get("resolution"):
        parameters["resolution"] = str(request.parameters["resolution"])
    if request.parameters.get("person_generation"):
        parameters["personGeneration"] = str(request.parameters["person_generation"])
    if request.parameters.get("seed") not in (None, "", "auto"):
        parameters["seed"] = int(request.parameters["seed"])
    return {"instances": [instance], "parameters": parameters}


def extract_video_uri(operation_payload: dict[str, Any]) -> str | None:
    if operation_payload.get("error"):
        error = operation_payload["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ProviderError(f"Generation failed: {message}")
    if not operation_payload.get("done"):
        return None

    response = operation_payload.get("response") or {}
    generated = response.get("generateVideoResponse") or response.get("generate_video_response") or {}
    samples = generated.get("generatedSamples") or generated.get("generated_samples") or []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        video = sample.get("video") or {}
        if isinstance(video, dict) and video.get("uri"):
            return str(video["uri"])
    raise ProviderError("Provider returned success without a video URI")


class VeoProvider(GenerationProvider):
    name = "google"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("Google API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or GEMINI_BASE).rstrip("/")
        model = resolve_model(request, context)
        payload = build_submit_payload(_with_first_frame_inline(request, context.api_key))
        headers = {"x-goog-api-key": context.api_key}
        try:
            with RetryingClient(base_url=base_url, timeout=60, headers=headers, follow_redirects=True) as client:
                submit = client.post(f"/models/{model}:predictLongRunning", json=payload)
                submit.raise_for_status()
                operation_name = submit.json().get("name") or ""
                if not operation_name:
                    raise ProviderError("Provider did not return an operation name")

                uri, poll_payload = poll_until_ready(
                    client, f"/{operation_name.lstrip('/')}", extract_video_uri
                )

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                download = client.get(uri)
                download.raise_for_status()
                target.write_bytes(download.content)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("Google Veo request failed", exc, context.api_key)) from exc


def _with_first_frame_inline(request: GenerationRequest, api_key: str) -> GenerationRequest:
    if request.parameters.get("first_frame_base64") or request.parameters.get("image_base64"):
        return request
    first_frame = request.source_for(FIRST_FRAME)
    if first_frame is not None:
        mime_type, data = image_file_to_base64(first_frame)
        parameters = dict(request.parameters)
        parameters["first_frame_base64"] = data
        parameters["first_frame_mime_type"] = mime_type
        return GenerationRequest(
            kind=request.kind,
            model=request.model,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            parameters=parameters,
            sources=request.sources,
        )

    first_frame_url = request.parameters.get("first_frame_url") or request.parameters.get("image_url")
    if not first_frame_url:
        return request
    try:
        with RetryingClient(timeout=30, follow_redirects=True) as client:
            response = client.get(str(first_frame_url), headers={"x-goog-api-key": api_key})
            response.raise_for_status()
            mime_type = response.headers.get("content-type", "").split(";")[0]
            if not mime_type:
                mime_type = mimetypes.guess_type(str(first_frame_url))[0] or "image/png"
            parameters = dict(request.parameters)
            parameters["first_frame_base64"] = base64.b64encode(response.content).decode("ascii")
            parameters["first_frame_mime_type"] = mime_type
            return GenerationRequest(
                kind=request.kind,
                model=request.model,
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                parameters=parameters,
                sources=request.sources,
            )
    except httpx.HTTPError as exc:
        raise ProviderError(provider_http_error("Failed to fetch Veo first frame", exc, api_key)) from exc
