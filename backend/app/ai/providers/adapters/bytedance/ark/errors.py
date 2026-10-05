"""火山方舟回的失败怎么说成人话 —— 主要是**内容审核**那一类。

方舟的审核码是 `<Input|Output><Text|Image|Video|Audio>SensitiveContentDetected[.<细类>]`(提交时回 400,生成完才
判的在任务终态的 `error.code` 里)。细类 `PrivacyInformation` 是「可能有真人」:写实人像当首帧、当参考图就会撞上。
此前用户看到的是「ARK 请求失败:Client error '400 Bad Request' f…」—— 看不出是服务商的审核,也不知道换一家就能出
(真跑过:同一张写实首帧,Evolink 上的 Seedance 照常出片)。

审核之外的失败照旧:提交时是「请求失败」加原文,任务终态是「生成失败」加服务商给的码和原因。
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.ai.providers.adapters.shared.errors import adapter_http_error
from app.ai.providers.contracts.generation import GenerationAdapterError, sanitize_adapter_error
from app.core.i18n import fragment

VENDOR = "ARK"

_MODERATION = re.compile(r"^(Input|Output)(Text|Image|Video|Audio)SensitiveContentDetected(?:\.(\w+))?$")
#: 审核码里是哪一样被拦:输入的提示词 / 图片 / 视频 / 音频,还是生成出来的那一份。
_PARTS = {
    ("Input", "Text"): "arkPart_inputText",
    ("Input", "Image"): "arkPart_inputImage",
    ("Input", "Video"): "arkPart_inputVideo",
    ("Input", "Audio"): "arkPart_inputAudio",
    ("Output", "Text"): "arkPart_outputText",
    ("Output", "Image"): "arkPart_outputImage",
    ("Output", "Video"): "arkPart_outputVideo",
    ("Output", "Audio"): "arkPart_outputAudio",
}
#: 真人那一类该换哪家:视频指 Evolink 上的 Seedance(真跑核对过不拦),图像指 Evolink 上的图像模型。
_ALTERNATIVES = {"video": "arkAlternative_video", "image": "arkAlternative_image"}


def moderation_error(code: str, message: str, *, kind: str) -> GenerationAdapterError | None:
    """方舟的审核码 → 一句人话;不是审核码回 None。`kind` 是这次生成的种类(真人那一类据此建议换哪家)。"""
    matched = _MODERATION.match(code.strip())
    if matched is None:
        return None
    direction, medium, subtype = matched.groups()
    part = fragment(_PARTS[(direction, medium)])
    detail = sanitize_adapter_error(f"{code}: {message}".strip(": "), None)[:300]
    if subtype == "PrivacyInformation":
        return GenerationAdapterError(
            "providerErr_arkPrivacyBlocked", part=part, alternative=fragment(_ALTERNATIVES.get(kind, "arkAlternative_video")),
            detail=detail,
        )
    return GenerationAdapterError("providerErr_arkContentBlocked", part=part, detail=detail)


def _error_body(payload: Any) -> tuple[str, str]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return "", ""
    return str(error.get("code") or ""), str(error.get("message") or "")


def ark_http_error(exc: httpx.HTTPError, credential: str | None, *, kind: str) -> GenerationAdapterError:
    """提交时方舟回了错:审核码说人话,别的照旧是「请求失败」加回包原文。"""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            code, message = _error_body(response.json())
        except ValueError:
            code, message = "", ""
        if code:
            blocked = moderation_error(code, message, kind=kind)
            if blocked is not None:
                return blocked
    return adapter_http_error(VENDOR, exc, credential)


def ark_task_failed(payload: dict[str, Any], status: str, *, kind: str) -> GenerationAdapterError:
    """任务落了失败的终态:审核码说人话,别的带上服务商给的码和原因(此前只说了一个 `failed`)。"""
    code, message = _error_body(payload)
    blocked = moderation_error(code, message, kind=kind) if code else None
    if blocked is not None:
        return blocked
    detail = f"{status} · {code}: {message}" if code else status
    return GenerationAdapterError("providerErr_generationFailed", vendor=VENDOR, detail=sanitize_adapter_error(detail, None)[:500])
