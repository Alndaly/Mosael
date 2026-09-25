"""Evolink media gateway adapter.

Evolink is a *platform* boundary: Seedance, Kling, Veo, Hailuo, WAN, Sora,
GPT Image, Gemini and Seedream are selected by ``model`` but share one HTTP
contract.  Keeping that contract here avoids cloning one provider adapter per
upstream engine and lets a single profile/API key serve image and video nodes.

Official protocol (evolink-media-mcp):

* local inputs -> ``files-api.evolink.ai/api/v1/files/upload/stream``;
* submit -> ``/v1/images/generations``, ``/v1/videos/generations`` or ``/v1/audios/generations``;
* poll -> ``/v1/tasks/{task_id}``;
* result URLs are short lived, so download them into Mosael immediately.

Audio (Suno) — https://evolink.ai/docs/en/api-manual/audio-series/suno/suno-music-generation and its
OpenAPI JSON, checked 2026-09-25. Suno has two modes and the adapter picks by what the user gave:

* **simple** (only a description): ``prompt`` is the description (≤500 chars). Every other creative
  field is accepted but ignored in this mode, the docs say — so we never send them there.
* **custom** (lyrics, instrumental, negative prompt, title, vocal gender or duration given): ``style``
  and ``title`` are required, ``prompt`` becomes the lyrics (optional when instrumental). The user's
  description is what Suno calls the style; the title defaults to the description's first line.

One generation returns **two tracks** (product page https://evolink.ai/suno); both land in the library.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.ai.audio_files import audio_suffix
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
    categorized_http_error,
    source_url_values,
    upstream_error,
)
from app.core.http_retry import RetryingClient
from app.media.image_preview import browser_compatible_image
from app.ai.media_transfer import download_to_path

BASE_URL = "https://api.evolink.ai/v1"
FILES_BASE_URL = "https://files-api.evolink.ai"
#: 这家的网关排队久,轮得勤没有意义。**上限不在这里另定**:用共用的那一个(见
#: contracts.generation.POLL_TIMEOUT_SECONDS)—— 此前这里的 600 秒是"我们等烦了",而远端任务
#: 不会因为我们放弃等待就停下、不再扣费。
POLL_INTERVAL_SECONDS = 10.0

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


#: Suno 的人声性别:宿主写 female / male,Suno 收 f / m。
_SUNO_GENDER = {"female": "f", "male": "m"}
#: 自定义模式的曲名上限(文档:max 80)。
_SUNO_TITLE_MAX = 80


def _suno_custom_mode(request: GenerationRequest) -> bool:
    """用户给了任何只有自定义模式才认的东西,就走自定义模式 —— 简单模式会把它们悄悄忽略掉。"""
    parameters = request.parameters
    return bool(
        str(parameters.get("lyrics") or "").strip()
        or parameters.get("instrumental") is True
        or request.negative_prompt.strip()
        or str(parameters.get("title") or "").strip()
        or parameters.get("vocal_gender")
        or parameters.get("duration_seconds") is not None
    )


def build_audio_payload(request: GenerationRequest) -> dict[str, Any]:
    """宿主请求 → Suno 请求体(两种模式见文件头)。"""
    payload: dict[str, Any] = {"model": request.model}
    if not _suno_custom_mode(request):
        payload["prompt"] = request.prompt
        return payload
    parameters = request.parameters
    payload["custom_mode"] = True
    description = request.prompt.strip()
    payload["style"] = description
    title = str(parameters.get("title") or "").strip() or (description.splitlines()[0] if description else "")
    payload["title"] = title[:_SUNO_TITLE_MAX]
    lyrics = str(parameters.get("lyrics") or "").strip()
    if parameters.get("instrumental") is True:
        payload["instrumental"] = True
    if lyrics:
        payload["prompt"] = lyrics
    if request.negative_prompt.strip():
        payload["negative_tags"] = request.negative_prompt.strip()
    gender = _SUNO_GENDER.get(str(parameters.get("vocal_gender") or ""))
    if gender:
        payload["vocal_gender"] = gender
    if parameters.get("duration_seconds") is not None:
        payload["duration"] = int(parameters["duration_seconds"])
    return payload


def extract_audio_urls(payload: dict[str, Any]) -> list[str] | None:
    """音频任务的终态:**先认 `results`**,那是任务查询接口写明的结果地址清单。

    `result_data` 的形状文档里有两种说法(`songs[]` 与列表),只在 `results` 为空时兜底读它 ——
    两处都读并合并的话,同一首歌若在两处给了不同的地址(播放流 / 成品),会被当成四首下载。
    """
    task = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(task.get("status") or "").lower()
    if status in _FAILED_STATUSES:
        _raise_task_error(task, status)
    urls = [str(url) for url in (task.get("results") or []) if url]
    if not urls:
        data = task.get("result_data")
        songs = data.get("songs") if isinstance(data, dict) else data
        for song in songs or []:
            if isinstance(song, dict) and song.get("audio_url"):
                urls.append(str(song["audio_url"]))
    urls = list(dict.fromkeys(urls))
    if urls and status in ("completed", ""):
        return urls
    if status == "completed":
        raise GenerationAdapterError("providerErr_noResultUrl", vendor="Evolink")
    return None


#: 任务失败时 `error.code` 的归类(文档 Error Codes Reference)。
_TASK_ERROR_CATEGORY = {
    "content_policy_violation": "content_blocked",
    "invalid_parameters": "invalid_params",
    "quota_exceeded": "balance",
    "resource_exhausted": "rate_limited",
    "service_unavailable": "unavailable",
    "service_error": "unavailable",
    "generation_timeout": "unavailable",
}


def _raise_task_error(task: dict[str, Any], status: str) -> None:
    error = task.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        detail = error.get("message") or code or status
        raise upstream_error("Evolink", _TASK_ERROR_CATEGORY.get(code), detail)
    raise GenerationAdapterError("providerErr_generationFailed", vendor="Evolink", detail=error or status)


def extract_result_urls(payload: dict[str, Any]) -> list[str] | None:
    task = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(task.get("status") or "").lower()
    if status in _FAILED_STATUSES:
        error = task.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("code") or status
        else:
            detail = error or status
        raise GenerationAdapterError("providerErr_generationFailed", vendor="Evolink", detail=detail)

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
        raise GenerationAdapterError("providerErr_noResultUrl", vendor="Evolink")
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
            raise GenerationAdapterError("providerErr_unreadableInputImage", vendor="Evolink", name=path.name)
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
        raise GenerationAdapterError(
            "providerErr_uploadFailed", vendor="Evolink", detail=payload.get("msg") or payload.get("code") or "unknown error"
        )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    url = data.get("file_url") or data.get("download_url")
    if not url:
        raise GenerationAdapterError("providerErr_uploadNoUrl", vendor="Evolink")
    return str(url)


def _collect_role_urls(
    request: GenerationRequest,
    context: GenerationAdapterContext,
    roles: tuple[str, ...],
    *,
    image: bool,
    limit: int,
    too_many_key: str,
) -> list[str]:
    """一类媒体的外链 + 本地上传,按角色顺序排好。上限是**协议天花板**(图 30 / 视频 10 /
    音频 10);每个模型各自的更严上限由描述符的 source_limits 在提交前就拦掉了。"""
    urls: list[str] = []
    for role in roles:
        urls.extend(source_url_values(request.parameters, role, request.kind))
        urls.extend(_upload(path, context, image=image) for path in request.sources_for(role))
    if len(urls) > limit:
        raise GenerationAdapterError(too_many_key, vendor="Evolink", limit=limit)
    return urls


def collect_media_urls(request: GenerationRequest, context: GenerationAdapterContext) -> dict[str, list[str]]:
    """把输入素材按网关的三个数组收齐:image_urls / video_urls / audio_urls。

    视频角色排首位的是被处理的那段(见 _VIDEO_VIDEO_ROLES),数组顺序就是语义,
    不能按"先收集到的在前"排。
    """
    if request.kind == "image":
        return {
            "image_urls": _collect_role_urls(request, context, (REFERENCE_IMAGE,), image=True, limit=14, too_many_key="providerErr_tooManyImages")
        }
    return {
        "image_urls": _collect_role_urls(request, context, _VIDEO_IMAGE_ROLES, image=True, limit=30, too_many_key="providerErr_tooManyImages"),
        "video_urls": _collect_role_urls(request, context, _VIDEO_VIDEO_ROLES, image=False, limit=10, too_many_key="providerErr_tooManyVideos"),
        "audio_urls": _collect_role_urls(request, context, _VIDEO_AUDIO_ROLES, image=False, limit=10, too_many_key="providerErr_tooManyAudios"),
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
        # 音频的扩展名按音频的规矩定(mp4 容器里的音频记成 m4a,见 adapters/audio_files)。
        suffix = audio_suffix(url, content_type) if kind == "audio" else _suffix(url, kind, content_type)
        target = output_dir / f"generated-{index}{suffix}"
        staged.replace(target)
        targets.append(target)
    return targets


class EvolinkGenerationAdapter(GenerationAdapter):
    supports_resume = True
    vendor_id = "evolink"

    #: 这个网关是**纯转发**:构造请求时不看模型名,而且每一项标量都是"给了才发"
    #: (见 build_image_payload / build_video_payload)。所以目录认不出的模型也能拿到这些键。
    #: 素材角色不在其中 —— 它们决定这个模型做哪种任务,按模型变得厉害。
    _SURFACE_BY_KIND = {
        "image": ("size", "num_images"),
        "video": ("duration_seconds", "resolution", "aspect_ratio", "generate_audio"),
        # Suno 的请求体按「给了什么」选模式,不看模型名;每一格都是给了才发。
        "audio": ("lyrics", "instrumental", "title", "vocal_gender", "duration_seconds"),
    }
    surface_depends_on_model = False
    _PATH_BY_KIND = {"image": "images", "video": "videos", "audio": "audios"}

    def __init__(self, media_kind: str):
        if media_kind not in self._SURFACE_BY_KIND:
            raise ValueError(f"unsupported Evolink generation kind: {media_kind}")
        self.media_kind = media_kind

    @property
    def parameter_surface(self) -> tuple[str, ...]:
        """一个类注册了两个 kind,面要跟着实例的 media_kind 走。"""
        return self._SURFACE_BY_KIND[self.media_kind]

    def validate_request(self, request: GenerationRequest) -> None:
        # Evolink 网关的协议范围:视频 3–30 秒(Seedance 2.5 已放到 4–30,2026-09-01 文档)、
        # 最高 4K。每个模型自己的更严限制由描述符在提交前拦,这里只是兜底。
        if not request.prompt.strip():
            raise GenerationAdapterError("providerErr_promptEmpty")
        if request.kind == "audio":
            # Suno 的每项上限(描述、歌词、时长)按型号不同,由描述符在提交前拦。
            return
        if request.kind == "image":
            count = int(request.parameters.get("num_images", 1))
            if not 1 <= count <= 4:
                raise GenerationAdapterError("providerErr_numImagesRange", max=4)
        else:
            duration = int(request.parameters.get("duration_seconds", 5))
            if duration != -1 and not 3 <= duration <= 30:
                raise GenerationAdapterError("providerErr_durationRange", min=3, max=30)
            quality = str(request.parameters.get("resolution", "720p"))
            if quality not in {"480p", "720p", "1080p", "4k"}:
                raise GenerationAdapterError("providerErr_resolutionChoices", choices="480p, 720p, 1080p, 4k")

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_apiKeyMissing", vendor="Evolink")
        if request.kind != self.media_kind:
            raise GenerationAdapterError(f"Evolink {self.media_kind} adapter received a {request.kind} request")
        try:
            if self.media_kind == "audio":
                # Suno 不收任何输入素材(文档里没有参考音频 / 续写的字段)。
                payload = build_audio_payload(request)
            else:
                media = collect_media_urls(request, context)
                payload = (
                    build_image_payload(request, media["image_urls"])
                    if self.media_kind == "image"
                    else build_video_payload(
                        request, media["image_urls"], media.get("video_urls"), media.get("audio_urls")
                    )
                )
            path = f"/{self._PATH_BY_KIND[self.media_kind]}/generations"
            with self._client(context) as client:
                response = client.post(path, json=payload)
                response.raise_for_status()
                task_id = _task_id(response.json())
                if not task_id:
                    raise GenerationAdapterError("providerErr_noTaskIdDetail", vendor="Evolink", detail=str(response.json())[:200])
                return self._collect(client, f"/tasks/{task_id}", request, output_dir)
        except httpx.HTTPError as exc:
            if self.media_kind == "audio":
                raise categorized_http_error("Evolink", exc, context.api_key) from exc
            raise adapter_http_error("Evolink", exc, context.api_key) from exc

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        try:
            with self._client(context) as client:
                return self._collect(client, poll_path, request, output_dir)
        except httpx.HTTPError as exc:
            raise adapter_http_error("Evolink", exc, context.api_key) from exc

    def _client(self, context: GenerationAdapterContext) -> RetryingClient:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_apiKeyMissing", vendor="Evolink")
        headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
        return RetryingClient(base_url=resolve_base_url(context), headers=headers, timeout=60)

    def _collect(self, client: RetryingClient, poll_path: str, request: GenerationRequest, output_dir: Path) -> GenerationResult:
        """提交之后的那一半。`generate` 和 `resume` 共用。"""
        urls, terminal = poll_until_ready(
            client, poll_path, extract_audio_urls if self.media_kind == "audio" else extract_result_urls,
            interval=POLL_INTERVAL_SECONDS,
            vendor="Evolink",
        )
        return GenerationResult(
            output_paths=download_results(urls, output_dir, self.media_kind),
            usage=metering_from_request(request),
            raw_usage=terminal,
        )
