from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.base import GenerationProvider, GenerationRequest, ProviderContext, ProviderError, provider_http_error

"""
Alibaba DashScope qwen-image adapter (async task API):
submit → poll /api/v1/tasks/{id} → download result URL.
"""

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
SUBMIT_PATH = "/api/v1/services/aigc/text2image/image-synthesis"
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


def resolve_dashscope_base(context: ProviderContext) -> str:
    """Qwen image uses DashScope's native async task API, not Bailian compatible-mode.

    A single Alibaba profile may still use an OpenAI-compatible base_url for chat models.
    Treat image generation as a separate capability endpoint; it can be overridden explicitly
    via extra.dashscope_base_url, otherwise it must use DashScope native.
    """
    configured = str(context.extra.get("dashscope_base_url") or context.extra.get("generation_base_url") or "").strip()
    return (configured or DASHSCOPE_BASE).rstrip("/")


def extract_result_url(task_payload: dict[str, Any]) -> str | None:
    output = task_payload.get("output") or {}
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


class QwenImageProvider(GenerationProvider):
    name = "alibaba"
    kind = "image"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> Path:
        if not context.api_key:
            raise ProviderError("DashScope API key is not configured (settings → 生成服务)")
        base_url = resolve_dashscope_base(context)
        headers = {"Authorization": f"Bearer {context.api_key}", "X-DashScope-Async": "enable"}
        try:
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
                    url = extract_result_url(poll.json())
                    if url:
                        break
                    time.sleep(POLL_INTERVAL_SECONDS)
                if not url:
                    raise ProviderError("Generation timed out")

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.png"
                download = client.get(url)
                download.raise_for_status()
                target.write_bytes(download.content)
                return target
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("DashScope request failed", exc, context.api_key)) from exc
