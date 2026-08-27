from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.base import (
    REFERENCE_IMAGE,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    metering_from_request,
    provider_http_error,
)

"""
OpenAI Images-compatible adapter:
POST /images/generations → b64_json/url → local image file.
"""

OPENAI_BASE = "https://api.openai.com/v1"


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "prompt": request.prompt,
        "n": int(request.parameters.get("num_images", 1)),
    }
    size = request.parameters.get("size")
    if size:
        payload["size"] = str(size).replace("*", "x")
    for key in ("quality", "background", "output_format", "moderation"):
        value = request.parameters.get(key)
        if value:
            payload[key] = value
    return payload


def build_edit_fields(request: GenerationRequest) -> dict[str, str]:
    fields: dict[str, str] = {
        "model": request.model,
        "prompt": request.prompt,
        "n": str(int(request.parameters.get("num_images", 1))),
    }
    size = request.parameters.get("size")
    if size:
        fields["size"] = str(size).replace("*", "x")
    for key in ("quality", "background", "output_format", "moderation", "input_fidelity"):
        value = request.parameters.get(key)
        if value:
            fields[key] = str(value)
    return fields


def extract_image_bytes(payload: dict[str, Any]) -> bytes:
    data = payload.get("data") or []
    if not data or not isinstance(data[0], dict):
        raise ProviderError("Provider returned no image data")
    first = data[0]
    if first.get("b64_json"):
        return base64.b64decode(str(first["b64_json"]))
    raise ProviderError("Provider returned a URL result where inline image data was expected")


class OpenAIImageProvider(GenerationProvider):
    kind = "image"

    def __init__(self, name: str = "openai") -> None:
        self.name = name

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("OpenAI API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or OPENAI_BASE).rstrip("/")
        headers = {"Authorization": f"Bearer {context.api_key}"}
        try:
            with RetryingClient(base_url=base_url, timeout=120, headers=headers) as client:
                references = request.sources_for(REFERENCE_IMAGE)
                if references:
                    files = []
                    handles = []
                    try:
                        # 张数由描述符管(见 domain/generation/catalog 的 source_limits),
                        # 提交前那道统一校验已经拦过。这里再截一刀的话,超出的那几张会被
                        # 悄悄丢掉 —— 任务照样成功,只是用的图和用户挂的不一样。
                        for path in references:
                            handle = path.open("rb")
                            handles.append(handle)
                            mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
                            files.append(("image[]", (path.name, handle, mime_type)))
                        response = client.post("/images/edits", data=build_edit_fields(request), files=files)
                    finally:
                        for handle in handles:
                            handle.close()
                else:
                    response = client.post("/images/generations", json=build_submit_payload(request))
                response.raise_for_status()
                content = response.json()
                data = content.get("data") or []
                image_bytes: bytes
                if data and isinstance(data[0], dict) and data[0].get("url"):
                    download = client.get(str(data[0]["url"]))
                    download.raise_for_status()
                    image_bytes = download.content
                else:
                    image_bytes = extract_image_bytes(content)
                output_dir.mkdir(parents=True, exist_ok=True)
                suffix = str(request.parameters.get("output_format") or "png").lower().lstrip(".")
                if suffix not in {"png", "jpg", "jpeg", "webp"}:
                    suffix = "png"
                target = output_dir / f"generated.{suffix}"
                target.write_bytes(image_bytes)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=content)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("OpenAI image request failed", exc, context.api_key)) from exc
