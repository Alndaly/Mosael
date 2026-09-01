from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.contracts.generation import (
    REFERENCE_IMAGE,
    GenerationAdapter,
    GenerationRequest,
    GenerationResult,
    GenerationAdapterContext,
    GenerationAdapterError,
    metering_from_request,
    adapter_http_error,
    source_url_values,
)
from app.ai.providers.media_transfer import fetch_bytes

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
    for key in ("quality", "background", "output_format", "moderation"):
        value = request.parameters.get(key)
        if value:
            fields[key] = str(value)
    return fields


def extract_image_bytes(payload: dict[str, Any]) -> list[bytes]:
    """取回**每一张**内联图。

    请求里的 `n` 是几,`data` 里就有几条。此前这里只读 data[0] —— 用户选了 4 张、按 4 张
    计了费,拿回来一张,而且没有任何地方会报错。
    """
    data = payload.get("data") or []
    entries = [one for one in data if isinstance(one, dict)]
    if not entries:
        raise GenerationAdapterError("Provider returned no image data")
    images = [base64.b64decode(str(one["b64_json"])) for one in entries if one.get("b64_json")]
    if not images:
        raise GenerationAdapterError("Provider returned a URL result where inline image data was expected")
    return images


class OpenAIImageAdapter(GenerationAdapter):
    media_kind = "image"

    def __init__(self, vendor_id: str = "openai") -> None:
        self.vendor_id = vendor_id

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise GenerationAdapterError("OpenAI API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or OPENAI_BASE).rstrip("/")
        headers = {"Authorization": f"Bearer {context.api_key}"}
        try:
            with RetryingClient(base_url=base_url, timeout=120, headers=headers) as client:
                references = request.sources_for(REFERENCE_IMAGE)
                reference_urls = source_url_values(request.parameters, REFERENCE_IMAGE, request.kind)
                if references or reference_urls:
                    files = []
                    handles = []
                    try:
                        # 张数由描述符管(见 domain/generation/catalog 的 source_limits),
                        # 提交前那道统一校验已经拦过。这里再截一刀的话,超出的那几张会被
                        # 悄悄丢掉 —— 任务照样成功,只是用的图和用户挂的不一样。
                        for index, url in enumerate(reference_urls, start=1):
                            remote = fetch_bytes(url)
                            name = Path(urlsplit(url).path).name or f"reference-{index}"
                            mime_type = remote.content_type or mimetypes.guess_type(name)[0] or "image/png"
                            files.append(("image[]", (name, remote.data, mime_type)))
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
                data = [one for one in (content.get("data") or []) if isinstance(one, dict)]
                #: 两种回法:外链和内联 base64。**都要全取** —— n 是几就有几条,
                #: 只取第一条的话后面那几张连同它们的钱一起消失。
                images: list[bytes] = []
                for one in data:
                    if one.get("b64_json"):
                        images.append(base64.b64decode(str(one["b64_json"])))
                    elif one.get("url"):
                        # Provider results are commonly pre-signed object-storage URLs. Never
                        # reuse the API client carrying the OpenAI bearer token.
                        images.append(fetch_bytes(str(one["url"])).data)
                if not images:
                    raise GenerationAdapterError("Provider returned no image data")
                output_dir.mkdir(parents=True, exist_ok=True)
                suffix = str(request.parameters.get("output_format") or "png").lower().lstrip(".")
                if suffix not in {"png", "jpg", "jpeg", "webp"}:
                    suffix = "png"
                #: 文件名带序号 —— 同名的话第二张会把第一张覆盖掉,而两次写入都"成功"。
                targets = [output_dir / f"generated-{index + 1}.{suffix}" for index in range(len(images))]
                for target, blob in zip(targets, images):
                    target.write_bytes(blob)
                return GenerationResult(output_paths=targets, usage=metering_from_request(request), raw_usage=content)
        except httpx.HTTPError as exc:
            raise GenerationAdapterError(adapter_http_error("OpenAI image request failed", exc, context.api_key)) from exc
