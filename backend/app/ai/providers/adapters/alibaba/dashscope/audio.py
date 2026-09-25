"""百炼(DashScope)的音频生成:Fun-Music(音乐)与 AudioGen(音效 / 环境声)。

官方文档(2026-09-25 核):
- Fun-Music:https://help.aliyun.com/zh/model-studio/fun-music-api
  (英文 https://www.alibabacloud.com/help/en/model-studio/fun-music-api)
- AudioGen(qwen-audio-3.1-tts-next):https://www.alibabacloud.com/help/en/model-studio/audio-generation-api
- 价目:https://help.aliyun.com/zh/model-studio/model-pricing

**两个都是同步接口、都只在北京地域。** 回包直接给 `output.audio.url`(24 小时有效),没有任务号 ——
所以没有回执可落,这一下 POST 也**不重试**(重发就是再生成、再收一次钱)。

文档说新的工作空间域名是 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com`,旧的
`dashscope.aliyuncs.com`「仍然完全可用」—— 连接里填的是哪个就用哪个(对话用的 compatible-mode
地址归一回原生根,和语音那边同一条判据)。

两个模型的路径和请求体都不一样,所以**参数面依赖模型名**(surface_depends_on_model 保持默认 True)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.adapters.alibaba.dashscope.speech import resolve_dashscope_native_base
from app.ai.audio_files import download_audio
from app.ai.providers.contracts.generation import (
    REFERENCE_AUDIO,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    http_error_detail,
    http_status_category,
    metering_from_request,
    source_values,
    upstream_error,
)
from app.core.http_retry import RetryingClient

VENDOR_LABEL = "阿里云百炼"
MUSIC_PATH = "/api/v1/services/audio/music/generation"
AUDIOGEN_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
MUSIC_MODELS = ("fun-music-v1", "fun-music-preview")
AUDIOGEN_MODELS = ("qwen-audio-3.1-tts-next",)
#: 文档的示例用 `--max-time 300`;一首完整的歌可能更久,宁可多等。
REQUEST_TIMEOUT_SECONDS = 600.0

#: DashScope 的错误码(`code` 字段)→ 失败类别。AudioGen 页给了前七个,余下两个是百炼通用的写法。
_CODE_CATEGORY = {
    "InvalidApiKey": "auth",
    "AccessDenied": "not_entitled",
    "Throttling": "rate_limited",
    "Throttling.RateQuota": "rate_limited",
    "Throttling.AllocationQuota": "rate_limited",
    "DataInspectionFailed": "content_blocked",
    "InvalidParameter": "invalid_params",
    "CLIENT_ERROR": "invalid_params",
    "InternalError": "unavailable",
    "Arrearage": "balance",
    "Model.AccessDenied": "not_entitled",
}


def path_for(model: str) -> str:
    name = (model or "").strip()
    if name in MUSIC_MODELS:
        return MUSIC_PATH
    if name in AUDIOGEN_MODELS:
        return AUDIOGEN_PATH
    raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL, detail=f"unknown model {name!r}")


def build_payload(request: GenerationRequest) -> dict[str, Any]:
    model = request.model.strip()
    path = path_for(model)
    fmt = request.parameters.get("output_format")
    if path == MUSIC_PATH:
        data: dict[str, Any] = {}
        if request.prompt.strip():
            data["prompt"] = request.prompt
        lyrics = str(request.parameters.get("lyrics") or "").strip()
        if lyrics:
            data["lyrics"] = lyrics
        if request.parameters.get("instrumental") is True:
            data["is_instrumental"] = True
        gender = request.parameters.get("vocal_gender")
        if gender:
            data["gender"] = str(gender)
        if fmt:
            data["format"] = str(fmt)
        return {"model": model, "input": data}
    data = {"text_prompt": request.prompt}
    # 参考音频最多 3 段:有直链给 audio_url,本地文件给 data URI(`audio_data`,文档写明两者二选一)。
    references = []
    for value in source_values(request, REFERENCE_AUDIO):
        references.append({"audio_data": value} if value.startswith("data:") else {"audio_url": value})
    if references:
        data["references"] = references
    if fmt:
        data["format"] = str(fmt)
    if request.parameters.get("seed") not in (None, ""):
        data["seed"] = int(request.parameters["seed"])
    return {"model": model, "input": data}


def _category(code: str) -> str | None:
    return _CODE_CATEGORY.get(code) or _CODE_CATEGORY.get(code.split(".", 1)[0])


def extract_audio(payload: dict[str, Any]) -> tuple[str, float]:
    """回包 → (音频地址, 计费秒数)。回包里带错误码的按类别抛。"""
    code = str(payload.get("code") or "")
    if code:
        raise upstream_error(VENDOR_LABEL, _category(code), f"{code} {payload.get('message') or ''}".strip())
    audio = ((payload.get("output") or {}).get("audio")) or {}
    url = str(audio.get("url") or "")
    if not url:
        raise GenerationAdapterError("providerErr_noAudioData", vendor=VENDOR_LABEL)
    usage = payload.get("usage") or {}
    try:
        seconds = float(usage.get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    return url, seconds


class DashScopeAudioAdapter(GenerationAdapter):
    vendor_id = "alibaba"
    media_kind = "audio"

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_apiKeyMissing", vendor=VENDOR_LABEL)
        path = path_for(request.model)
        payload = build_payload(request)
        headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
        base_url = resolve_dashscope_native_base(context.base_url)
        try:
            with RetryingClient(base_url=base_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0) as client:
                response = client.post(path, json=payload)
                body = _json_or_error(response, context)
            url, seconds = extract_audio(body)
            fallback = ".wav" if str(request.parameters.get("output_format") or "") == "wav" else ".mp3"
            target = download_audio(url, output_dir, fallback=fallback)
        except httpx.HTTPError as exc:
            raise _http_error(exc, context) from exc
        usage = metering_from_request(request)
        # 两个模型都按「生成音频的秒数」计(文档:usage.duration 就是计费时长)。
        if seconds > 0:
            usage["audio_seconds"] = seconds
        return GenerationResult(
            output_paths=[target],
            usage=usage,
            raw_usage={"request_id": body.get("request_id"), "usage": body.get("usage")},
        )


def _json_or_error(response: httpx.Response, context: GenerationAdapterContext) -> dict[str, Any]:
    """百炼把错误码放在 4xx 正文里(`{request_id, code, message}`),先读正文再看状态码。"""
    try:
        body = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise GenerationAdapterError(
            "providerErr_upstreamUnavailable", vendor=VENDOR_LABEL, detail=response.text[:200]
        ) from exc
    if response.status_code >= 400:
        code = str(body.get("code") or "")
        category = _category(code) if code else http_status_category(response.status_code)
        raise upstream_error(VENDOR_LABEL, category, f"{code} {body.get('message') or ''}".strip() or response.status_code)
    return body


def _http_error(exc: httpx.HTTPError, context: GenerationAdapterContext) -> GenerationAdapterError:
    response = getattr(exc, "response", None)
    category = http_status_category(response.status_code) if response is not None else None
    return upstream_error(VENDOR_LABEL, category, http_error_detail(exc, context.api_key))
