"""HeyGen 的说话照片与对口型(ADR 0028 阶段 4,海外)。

官方文档(developers.heygen.com,v3,2026-09-28 读):

- **说话照片**(Audio to Video 的 `type: "image"`):`POST /v3/videos`,`image` 收 `{type: url}` / `{type: asset_id}` /
  `{type: base64, media_type, data}`(png / jpeg,<2K、≤50MB),配音给 `audio_url`(公网链接)或 `audio_asset_id`
  (mp3 / wav);可选 `motion_prompt`(动作)、`resolution`(720p / 1080p)、`aspect_ratio`(`auto` 跟着原图走,文档推荐)。
  渲染引擎默认 Avatar IV。音频上限文档两处说法不一(「Audio to Video」页写 30 分钟,「Usage Limits」页写头像输入
  最长 10 分钟),描述符按严的那个写 600 秒。查询 `GET /v3/videos/{video_id}`:`status` pending / processing /
  completed / failed,成片在 `video_url`,失败看 `failure_code` / `failure_message`。
- **对口型**(Lipsync):`POST /v3/lipsyncs`,`video`、`audio` 都收 `{type: url}` / `{type: asset_id}`,`mode` speed /
  precision;`enable_dynamic_duration` 默认开 —— 成片长度跟着新配音走。查询 `GET /v3/lipsyncs/{id}`:`status`
  pending / running / completed / failed,成片在 `video_url`,失败看 `failure_message`。
- **本地素材走直传**(`POST /v3/assets/direct-uploads` 拿预签名地址 → PUT 字节 → `POST /v3/assets/{id}/complete`,
  单个文件最大 200MiB),**不用用户配对象存储**;直传只收 png / jpeg / mp4 / webm / mp3 / wav,别的配音先转 mp3。
  图片直接内联 Base64,少一趟上传。
- 鉴权:`X-Api-Key` 头。错误体 `{"error": {"code", "message"}}`。

接口形状照文档写,**还没拿真实密钥跑到终态**:第一次真跑时以接口自己的报错校准。
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.ai.media_transfer import download_to_path, put_to_presigned_url
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    SOURCE_VIDEO,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
    source_url_values,
)
from app.ai.providers.adapters.shared.errors import http_error_detail, http_status_category, upstream_error
from app.ai.providers.adapters.shared.polling import poll_until_ready
from app.core.http_retry import RetryingClient

VENDOR_LABEL = "HeyGen"
BASE_URL = "https://api.heygen.com"
AVATAR_MODEL = "heygen-avatar-iv"
LIPSYNC_MODEL = "heygen-lipsync"
VIDEOS_PATH = "/v3/videos"
LIPSYNCS_PATH = "/v3/lipsyncs"
POLL_INTERVAL_SECONDS = 10.0

#: 直传收的格式(文档「Upload Assets」),后缀 → 声明的 MIME。
UPLOAD_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

#: 错误码 → 失败类别(文档「Error Codes」)。查询回包的 `failure_code` 用的是同一套词。
_CODE_CATEGORY = {
    "unauthorized": "auth",
    "forbidden": "auth",
    "insufficient_api_key_scope": "auth",
    "insufficient_credit": "balance",
    "quota_exceeded": "balance",
    "trial_limit_exceeded": "balance",
    "subscription_required": "not_entitled",
    "plan_upgrade_required": "not_entitled",
    "rate_limit_exceeded": "rate_limited",
    "content_policy_violation": "content_blocked",
    "invalid_parameter": "invalid_params",
    "image_processing_failed": "invalid_params",
    "download_failed": "invalid_params",
    "no_audio_track": "invalid_params",
    "video_too_long": "invalid_params",
    "internal_error": "unavailable",
    "service_unavailable": "unavailable",
    "gateway_timeout": "unavailable",
}


def _category(code: Any) -> str | None:
    return _CODE_CATEGORY.get(str(code or "").strip().lower())


def _link(request: GenerationRequest, role: str) -> str | None:
    """这个角色有没有能原样交给 HeyGen 去下的链接(界面粘的外链,或从直链导入的素材)。"""
    urls = source_url_values(request.parameters, role, request.kind)
    if urls:
        return str(urls[0])
    for item in request.sources:
        if item.role == role and item.public_url:
            return item.public_url
    return None


def _path(request: GenerationRequest, role: str) -> Path:
    path = request.source_for(role)
    if path is None or not path.is_file():
        raise GenerationAdapterError("providerErr_sourceMissing", vendor=VENDOR_LABEL, role=role)
    return path


def image_field(request: GenerationRequest, work: Path) -> dict[str, Any]:
    """人像:有链接给链接,本地的内联 Base64(不是 png / jpeg 的先转 png)。"""
    link = _link(request, FIRST_FRAME)
    if link:
        return {"type": "url", "url": link}
    path = _path(request, FIRST_FRAME)
    if path.suffix.lower() not in IMAGE_TYPES:
        from app.media.vendor_formats import still_png

        path = still_png(path, work / "portrait.png")
    return {"type": "base64", "media_type": IMAGE_TYPES[path.suffix.lower()],
            "data": base64.b64encode(path.read_bytes()).decode("ascii")}


def uploadable(path: Path, role: str, work: Path) -> Path:
    """直传收不下的格式先转:配音转 mp3;视频 HeyGen 只收 mp4 / webm,别的说清楚(素材库导入时已把 mov 换成 mp4)。"""
    if path.suffix.lower() in UPLOAD_TYPES:
        return path
    if role == DRIVING_AUDIO:
        from app.media.vendor_formats import speech_mp3

        return speech_mp3(path, work / "voice.mp3")
    raise GenerationAdapterError("providerErr_heygenVideoFormat", format=path.suffix.lower() or "?")


def _data(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    data = (response.json() or {}).get("data")
    if not isinstance(data, dict):
        raise GenerationAdapterError("providerErr_upstreamUnavailable", vendor=VENDOR_LABEL, detail=response.text[:200])
    return data


def upload_asset(client: Any, path: Path) -> str:
    """直传三步:要预签名地址 → PUT 字节(不带 Key)→ 完成。回 asset_id。"""
    content_type = UPLOAD_TYPES[path.suffix.lower()]
    data = path.read_bytes()
    slot = _data(client.post("/v3/assets/direct-uploads",
                             json={"filename": path.name, "content_type": content_type, "size_bytes": len(data)}))
    asset_id = str(slot.get("asset_id") or "")
    if not asset_id or not slot.get("upload_url"):
        raise GenerationAdapterError("providerErr_upstreamUnavailable", vendor=VENDOR_LABEL, detail=str(slot)[:200])
    put_to_presigned_url(str(slot["upload_url"]), data, slot.get("upload_headers") or {})
    _data(client.post(f"/v3/assets/{asset_id}/complete", json={}))
    return asset_id


def _media(client: Any, request: GenerationRequest, role: str, work: Path) -> dict[str, Any]:
    """对口型那两格:`{type: url}` 或传上去的 `{type: asset_id}`。"""
    link = _link(request, role)
    if link:
        return {"type": "url", "url": link}
    return {"type": "asset_id", "asset_id": upload_asset(client, uploadable(_path(request, role), role, work))}


def build_avatar_body(client: Any, request: GenerationRequest, work: Path) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "image", "image": image_field(request, work), "aspect_ratio": "auto"}
    link = _link(request, DRIVING_AUDIO)
    if link:
        body["audio_url"] = link
    else:
        body["audio_asset_id"] = upload_asset(client, uploadable(_path(request, DRIVING_AUDIO), DRIVING_AUDIO, work))
    resolution = str(request.parameters.get("resolution") or "").strip().lower()
    if resolution:
        body["resolution"] = resolution
    if request.prompt.strip():
        body["motion_prompt"] = request.prompt.strip()
    return body


def build_lipsync_body(client: Any, request: GenerationRequest, work: Path) -> dict[str, Any]:
    """精度模式:对口型要进成片,不是预览草稿(speed 是文档说的「快速出草稿」)。"""
    return {
        "video": _media(client, request, SOURCE_VIDEO, work),
        "audio": _media(client, request, DRIVING_AUDIO, work),
        "mode": "precision",
    }


def extract_video(payload: dict[str, Any]) -> str | None:
    """两个查询接口同一个形状:做完回成片地址,还在跑回 None,失败按 failure_code 归类抛。"""
    data = payload.get("data") or {}
    status = str(data.get("status") or "").lower()
    if status == "failed":
        detail = data.get("failure_message") or data.get("failure_code") or "failed"
        raise upstream_error(VENDOR_LABEL, _category(data.get("failure_code")), detail)
    if status != "completed":
        return None
    url = data.get("video_url")
    if not url:
        raise GenerationAdapterError("providerErr_noResultUrl", vendor=VENDOR_LABEL)
    return str(url)


class HeyGenVideoAdapter(GenerationAdapter):
    vendor_id = "heygen"
    media_kind = "video"
    supports_resume = True

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        model = (request.model or "").strip().lower()
        if model not in (AVATAR_MODEL, LIPSYNC_MODEL):
            raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL,
                                         detail=f"unknown model {request.model!r}")
        with self._client(context) as client, tempfile.TemporaryDirectory(prefix="mosael-heygen-") as folder:
            work = Path(folder)
            try:
                if model == AVATAR_MODEL:
                    submitted = _data(client.post(VIDEOS_PATH, json=build_avatar_body(client, request, work)))
                    poll_path = f"{VIDEOS_PATH}/{submitted.get('video_id') or ''}"
                else:
                    submitted = _data(client.post(LIPSYNCS_PATH, json=build_lipsync_body(client, request, work)))
                    poll_path = f"{LIPSYNCS_PATH}/{submitted.get('lipsync_id') or ''}"
            except httpx.HTTPError as exc:
                raise self._http_error(exc, context) from exc
            if poll_path.endswith("/"):
                raise GenerationAdapterError("providerErr_noTaskIdDetail", vendor=VENDOR_LABEL, detail=str(submitted)[:200])
            return self._collect(client, poll_path, request, context, output_dir)

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        with self._client(context) as client:
            return self._collect(client, poll_path, request, context, output_dir)

    def _client(self, context: GenerationAdapterContext) -> RetryingClient:
        key = (context.api_key or "").strip()
        if not key:
            raise GenerationAdapterError("providerErr_heygenKeyMissing")
        base = (context.base_url or BASE_URL).rstrip("/")
        return RetryingClient(base_url=base, timeout=120, headers={"X-Api-Key": key})

    def _collect(self, client: Any, poll_path: str, request: GenerationRequest,
                 context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        try:
            url, terminal = poll_until_ready(client, poll_path, extract_video, interval=POLL_INTERVAL_SECONDS,
                                             vendor=VENDOR_LABEL)
            target = output_dir / "generated.mp4"
            download_to_path(url, target)
        except httpx.HTTPError as exc:
            raise self._http_error(exc, context) from exc
        data = terminal.get("data") or {}
        return GenerationResult(output_paths=[target], usage=metering_from_request(request),
                                raw_usage={"status": data.get("status"), "duration": data.get("duration")})

    def _http_error(self, exc: httpx.HTTPError, context: GenerationAdapterContext) -> GenerationAdapterError:
        """先认回包里的错误码,认不出再按状态码归类。"""
        response = getattr(exc, "response", None)
        detail = http_error_detail(exc, context.api_key or None)
        category = None
        if response is not None:
            try:
                category = _category(((response.json() or {}).get("error") or {}).get("code"))
            except ValueError:
                category = None
            category = category or http_status_category(response.status_code)
        if category is None:
            return GenerationAdapterError("providerErr_requestFailed", vendor=VENDOR_LABEL, detail=detail)
        return upstream_error(VENDOR_LABEL, category, detail)
