"""可灵音效:文生音效与视频生音效。

官方文档(2026-09-25 核;页面要在浏览器里渲染才看得到内容):
- 文生音效:https://kling.ai/document-api/api/video/audio-generation/text-to-audio
- 视频生音效:https://kling.ai/document-api/api/video/audio-generation/video-to-audio
- 错误码:https://kling.ai/document-api/api/get-started/error-codes
- 鉴权:https://kling.ai/document-api/api/get-started/authentication

两个接口都**没有模型字段**,路径就是能力。目录里的两个 id(`kling-text-to-audio` /
`kling-video-to-audio`)是我们给这两条路起的名字,Adapter 按它选路径。

**异步**,和可灵旧版视频接口同一个信封:`{code, message, data:{task_id, task_status, task_result}}`,
状态 `submitted | processing | succeed | failed`,按 `GET <同一路径>/<task_id>` 查。结果在
`task_result.audios[]`(`url_mp3` / `url_wav`);视频生音效另外还交回一段配好声的视频 —— 这是音频
生成,我们取音轨(wav 优先:剪辑时是无损的那一份)。

鉴权沿用视频那边的写法(auth_header):有 Secret Key 就签 JWT,没有就把 Key 当 Bearer 直接用 ——
文档现在推荐的正是后者(控制台生成的 API Key)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.ai.audio_files import download_audio
from app.ai.providers.adapters.kuaishou.kling.video import KLING_BASE, auth_header
from app.ai.providers.contracts.generation import (
    SOURCE_VIDEO,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    categorized_http_error,
    metering_from_request,
    poll_until_ready,
    source_url_values,
    upstream_error,
)
from app.core.http_retry import RetryingClient

VENDOR_LABEL = "Kling"
TEXT_TO_AUDIO = "kling-text-to-audio"
VIDEO_TO_AUDIO = "kling-video-to-audio"
_PATHS = {
    TEXT_TO_AUDIO: "/v1/audio/text-to-audio",
    VIDEO_TO_AUDIO: "/v1/audio/video-to-audio",
}
#: 文生音效的时长是必填的(3.0–10.0 秒)。没给时用描述符声明的默认值 —— 那是界面上摆出来的初值,
#: 不是这里另编的数。
DEFAULT_SFX_SECONDS = 5

#: 错误码 → 失败类别(错误码页的表)。
_CODE_CATEGORY = {
    1000: "auth", 1001: "auth", 1002: "auth", 1003: "auth", 1004: "auth",
    1100: "auth", 1101: "balance", 1102: "balance", 1103: "not_entitled",
    1200: "invalid_params", 1201: "invalid_params", 1202: "invalid_params", 1203: "invalid_params",
    1300: "content_blocked", 1301: "content_blocked",
    1302: "rate_limited", 1303: "rate_limited", 1304: "rate_limited",
    5000: "unavailable", 5001: "unavailable", 5002: "unavailable",
}


def path_for(model: str) -> str:
    path = _PATHS.get((model or "").strip())
    if path is None:
        raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL, detail=f"unknown model {model!r}")
    return path


def build_payload(request: GenerationRequest) -> dict[str, Any]:
    model = request.model.strip()
    if model == TEXT_TO_AUDIO:
        duration = request.parameters.get("duration_seconds")
        return {
            "prompt": request.prompt,
            "duration": float(duration if duration is not None else DEFAULT_SFX_SECONDS),
        }
    path_for(model)
    urls = source_url_values(request.parameters, SOURCE_VIDEO, request.kind)
    if not urls:
        # 描述符把 source_video 标成 url_only:本地素材在提交前已经换成了直链(见 operations
        # 的 public_links)。走到这里还没有链接,只可能是绕过了那道校验的直接调用。
        raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL, detail="video_url is required")
    payload: dict[str, Any] = {"video_url": urls[0]}
    if request.prompt.strip():
        payload["sound_effect_prompt"] = request.prompt
    bgm = str(request.parameters.get("bgm_prompt") or "").strip()
    if bgm:
        payload["bgm_prompt"] = bgm
    if request.parameters.get("asmr_mode") is not None:
        payload["asmr_mode"] = bool(request.parameters["asmr_mode"])
    return payload


def _raise_for_code(payload: dict[str, Any]) -> None:
    code = payload.get("code")
    if code in (None, 0):
        return
    try:
        number = int(code)
    except (TypeError, ValueError):
        number = -1
    raise upstream_error(VENDOR_LABEL, _CODE_CATEGORY.get(number), f"{code} {payload.get('message') or ''}".strip())


def extract_audio(payload: dict[str, Any]) -> dict[str, Any] | None:
    """查询回包:成功回第一条音频,还在跑回 None,失败按原因抛。"""
    _raise_for_code(payload)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(data.get("task_status") or "").lower()
    if status in ("submitted", "processing", ""):
        return None
    if status == "failed":
        raise upstream_error(VENDOR_LABEL, None, data.get("task_status_msg") or status)
    if status != "succeed":
        return None
    for audio in ((data.get("task_result") or {}).get("audios")) or []:
        if isinstance(audio, dict) and (audio.get("url_wav") or audio.get("url_mp3")):
            return audio
    raise GenerationAdapterError("providerErr_noResultUrl", vendor=VENDOR_LABEL)


class KlingAudioAdapter(GenerationAdapter):
    vendor_id = "kuaishou"
    media_kind = "audio"
    supports_resume = True

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        path = path_for(request.model)
        payload = build_payload(request)
        try:
            with self._client(context) as client:
                submit = client.post(path, json=payload)
                submit.raise_for_status()
                body = submit.json()
                _raise_for_code(body)
                task_id = str(((body.get("data") or {}).get("task_id")) or "").strip()
                if not task_id:
                    raise GenerationAdapterError("providerErr_noTaskId", vendor=VENDOR_LABEL)
                return self._collect(client, f"{path}/{task_id}", request, output_dir)
        except httpx.HTTPError as exc:
            raise _http_error(exc, context) from exc

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        try:
            with self._client(context) as client:
                return self._collect(client, poll_path, request, output_dir)
        except httpx.HTTPError as exc:
            raise _http_error(exc, context) from exc

    def _client(self, context: GenerationAdapterContext) -> RetryingClient:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_klingKeyMissing")
        headers = {"Authorization": auth_header(context), "Content-Type": "application/json"}
        return RetryingClient(base_url=(context.base_url or KLING_BASE).rstrip("/"), timeout=60, headers=headers, follow_redirects=True)

    def _collect(self, client: RetryingClient, poll_path: str, request: GenerationRequest, output_dir: Path) -> GenerationResult:
        audio, terminal = poll_until_ready(client, poll_path, extract_audio, vendor=VENDOR_LABEL)
        url = str(audio.get("url_wav") or audio.get("url_mp3"))
        target = download_audio(url, output_dir, fallback=".wav" if audio.get("url_wav") else ".mp3")
        usage = metering_from_request(request)
        raw = terminal.get("data") if isinstance(terminal.get("data"), dict) else {}
        return GenerationResult(
            output_paths=[target],
            usage=usage,
            raw_usage={
                "task_id": raw.get("task_id"),
                "final_unit_deduction": raw.get("final_unit_deduction"),
                "final_balance_deduction": raw.get("final_balance_deduction"),
            },
        )


def _http_error(exc: httpx.HTTPError, context: GenerationAdapterContext) -> GenerationAdapterError:
    """可灵的 4xx 正文里有错误码,比状态码说得清 —— 先读正文。"""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            _raise_for_code(response.json())
        except GenerationAdapterError as categorized:
            return categorized
        except ValueError:
            pass
    return categorized_http_error(VENDOR_LABEL, exc, context.api_key)
