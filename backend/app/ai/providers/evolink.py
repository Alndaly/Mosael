"""Evolink media gateway adapter.

Evolink is a *platform* boundary: Seedance, Kling, Veo, Hailuo, WAN, Sora,
GPT Image, Gemini and Seedream are selected by ``model`` but share one HTTP
contract.  Keeping that contract here avoids cloning one provider adapter per
upstream engine and lets a single profile/API key serve image and video nodes.

Official protocol (evolink-media-mcp):

* local inputs -> ``files-api.evolink.ai/api/v1/files/upload/stream``;
* submit -> ``/v1/images/generations`` or ``/v1/videos/generations``;
* poll -> ``/v1/tasks/{task_id}``;
* result URLs are short lived, so download them into OpenStudio immediately.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.ai.providers.base import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    ROLE_URL_PARAMETERS,
    metering_from_request,
    poll_until_ready,
    provider_http_error,
)
from app.core.http_retry import RetryingClient
from app.media.image_preview import browser_compatible_image

BASE_URL = "https://api.evolink.ai/v1"
FILES_BASE_URL = "https://files-api.evolink.ai"
POLL_INTERVAL_SECONDS = 10.0
POLL_TIMEOUT_SECONDS = 600.0

_VIDEO_IMAGE_ROLES = (FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE)
_FAILED_STATUSES = {"failed", "cancelled", "canceled", "expired"}


def resolve_base_url(context: ProviderContext) -> str:
    base = (context.base_url or BASE_URL).rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def resolve_files_base_url(context: ProviderContext) -> str:
    return str(context.extra.get("files_base_url") or FILES_BASE_URL).rstrip("/")


def _parameter_urls(request: GenerationRequest, roles: tuple[str, ...]) -> list[str]:
    """Remote URLs only; local sources are uploaded separately.

    The common ``source_values`` helper intentionally turns local files into
    data URLs. Evolink's schema requires actual URLs, hence this adapter reads
    URL parameters directly and uses the Files API for local paths.
    """
    urls: list[str] = []
    for role in roles:
        names = ROLE_URL_PARAMETERS.get(role, ())
        if request.kind == "image" and role == REFERENCE_IMAGE:
            names = (*names, "image_url")
        elif request.kind == "video" and role == FIRST_FRAME:
            names = (*names, "image_url")
        for name in names:
            value = request.parameters.get(name)
            values = value if isinstance(value, (list, tuple)) else [value]
            urls.extend(str(one) for one in values if one)
    return urls


def build_image_payload(request: GenerationRequest, image_urls: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": request.model, "prompt": request.prompt}
    if request.parameters.get("size"):
        payload["size"] = str(request.parameters["size"]).replace("*", "x")
    if request.parameters.get("num_images") is not None:
        payload["n"] = int(request.parameters["num_images"])
    urls = image_urls if image_urls is not None else _parameter_urls(request, (REFERENCE_IMAGE,))
    if urls:
        payload["image_urls"] = urls
    return payload


def build_video_payload(request: GenerationRequest, image_urls: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": request.model, "prompt": request.prompt}
    if request.parameters.get("duration_seconds") is not None:
        payload["duration"] = int(request.parameters["duration_seconds"])
    if request.parameters.get("resolution"):
        payload["quality"] = str(request.parameters["resolution"])
    if request.parameters.get("aspect_ratio"):
        payload["aspect_ratio"] = str(request.parameters["aspect_ratio"])
    if request.parameters.get("generate_audio") is not None:
        payload["generate_audio"] = bool(request.parameters["generate_audio"])
    urls = image_urls if image_urls is not None else _parameter_urls(request, _VIDEO_IMAGE_ROLES)
    if urls:
        payload["image_urls"] = urls
    return payload


def extract_result_urls(payload: dict[str, Any]) -> list[str] | None:
    task = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(task.get("status") or "").lower()
    if status in _FAILED_STATUSES:
        error = task.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("code") or status
        else:
            detail = error or status
        raise ProviderError(f"Evolink 生成失败: {detail}")

    urls = [str(url) for url in (task.get("results") or []) if url]
    for item in task.get("result_data") or []:
        if not isinstance(item, dict):
            continue
        for key in ("video_url", "image_url", "audio_url"):
            if item.get(key):
                urls.append(str(item[key]))
                break
    urls = list(dict.fromkeys(urls))
    if urls:
        return urls
    if status == "completed":
        raise ProviderError("Evolink 返回完成状态但没有产物地址")
    return None


def _task_id(payload: dict[str, Any]) -> str:
    task = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return str(task.get("id") or task.get("task_id") or "").strip()


def _upload(path: Path, context: ProviderContext) -> str:
    compatible = browser_compatible_image(path, path.parent)
    if compatible is None:
        raise ProviderError(f"Evolink 无法读取输入图片: {path.name}")
    upload_path, mime = compatible
    headers = {"Authorization": f"Bearer {context.api_key}"}
    # Bytes make retries safe: unlike a streaming file handle, the request body
    # can be replayed after a transient 429/5xx.
    files = {"file": (upload_path.name, upload_path.read_bytes(), mime)}
    with RetryingClient(base_url=resolve_files_base_url(context), headers=headers, timeout=120) as client:
        response = client.post("/api/v1/files/upload/stream", files=files)
        response.raise_for_status()
        payload = response.json()
    if payload.get("success") is False:
        raise ProviderError(f"Evolink 素材上传失败: {payload.get('msg') or payload.get('code') or 'unknown error'}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    url = data.get("file_url") or data.get("download_url")
    if not url:
        raise ProviderError("Evolink 素材上传成功但没有返回文件地址")
    return str(url)


def collect_image_urls(request: GenerationRequest, context: ProviderContext) -> list[str]:
    roles = (REFERENCE_IMAGE,) if request.kind == "image" else _VIDEO_IMAGE_ROLES
    urls = _parameter_urls(request, roles)
    for role in roles:
        urls.extend(_upload(path, context) for path in request.sources_for(role))
    limit = 14 if request.kind == "image" else 9
    if len(urls) > limit:
        raise ProviderError(f"Evolink {request.kind} 最多接收 {limit} 张输入图片")
    return urls


def _suffix(url: str, kind: str, content_type: str) -> str:
    mime_suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) if content_type else None
    url_suffix = Path(urlparse(url).path).suffix
    fallback = ".mp4" if kind == "video" else ".png"
    suffix = mime_suffix or url_suffix or fallback
    return ".jpg" if suffix == ".jpe" else suffix


def download_results(urls: list[str], output_dir: Path, kind: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets: list[Path] = []
    with RetryingClient(timeout=180) as client:
        for index, url in enumerate(urls, start=1):
            with client.stream("GET", url) as response:
                response.raise_for_status()
                target = output_dir / f"generated-{index}{_suffix(url, kind, response.headers.get('content-type', ''))}"
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            targets.append(target)
    return targets


class EvolinkProvider(GenerationProvider):
    name = "evolink"

    def __init__(self, kind: str):
        if kind not in {"image", "video"}:
            raise ValueError(f"unsupported Evolink generation kind: {kind}")
        self.kind = kind

    def validate_request(self, request: GenerationRequest) -> None:
        # Evolink's public contract allows 3–15 second videos and 4K, wider
        # than the legacy provider-neutral guardrail (10s / 1080p).
        if not request.prompt.strip():
            raise ProviderError("Prompt must not be empty")
        if request.kind == "image":
            count = int(request.parameters.get("num_images", 1))
            if not 1 <= count <= 4:
                raise ProviderError("num_images must be between 1 and 4")
        else:
            duration = int(request.parameters.get("duration_seconds", 5))
            if not 3 <= duration <= 15:
                raise ProviderError("duration_seconds must be between 3 and 15")
            quality = str(request.parameters.get("resolution", "720p"))
            if quality not in {"480p", "720p", "1080p", "4k"}:
                raise ProviderError("resolution must be one of 480p, 720p, 1080p, 4k")

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("Evolink 生成需要 API Key，请在设置 → AI 服务中配置")
        if request.kind != self.kind:
            raise ProviderError(f"Evolink {self.kind} adapter received a {request.kind} request")
        headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
        try:
            image_urls = collect_image_urls(request, context)
            payload = (
                build_image_payload(request, image_urls)
                if self.kind == "image"
                else build_video_payload(request, image_urls)
            )
            path = "/images/generations" if self.kind == "image" else "/videos/generations"
            with RetryingClient(base_url=resolve_base_url(context), headers=headers, timeout=60) as client:
                response = client.post(path, json=payload)
                response.raise_for_status()
                task_id = _task_id(response.json())
                if not task_id:
                    raise ProviderError(f"Evolink 没有返回任务 id: {str(response.json())[:200]}")
                urls, terminal = poll_until_ready(
                    client,
                    f"/tasks/{task_id}",
                    extract_result_urls,
                    interval=POLL_INTERVAL_SECONDS,
                    timeout=POLL_TIMEOUT_SECONDS,
                    timed_out_message="Evolink 生成超时",
                )
            return GenerationResult(
                output_paths=download_results(urls, output_dir, self.kind),
                usage=metering_from_request(request),
                raw_usage=terminal,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("Evolink 请求失败", exc, context.api_key)) from exc
