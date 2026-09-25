"""MiniMax 音乐生成(music-3.0 / music-2.6 / music-cover)。

官方文档(2026-09-25 核):
- 音乐生成:https://platform.minimax.cn/docs/api-reference/music-generation
  (国际站 https://platform.minimax.io/docs/api-reference/music-generation)
- 错误码:https://platform.minimax.cn/docs/api-reference/errorcode
- 限流:https://platform.minimax.cn/docs/guides/rate-limits

**2026-08-20 起不再向新用户开放。** 文档原话:「付费接口(音乐生成、歌词生成)不再面向新用户提供服务,
历史付费用户可继续使用现有 API 服务」。接口仍在(没有密钥的请求照样回 1004),所以对老用户照接;
新账号会在对面被拒,拒绝码由下面那张表翻成人话。

**同步接口。** `POST /v1/music_generation`,音频就在同一个回包里(`data.audio`,十六进制)——
没有任务号,也就没有回执可落、没有「接着取」。所以这一下 POST **不重试**:读超时之后重发,
等于让对面再写一首、再收一次钱。

**错误以 HTTP 200 返回**,真正的结果在 `base_resp.status_code`(0 = 成功)。

**两种输出**:`output_format` 可以是 `url` 或 `hex`,但文档只写明了 hex 放在 `data.audio`,没写 url
放在哪 —— 所以这里用文档写明的 hex(默认值),不去猜 url 的位置。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from app.ai.audio_files import write_inline_audio
from app.ai.providers.contracts.generation import (
    REFERENCE_AUDIO,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    categorized_http_error,
    metering_from_request,
    source_url_values,
    upstream_error,
)
from app.core.http_retry import RetryingClient

BASE_URL = "https://api.minimaxi.com"
PATH = "/v1/music_generation"
VENDOR_LABEL = "MiniMax"
#: 一首歌要生成一两分钟;文档没给上限。宁可多等,也不要在对面生成完之前掐断(掐断也照样扣费)。
REQUEST_TIMEOUT_SECONDS = 600.0
COVER_MODELS = ("music-cover",)
#: 输出:mp3、44.1kHz、256kbps —— 三个值都在文档的可选清单里(sample_rate / bitrate / format)。
AUDIO_SETTING = {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"}

#: base_resp.status_code → 失败类别。表来自音乐生成页与错误码页。
_CODE_CATEGORY = {
    1000: "unavailable",
    1001: "unavailable",
    1002: "rate_limited",
    1004: "auth",
    1008: "balance",
    1024: "unavailable",
    1026: "content_blocked",
    1027: "content_blocked",
    1033: "unavailable",
    1039: "invalid_params",
    1041: "rate_limited",
    1042: "invalid_params",
    2013: "invalid_params",
    2045: "rate_limited",
    2049: "auth",
    2056: "balance",
}


def _reference_audio(request: GenerationRequest) -> dict[str, str]:
    """翻唱的那一首:有公网直链就给 `audio_url`,本地文件就给 `audio_base64`(两者只能给一个)。"""
    urls = source_url_values(request.parameters, REFERENCE_AUDIO, request.kind)
    if urls:
        return {"audio_url": urls[0]}
    path = request.source_for(REFERENCE_AUDIO)
    if path is None:
        return {}
    return {"audio_base64": base64.b64encode(path.read_bytes()).decode("ascii")}


def build_payload(request: GenerationRequest) -> dict[str, Any]:
    """宿主请求 → MiniMax 的请求体。

    - 纯音乐 → `is_instrumental: true`(这时描述必填,提交前已经拦过);
    - 有人声但没给歌词 → `lyrics_optimizer: true`,文档:「为 true 且 lyrics 为空时,根据 prompt 自动生成歌词」;
    - 翻唱模型 → 附上参考音频。
    """
    model = request.model.strip()
    payload: dict[str, Any] = {
        "model": model,
        "output_format": "hex",
        "audio_setting": dict(AUDIO_SETTING),
    }
    if request.prompt.strip():
        payload["prompt"] = request.prompt
    lyrics = str(request.parameters.get("lyrics") or "").strip()
    if lyrics:
        payload["lyrics"] = lyrics
    if model in COVER_MODELS:
        payload.update(_reference_audio(request))
        return payload
    if request.parameters.get("instrumental") is True:
        payload["is_instrumental"] = True
    elif not lyrics:
        payload["lyrics_optimizer"] = True
    return payload


def extract_audio_hex(payload: dict[str, Any]) -> str:
    """回包 → 十六进制音频。`base_resp.status_code` 不为 0 时按上面那张表归类抛出。"""
    base = payload.get("base_resp") or {}
    code = base.get("status_code")
    if code not in (None, 0):
        try:
            number = int(code)
        except (TypeError, ValueError):
            number = -1
        raise upstream_error(VENDOR_LABEL, _CODE_CATEGORY.get(number), f"{code} {base.get('status_msg') or ''}".strip())
    data = payload.get("data") or {}
    audio = data.get("audio")
    if not audio:
        raise GenerationAdapterError("providerErr_noAudioData", vendor=VENDOR_LABEL)
    return str(audio)


def _usage(request: GenerationRequest, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """用量:按首一条;`extra_info.music_duration` 的单位文档没写(示例数值对得上毫秒),所以不拿它
    冒充秒数 —— 秒数由运行器按探测到的真实时长补。原样记进 raw 以便对账。"""
    extra = payload.get("extra_info") if isinstance(payload.get("extra_info"), dict) else {}
    raw = {"extra_info": extra, "trace_id": payload.get("trace_id")}
    return metering_from_request(request), raw


class MiniMaxMusicAdapter(GenerationAdapter):
    vendor_id = "minimax"
    media_kind = "audio"

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_apiKeyMissing", vendor=VENDOR_LABEL)
        base_url = (context.base_url or BASE_URL).rstrip("/")
        # 档案里常填的是对话用的 `.../v1`;音乐接口的路径自带 /v1,截掉免得拼成 /v1/v1。
        if base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")]
        headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
        try:
            with RetryingClient(base_url=base_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0) as client:
                response = client.post(PATH, json=build_payload(request))
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise categorized_http_error(VENDOR_LABEL, exc, context.api_key) from exc
        audio = extract_audio_hex(payload)
        try:
            target = write_inline_audio(audio, output_dir, encoding="hex", suffix=".mp3")
        except ValueError as exc:
            raise GenerationAdapterError("providerErr_noAudioData", vendor=VENDOR_LABEL) from exc
        usage, raw = _usage(request, payload)
        return GenerationResult(output_paths=[target], usage=usage, raw_usage=raw)
