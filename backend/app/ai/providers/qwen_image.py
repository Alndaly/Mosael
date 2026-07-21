from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

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
Alibaba DashScope qwen-image adapter (async task API):
submit → poll /api/v1/tasks/{id} → download result URL.
"""

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
SUBMIT_PATH = "/api/v1/services/aigc/text2image/image-synthesis"
EDIT_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
POLL_INTERVAL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 300


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    size = str(request.parameters.get("size", "1024*1024")).replace("x", "*")
    payload: dict[str, Any] = {
        "model": request.model,
        "input": {"prompt": request.prompt},
        "parameters": {
            "size": size,
            "n": int(request.parameters.get("num_images", 1)),
        },
    }
    if request.negative_prompt:
        payload["input"]["negative_prompt"] = request.negative_prompt
    if request.parameters.get("seed") is not None:
        payload["parameters"]["seed"] = int(request.parameters["seed"])
    return payload


def build_edit_payload(request: GenerationRequest, context: ProviderContext | None = None) -> dict[str, Any]:
    model = resolve_edit_model(request, context)
    content: list[dict[str, str]] = [{"image": image_file_to_data_url(path)} for path in request.source_files[:3]]
    content.append({"text": request.prompt})
    parameters: dict[str, Any] = {
        "n": int(request.parameters.get("num_images", 1)),
        "watermark": False,
    }
    if request.negative_prompt:
        parameters["negative_prompt"] = request.negative_prompt
    if request.parameters.get("seed") is not None:
        parameters["seed"] = int(request.parameters["seed"])
    if request.parameters.get("size") and model != "qwen-image-edit":
        parameters["size"] = str(request.parameters["size"]).replace("x", "*")
    if model != "qwen-image-edit":
        parameters["prompt_extend"] = bool(request.parameters.get("prompt_extend", True))
    return {
        "model": model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": parameters,
    }


def resolve_edit_model(request: GenerationRequest, context: ProviderContext | None = None) -> str:
    model = (request.model or (context.default_model if context else "") or "qwen-image-edit").strip()
    if model in {"qwen-image", "qwen-image-plus", "qwen-image-max"}:
        return "qwen-image-edit"
    return model


def resolve_dashscope_base(context: ProviderContext) -> str:
    """Qwen image uses DashScope's native async task API, not Bailian compatible-mode.

    A single Alibaba profile may still use an OpenAI-compatible base_url for chat models.
    Treat image generation as a separate capability endpoint; it can be overridden explicitly
    via extra.dashscope_base_url, otherwise it must use DashScope native.
    """
    configured = str(context.extra.get("dashscope_base_url") or context.extra.get("generation_base_url") or "").strip()
    return (configured or DASHSCOPE_BASE).rstrip("/")


def resolve_qwen_edit_base(context: ProviderContext) -> str:
    configured = str(context.extra.get("qwen_edit_base_url") or context.extra.get("generation_base_url") or "").strip()
    if configured:
        return configured.rstrip("/")
    base_url = (context.base_url or "").rstrip("/")
    if base_url.endswith("/compatible-mode/v1"):
        return base_url.removesuffix("/compatible-mode/v1")
    if base_url and base_url != DASHSCOPE_BASE:
        return base_url
    return DASHSCOPE_BASE


def extract_result_url(task_payload: dict[str, Any]) -> str | None:
    output = task_payload.get("output") or {}
    choices = output.get("choices") or []
    for choice in choices:
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("image"):
                    return str(item["image"])
    status = output.get("task_status")
    if status == "SUCCEEDED":
        results = output.get("results") or []
        for result in results:
            if isinstance(result, dict) and result.get("url"):
                return str(result["url"])
        raise ProviderError("Provider returned success without a result URL")
    if status in ("FAILED", "CANCELED"):
        raise ProviderError(f"Generation failed with status {status}")
    return None


def download_result_asset(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # DashScope returns a pre-signed OSS URL. Do not reuse the DashScope client here:
    # carrying Authorization or DashScope headers into OSS changes signature validation.
    with httpx.Client(timeout=120) as client:
        response = client.get(url)
        response.raise_for_status()
        target.write_bytes(response.content)


class QwenImageProvider(GenerationProvider):
    name = "alibaba"
    kind = "image"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("DashScope API key is not configured (settings → 生成服务)")
        base_url = resolve_dashscope_base(context)
        try:
            if request.source_files:
                headers = {"Authorization": f"Bearer {context.api_key}", "Content-Type": "application/json"}
                with httpx.Client(base_url=resolve_qwen_edit_base(context), timeout=120, headers=headers) as client:
                    submit = client.post(EDIT_PATH, json=build_edit_payload(request, context))
                    submit.raise_for_status()
                    url = extract_result_url(submit.json())
                    if not url:
                        raise ProviderError("Provider returned success without a result URL")
                    target = output_dir / "generated.png"
                    download_result_asset(url, target)
                    return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=submit.json())

            headers = {"Authorization": f"Bearer {context.api_key}", "X-DashScope-Async": "enable"}
            with httpx.Client(base_url=base_url, timeout=30, headers=headers) as client:
                submit = client.post(SUBMIT_PATH, json=build_submit_payload(request))
                submit.raise_for_status()
                task_id = ((submit.json().get("output") or {}).get("task_id")) or ""
                if not task_id:
                    raise ProviderError("Provider did not return a task id")

                deadline = time.time() + POLL_TIMEOUT_SECONDS
                url: str | None = None
                while time.time() < deadline:
                    poll = client.get(f"/api/v1/tasks/{task_id}")
                    poll.raise_for_status()
                    poll_payload = poll.json()
                    url = extract_result_url(poll_payload)
                    if url:
                        break
                    time.sleep(POLL_INTERVAL_SECONDS)
                if not url:
                    raise ProviderError("Generation timed out")

                target = output_dir / "generated.png"
                download_result_asset(url, target)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("DashScope request failed", exc, context.api_key)) from exc
