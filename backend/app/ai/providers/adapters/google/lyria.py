"""Google Lyria 音乐生成(Gemini API 的 generateContent)。

官方文档(2026-09-25 核):
- 音乐生成指南(generateContent 版):https://ai.google.dev/gemini-api/docs/generate-content/music-generation
- 模型页:https://ai.google.dev/gemini-api/docs/models/lyria-3.5
  (另有 lyria-3-clip-preview / lyria-3-pro-preview)
- 价目:https://ai.google.dev/gemini-api/docs/pricing

**同步接口,没有远端任务。** `POST /v1beta/models/{model}:generateContent`,音频以 base64 放在
回包 `candidates[0].content.parts[].inlineData` 里,同一个回包里还有文字(歌词或曲式说明)——
文档特意说**别假定歌词在前**,所以逐个 part 找。没有任务号可落,也就没有「接着取」(ADR 0019
管的是异步任务;同步这一下花的钱,线程死了就是没了,这是接口的形状,不是我们能补的)。

**没有结构化参数。** 时长、BPM、种子、负向提示、张数一个都没有 —— 文档原话是「通过提示词来
控制」:段落标签([Verse] / [Chorus])、时间戳、自带歌词、「Instrumental only, no vocals」都写进
提示词。所以本 Adapter 只收两项宿主参数,并按文档的写法拼进提示词:

- `lyrics`:用户自己的歌词,原样接在描述后面(歌词自带段落标签);
- `instrumental`:在描述末尾加上文档给的那句 `Instrumental only, no vocals.`。

没设就不拼 —— 用户不动它们时,发出去的提示词一个字都不变(见 ADR 0015 的参数面约定)。

**不重试这一下 POST。** 它是同步的付费生成:读超时之后重发,等于让对面再生成、再收一次钱。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.contracts.generation import (
    REFERENCE_IMAGE,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    categorized_http_error,
    image_file_to_base64,
    metering_from_request,
    upstream_error,
)
from app.ai.audio_files import audio_suffix
from app.core.http_retry import RetryingClient

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL_ID = "lyria-3.5"
VENDOR_LABEL = "Google Lyria"
#: 一首完整的歌要生成一两分钟;文档没给延迟上限,宁可等久一点也不要在对面生成完之前掐断。
REQUEST_TIMEOUT_SECONDS = 600.0
#: 文档给的「只要纯音乐」的写法。
INSTRUMENTAL_SENTENCE = "Instrumental only, no vocals."
#: 文档:最多 10 张图作为输入(图生音乐)。描述符的 source_limits 在提交前拦,这里只兜底。
MAX_IMAGES = 10

#: Gemini 在回包里说「拦下了」的几种方式(promptFeedback.blockReason、candidate.finishReason)。
_BLOCKED_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}


def compose_prompt(request: GenerationRequest) -> str:
    """把宿主的两项参数按文档的写法拼进提示词。都没设时原样返回。"""
    parts = [request.prompt.strip()] if request.prompt.strip() else []
    if request.parameters.get("instrumental") is True:
        parts.append(INSTRUMENTAL_SENTENCE)
    lyrics = str(request.parameters.get("lyrics") or "").strip()
    if lyrics:
        parts.append(lyrics)
    return "\n\n".join(parts)


def build_payload(request: GenerationRequest) -> dict[str, Any]:
    """generateContent 的请求体:一段文字,外加(可选的)参考图。

    `generationConfig` 不发 —— 文档里最小的请求就是只有 `contents`,默认出 MP3。"""
    parts: list[dict[str, Any]] = [{"text": compose_prompt(request)}]
    images = request.sources_for(REFERENCE_IMAGE)
    if len(images) > MAX_IMAGES:
        raise GenerationAdapterError("providerErr_tooManyImages", vendor=VENDOR_LABEL, limit=MAX_IMAGES)
    for path in images:
        mime_type, data = image_file_to_base64(path)
        parts.append({"inline_data": {"mime_type": mime_type, "data": data}})
    return {"contents": [{"parts": parts}]}


def extract_audio(payload: dict[str, Any]) -> tuple[bytes, str, str]:
    """回包 → (音频字节, mime, 同回的文字)。没有音频时按回包说的原因抛。"""
    feedback = payload.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise upstream_error(VENDOR_LABEL, "content_blocked", feedback.get("blockReason"))
    texts: list[str] = []
    finish = ""
    for candidate in payload.get("candidates") or []:
        finish = finish or str(candidate.get("finishReason") or "")
        for part in ((candidate.get("content") or {}).get("parts")) or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if isinstance(inline, dict) and inline.get("data"):
                mime = str(inline.get("mimeType") or inline.get("mime_type") or "audio/mpeg")
                if mime.startswith("audio/"):
                    texts.extend(
                        str(other.get("text")) for other in candidate["content"]["parts"] if other.get("text")
                    )
                    return base64.b64decode(inline["data"]), mime, "\n".join(texts)
    if finish in _BLOCKED_FINISH:
        raise upstream_error(VENDOR_LABEL, "content_blocked", finish)
    raise GenerationAdapterError("providerErr_noAudioData", vendor=VENDOR_LABEL)


def _scrubbed(payload: dict[str, Any]) -> dict[str, Any]:
    """回包去掉音频本身再记进用量 —— 几兆字节的 base64 不该落进数据库。"""
    usage = payload.get("usageMetadata")
    return {"usageMetadata": usage} if isinstance(usage, dict) else {}


class LyriaAdapter(GenerationAdapter):
    vendor_id = "google"
    media_kind = "audio"
    #: 请求构造不看模型名,而且两项都是「设了才拼」—— 目录认不出的 Lyria 型号也能拿到这两格。
    parameter_surface = ("lyrics", "instrumental")
    surface_depends_on_model = False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_apiKeyMissing", vendor=VENDOR_LABEL)
        model = (request.model or context.configured_model_id or DEFAULT_MODEL_ID).strip()
        base_url = (context.base_url or GEMINI_BASE).rstrip("/")
        headers = {"x-goog-api-key": context.api_key, "Content-Type": "application/json"}
        try:
            with RetryingClient(base_url=base_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0) as client:
                response = client.post(f"/models/{model}:generateContent", json=build_payload(request))
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise categorized_http_error(VENDOR_LABEL, exc, context.api_key) from exc
        audio, mime, text = extract_audio(payload)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"generated{audio_suffix('', mime)}"
        target.write_bytes(audio)
        raw = _scrubbed(payload)
        if text:
            raw["text"] = text[:4000]
        return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage=raw)
