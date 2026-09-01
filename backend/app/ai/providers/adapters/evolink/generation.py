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

from app.ai.providers.contracts.generation import (
    FIRST_CLIP,
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_AUDIO,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    SOURCE_VIDEO,
    GenerationAdapter,
    GenerationRequest,
    GenerationResult,
    GenerationAdapterContext,
    GenerationAdapterError,
    metering_from_request,
    poll_until_ready,
    adapter_http_error,
    source_url_values,
)
from app.core.http_retry import RetryingClient
from app.media.image_preview import browser_compatible_image
from app.ai.providers.media_transfer import download_to_path

BASE_URL = "https://api.evolink.ai/v1"
FILES_BASE_URL = "https://files-api.evolink.ai"
POLL_INTERVAL_SECONDS = 10.0
POLL_TIMEOUT_SECONDS = 600.0

#: 图片角色的迭代顺序即 `image_urls` 的数组顺序:首帧在前、尾帧在后(网关按位置认帧)。
#: 参考图和帧不会同时出现 —— 描述符按模型 id 把两条路分开了,所以进同一个数组是安全的。
_VIDEO_IMAGE_ROLES = (FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE)
#: 视频角色的迭代顺序即 `video_urls` 的数组顺序:**被编辑/被续写的那段必须在第一位**
#: (文档原文:the first video is the video being edited / extended),其余位置才是参考。
_VIDEO_VIDEO_ROLES = (SOURCE_VIDEO, FIRST_CLIP, REFERENCE_VIDEO)
_VIDEO_AUDIO_ROLES = (REFERENCE_AUDIO,)
_FAILED_STATUSES = {"failed", "cancelled", "canceled", "expired"}


def resolve_base_url(context: GenerationAdapterContext) -> str:
    base = (context.base_url or BASE_URL).rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def resolve_files_base_url(context: GenerationAdapterContext) -> str:
    return str(context.options.get("files_base_url") or FILES_BASE_URL).rstrip("/")


def _parameter_urls(request: GenerationRequest, roles: tuple[str, ...]) -> list[str]:
    """Remote URLs only; local sources are uploaded separately.

    The common ``source_values`` helper intentionally turns local files into
    data URLs. Evolink's schema requires actual URLs, hence this adapter reads
    URL parameters directly and uses the Files API for local paths.
    """
    return [url for role in roles for url in source_url_values(request.parameters, role, request.kind)]


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


def build_video_payload(
    request: GenerationRequest,
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    audio_urls: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": request.model, "prompt": request.prompt}
    if request.parameters.get("duration_seconds") is not None:
        payload["duration"] = int(request.parameters["duration_seconds"])
    if request.parameters.get("resolution"):
        payload["quality"] = str(request.parameters["resolution"])
    if request.parameters.get("aspect_ratio"):
        payload["aspect_ratio"] = str(request.parameters["aspect_ratio"])
    if request.parameters.get("generate_audio") is not None:
        payload["generate_audio"] = bool(request.parameters["generate_audio"])
    images = image_urls if image_urls is not None else _parameter_urls(request, _VIDEO_IMAGE_ROLES)
    if images:
        payload["image_urls"] = images
    # 全能参考与视频编辑/续写走 video_urls / audio_urls(Seedance 2.5 的五份文档,2026-09-01
    # 核)。1.5 与 2.5-i2v 的描述符不声明视频/音频角色,这两段在那些模型上自然为空。
    videos = video_urls if video_urls is not None else _parameter_urls(request, _VIDEO_VIDEO_ROLES)
    if videos:
        payload["video_urls"] = videos
    audios = audio_urls if audio_urls is not None else _parameter_urls(request, _VIDEO_AUDIO_ROLES)
    if audios:
        payload["audio_urls"] = audios
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
        raise GenerationAdapterError(f"Evolink 生成失败: {detail}")

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
        raise GenerationAdapterError("Evolink 返回完成状态但没有产物地址")
    return None


def _task_id(payload: dict[str, Any]) -> str:
    task = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return str(task.get("id") or task.get("task_id") or "").strip()


def _upload(path: Path, context: GenerationAdapterContext, *, image: bool = True) -> str:
    mime: str | None = None
    upload_path = path
    if image:
        compatible = browser_compatible_image(path, path.parent)
        if compatible is None:
            raise GenerationAdapterError(f"Evolink 无法读取输入图片: {path.name}")
        upload_path, mime = compatible
    if mime is None:
        # 参考视频/音频原样上传 —— 网关收 .mp4/.mov/.wav/.mp3,图像归一化对它们既不适用也会失败。
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Authorization": f"Bearer {context.api_key}"}
    # Bytes make retries safe: unlike a streaming file handle, the request body
    # can be replayed after a transient 429/5xx.
    files = {"file": (upload_path.name, upload_path.read_bytes(), mime)}
    with RetryingClient(base_url=resolve_files_base_url(context), headers=headers, timeout=120) as client:
        response = client.post("/api/v1/files/upload/stream", files=files)
        response.raise_for_status()
        payload = response.json()
    if payload.get("success") is False:
        raise GenerationAdapterError(f"Evolink 素材上传失败: {payload.get('msg') or payload.get('code') or 'unknown error'}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    url = data.get("file_url") or data.get("download_url")
    if not url:
        raise GenerationAdapterError("Evolink 素材上传成功但没有返回文件地址")
    return str(url)


def _collect_role_urls(
    request: GenerationRequest,
    context: GenerationAdapterContext,
    roles: tuple[str, ...],
    *,
    image: bool,
    limit: int,
    label: str,
) -> list[str]:
    """一类媒体的外链 + 本地上传,按角色顺序排好。上限是**协议天花板**(图 30 / 视频 10 /
    音频 10);每个模型各自的更严上限由描述符的 source_limits 在提交前就拦掉了。"""
    urls: list[str] = []
    for role in roles:
        urls.extend(source_url_values(request.parameters, role, request.kind))
        urls.extend(_upload(path, context, image=image) for path in request.sources_for(role))
    if len(urls) > limit:
        raise GenerationAdapterError(f"Evolink {request.kind} 最多接收 {limit} 份{label}")
    return urls


def collect_media_urls(request: GenerationRequest, context: GenerationAdapterContext) -> dict[str, list[str]]:
    """把输入素材按网关的三个数组收齐:image_urls / video_urls / audio_urls。

    视频角色排首位的是被处理的那段(见 _VIDEO_VIDEO_ROLES),数组顺序就是语义,
    不能按"先收集到的在前"排。
    """
    if request.kind == "image":
        return {
            "image_urls": _collect_role_urls(request, context, (REFERENCE_IMAGE,), image=True, limit=14, label="图片")
        }
    return {
        "image_urls": _collect_role_urls(request, context, _VIDEO_IMAGE_ROLES, image=True, limit=30, label="图片"),
        "video_urls": _collect_role_urls(request, context, _VIDEO_VIDEO_ROLES, image=False, limit=10, label="视频"),
        "audio_urls": _collect_role_urls(request, context, _VIDEO_AUDIO_ROLES, image=False, limit=10, label="音频"),
    }


def _suffix(url: str, kind: str, content_type: str) -> str:
    mime_suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) if content_type else None
    url_suffix = Path(urlparse(url).path).suffix
    fallback = ".mp4" if kind == "video" else ".png"
    suffix = mime_suffix or url_suffix or fallback
    return ".jpg" if suffix == ".jpe" else suffix


def download_results(urls: list[str], output_dir: Path, kind: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets: list[Path] = []
    for index, url in enumerate(urls, start=1):
        staged = output_dir / f"generated-{index}.download"
        content_type = download_to_path(url, staged, timeout=180)
        target = output_dir / f"generated-{index}{_suffix(url, kind, content_type)}"
        staged.replace(target)
        targets.append(target)
    return targets


class EvolinkGenerationAdapter(GenerationAdapter):
    vendor_id = "evolink"

    def __init__(self, media_kind: str):
        if media_kind not in {"image", "video"}:
            raise ValueError(f"unsupported Evolink generation kind: {media_kind}")
        self.media_kind = media_kind

    def validate_request(self, request: GenerationRequest) -> None:
        # Evolink 网关的协议范围:视频 3–30 秒(Seedance 2.5 已放到 4–30,2026-09-01 文档)、
        # 最高 4K。每个模型自己的更严限制由描述符在提交前拦,这里只是兜底。
        if not request.prompt.strip():
            raise GenerationAdapterError("Prompt must not be empty")
        if request.kind == "image":
            count = int(request.parameters.get("num_images", 1))
            if not 1 <= count <= 4:
                raise GenerationAdapterError("num_images must be between 1 and 4")
        else:
            duration = int(request.parameters.get("duration_seconds", 5))
            if duration != -1 and not 3 <= duration <= 30:
                raise GenerationAdapterError("duration_seconds must be -1 (auto) or between 3 and 30")
            quality = str(request.parameters.get("resolution", "720p"))
            if quality not in {"480p", "720p", "1080p", "4k"}:
                raise GenerationAdapterError("resolution must be one of 480p, 720p, 1080p, 4k")

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("Evolink 生成需要 API Key，请在设置 → AI 服务中配置")
        if request.kind != self.media_kind:
            raise GenerationAdapterError(f"Evolink {self.media_kind} adapter received a {request.kind} request")
        headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
        try:
            media = collect_media_urls(request, context)
            payload = (
                build_image_payload(request, media["image_urls"])
                if self.media_kind == "image"
                else build_video_payload(
                    request, media["image_urls"], media.get("video_urls"), media.get("audio_urls")
                )
            )
            path = "/images/generations" if self.media_kind == "image" else "/videos/generations"
            with RetryingClient(base_url=resolve_base_url(context), headers=headers, timeout=60) as client:
                response = client.post(path, json=payload)
                response.raise_for_status()
                task_id = _task_id(response.json())
                if not task_id:
                    raise GenerationAdapterError(f"Evolink 没有返回任务 id: {str(response.json())[:200]}")
                urls, terminal = poll_until_ready(
                    client,
                    f"/tasks/{task_id}",
                    extract_result_urls,
                    interval=POLL_INTERVAL_SECONDS,
                    timeout=POLL_TIMEOUT_SECONDS,
                    timed_out_message="Evolink 生成超时",
                )
            return GenerationResult(
                output_paths=download_results(urls, output_dir, self.media_kind),
                usage=metering_from_request(request),
                raw_usage=terminal,
            )
        except httpx.HTTPError as exc:
            raise GenerationAdapterError(adapter_http_error("Evolink 请求失败", exc, context.api_key)) from exc
