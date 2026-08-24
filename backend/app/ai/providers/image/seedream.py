from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.domain.ai_retry import RetryingClient

from app.ai.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    image_file_to_data_url,
    metering_from_request,
    provider_http_error,
)

"""
ByteDance Seedream(豆包生图)adapter。

火山 ARK 的图片接口是 OpenAI 风格的同步端点(POST /images/generations →
data[0].url),与 seedance 视频的异步任务端点不同,不需要轮询。
4.x 支持 image 入参做参考图;3.x t2i 纯文生图,支持 seed。
复用 seedance 同一 bytedance 档案的 ARK key 与 base_url。
"""

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
IMAGES_PATH = "/images/generations"
DEFAULT_MODEL_ID = "doubao-seedream-4-0-250828"


def _is_seedream4(model: str) -> bool:
    return "seedream-4" in model


def resolve_seedream_model(request: GenerationRequest, context: ProviderContext | None = None) -> str:
    return (request.model or (context.default_model if context else "") or DEFAULT_MODEL_ID).strip()


def build_image_payload(request: GenerationRequest, context: ProviderContext | None = None) -> dict[str, Any]:
    model = resolve_seedream_model(request, context)
    payload: dict[str, Any] = {
        "model": model,
        "prompt": request.prompt.strip(),
        "response_format": "url",
        "watermark": False,
    }
    size = str(request.parameters.get("size", "")).strip()
    if size:
        payload["size"] = size.replace("*", "x")
    if _is_seedream4(model):
        # 4.x 参考图:显式 URL 优先,其次上传文件转 data URL。
        reference = request.parameters.get("image_url")
        if not reference and request.source_files:
            reference = image_file_to_data_url(request.source_files[0])
        if reference:
            payload["image"] = [str(reference)]
    elif request.parameters.get("seed") is not None:
        payload["seed"] = int(request.parameters["seed"])
    return payload


def extract_image_url(response_payload: dict[str, Any]) -> str:
    data = response_payload.get("data") or []
    for item in data:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    raise ProviderError("Provider returned success without an image URL")


class SeedreamProvider(GenerationProvider):
    # 与 Seedance(video)同属 "bytedance":适配器注册表按 (vendor, kind) 建键,
    # 同一家的图像与视频天然共存,不需要为此拆出第二个 vendor。
    name = "bytedance"
    kind = "image"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("ARK API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or ARK_BASE).rstrip("/")
        headers = {"Authorization": f"Bearer {context.api_key}"}
        try:
            with RetryingClient(base_url=base_url, timeout=180, headers=headers) as client:
                response = client.post(IMAGES_PATH, json=build_image_payload(request, context))
                response.raise_for_status()
                payload = response.json()
                url = extract_image_url(payload)

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.png"
                # 结果是预签名的对象存储 URL:不能带着 ARK 的 Authorization 去下载,
                # 多余的头会破坏签名校验(与 DashScope 同坑)。
                with RetryingClient(timeout=120) as downloader:
                    download = downloader.get(url)
                    download.raise_for_status()
                    target.write_bytes(download.content)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("ARK image request failed", exc, context.api_key)) from exc
