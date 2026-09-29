"""Hedra 的 Character-3 说话照片(ADR 0028 阶段 4,海外)。

官方文档(hedra.com/docs,API v3,2026-09-28 读):

- 提交 `POST /v3/models/hedra-character-3`,请求体 `{"input": {...}}`,回 202 和 `job_id`;查询 `GET /v3/jobs/{job_id}`:
  `status` IN_QUEUE / IN_PROGRESS / COMPLETED / FAILED,成片在 `outputs[].url`,失败看 `error.code` / `error.message`。
- `input`:`start_image`(≤10MB)、`audio`(每段 0.5–600 秒、≤100MB;给一串是多人,这一版只给一段)、**必填**的
  `prompt`、`aspect_ratio`(1:1 / 4:3 / 3:4 / 16:9 / 9:16 / 9:21 / 21:9)、`resolution`(540p / 720p / 1080p);
  不给 `duration_ms` 就跟着音频走。
- **图和音频都只收 `POST /v3/files` 发回的那条临时链接**(一小时内有效;改过的、外面的链接一律按外链拒),所以本地
  素材直接传,链接素材先下到本地再传 —— 不用用户配对象存储。
- 提示词是必填的:用户没写就给一句中性的「对着镜头自然地说话」,不替人编动作。
- 画幅没有 `auto`:按原图宽高挑最接近的那一档,人像不被裁掉半张脸。
- 鉴权:`Authorization: Key <key_id>:<secret>`。钱包是预付的,余额不足提交时回 402 `INSUFFICIENT_BALANCE`。

接口形状照文档写,**还没拿真实密钥跑到终态**:第一次真跑时以接口自己的报错校准。
"""

from __future__ import annotations

import math
import mimetypes
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.ai.media_transfer import download_to_path
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
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

VENDOR_LABEL = "Hedra"
BASE_URL = "https://api.hedra.com/v3"
CHARACTER_MODEL = "hedra-character-3"
POLL_INTERVAL_SECONDS = 10.0
DEFAULT_PROMPT = "A person speaking naturally to the camera."
ASPECT_RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16", "9:21", "21:9")

#: 错误码 → 失败类别(文档的 ErrorCode,仿 gRPC 状态码)。
_CODE_CATEGORY = {
    "UNAUTHORIZED": "auth",
    "PERMISSION_DENIED": "auth",
    "INSUFFICIENT_BALANCE": "balance",
    "MODERATION_FAILED": "content_blocked",
    "INVALID_ARGUMENT": "invalid_params",
    "FAILED_PRECONDITION": "invalid_params",
    "RESOURCE_EXHAUSTED": "rate_limited",
    "UNAVAILABLE": "unavailable",
    "INTERNAL": "unavailable",
    "DEADLINE_EXCEEDED": "unavailable",
}


def _category(error: Any) -> str | None:
    if not isinstance(error, dict):
        return None
    return _CODE_CATEGORY.get(str(error.get("code") or "").strip().upper())


def closest_aspect_ratio(width: int | None, height: int | None) -> str:
    """原图宽高 → 最接近的那一档(按比值的对数距离,横竖对称)。读不出尺寸就 1:1。"""
    if not width or not height:
        return "1:1"
    target = math.log(width / height)

    def distance(ratio: str) -> float:
        w, h = (int(part) for part in ratio.split(":"))
        return abs(math.log(w / h) - target)

    return min(ASPECT_RATIOS, key=distance)


def local_copy(request: GenerationRequest, role: str, work: Path) -> Path:
    """这个角色的本地文件。Hedra 只收它自己发的上传链接,所以链接素材也先下到本地。"""
    urls = source_url_values(request.parameters, role, request.kind)
    if urls:
        suffix = Path(urlsplit(str(urls[0])).path).suffix.lower()
        target = work / f"{role}{suffix}"
        download_to_path(str(urls[0]), target)
        return target
    path = request.source_for(role)
    if path is None or not path.is_file():
        raise GenerationAdapterError("providerErr_sourceMissing", vendor=VENDOR_LABEL, role=role)
    return path


def upload_file(client: Any, path: Path) -> str:
    """`POST /v3/files` → 那条一小时有效的链接(原样交回去,查询串也不能动)。"""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    response = client.post("/files", files={"file": (path.name, path.read_bytes(), mime)})
    response.raise_for_status()
    url = str((response.json() or {}).get("url") or "")
    if not url:
        raise GenerationAdapterError("providerErr_upstreamUnavailable", vendor=VENDOR_LABEL, detail=response.text[:200])
    return url


def _image_size(path: Path) -> tuple[int | None, int | None]:
    from app.media.probe import probe_media

    info = probe_media(path, measure_missing_duration=False)
    return info.get("width"), info.get("height")


def build_input(client: Any, request: GenerationRequest, work: Path) -> dict[str, Any]:
    image = local_copy(request, FIRST_FRAME, work)
    audio = local_copy(request, DRIVING_AUDIO, work)
    width, height = _image_size(image)
    resolution = str(request.parameters.get("resolution") or "").strip().lower() or "720p"
    return {
        "prompt": request.prompt.strip() or DEFAULT_PROMPT,
        "aspect_ratio": closest_aspect_ratio(width, height),
        "resolution": resolution,
        "start_image": {"source": "url", "url": upload_file(client, image)},
        "audio": {"source": "url", "url": upload_file(client, audio)},
    }


def extract_video(payload: dict[str, Any]) -> str | None:
    status = str(payload.get("status") or "").upper()
    if status == "FAILED":
        error = payload.get("error") or {}
        detail = (error.get("message") if isinstance(error, dict) else None) or "failed"
        raise upstream_error(VENDOR_LABEL, _category(error), detail)
    if status != "COMPLETED":
        return None
    for output in payload.get("outputs") or []:
        if isinstance(output, dict) and output.get("url"):
            return str(output["url"])
    raise GenerationAdapterError("providerErr_noResultUrl", vendor=VENDOR_LABEL)


class HedraVideoAdapter(GenerationAdapter):
    vendor_id = "hedra"
    media_kind = "video"
    supports_resume = True

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        model = (request.model or "").strip().lower()
        if model != CHARACTER_MODEL:
            raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL,
                                         detail=f"unknown model {request.model!r}")
        with self._client(context) as client, tempfile.TemporaryDirectory(prefix="mosael-hedra-") as folder:
            try:
                response = client.post(f"/models/{model}", json={"input": build_input(client, request, Path(folder))})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise self._http_error(exc, context) from exc
            job_id = str((response.json() or {}).get("job_id") or "").strip()
            if not job_id:
                raise GenerationAdapterError("providerErr_noTaskIdDetail", vendor=VENDOR_LABEL, detail=response.text[:200])
            return self._collect(client, f"/jobs/{job_id}", request, context, output_dir)

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        with self._client(context) as client:
            return self._collect(client, poll_path, request, context, output_dir)

    def _client(self, context: GenerationAdapterContext) -> RetryingClient:
        key = (context.api_key or "").strip()
        if not key:
            raise GenerationAdapterError("providerErr_hedraKeyMissing")
        base = (context.base_url or BASE_URL).rstrip("/")
        return RetryingClient(base_url=base, timeout=120, headers={"Authorization": f"Key {key}"})

    def _collect(self, client: Any, poll_path: str, request: GenerationRequest,
                 context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        try:
            url, terminal = poll_until_ready(client, poll_path, extract_video, interval=POLL_INTERVAL_SECONDS,
                                             vendor=VENDOR_LABEL)
            target = output_dir / "generated.mp4"
            download_to_path(url, target)
        except httpx.HTTPError as exc:
            raise self._http_error(exc, context) from exc
        return GenerationResult(output_paths=[target], usage=metering_from_request(request),
                                raw_usage={"status": terminal.get("status"), "cost": terminal.get("cost"),
                                           "currency": terminal.get("currency")})

    def _http_error(self, exc: httpx.HTTPError, context: GenerationAdapterContext) -> GenerationAdapterError:
        """先认回包里的错误码,认不出再按状态码归类。"""
        response = getattr(exc, "response", None)
        detail = http_error_detail(exc, context.api_key or None)
        category = None
        if response is not None:
            try:
                category = _category((response.json() or {}).get("error"))
            except ValueError:
                category = None
            category = category or http_status_category(response.status_code)
        if category is None:
            return GenerationAdapterError("providerErr_requestFailed", vendor=VENDOR_LABEL, detail=detail)
        return upstream_error(VENDOR_LABEL, category, detail)
