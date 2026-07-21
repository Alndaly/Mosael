from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.base import GenerationProvider, GenerationRequest, ProviderContext, ProviderError, provider_http_error

"""
ByteDance Seedance adapter via Volcano ARK content-generation tasks:
submit → poll /tasks/{id} → download video_url. Seedance takes generation
parameters as a text-command suffix.
"""

ARK_BASE = "https://ark.cn-beijing.volces.com"
TASKS_PATH = "/api/v3/contents/generations/tasks"
POLL_INTERVAL_SECONDS = 3.0
POLL_TIMEOUT_SECONDS = 600
DEFAULT_MODEL_ID = "seedance-1-0-lite-t2v-250428"


def build_submit_payload(request: GenerationRequest) -> dict[str, Any]:
    duration = int(float(request.parameters.get("duration_seconds", 5)))
    resolution = str(request.parameters.get("resolution", "720p"))
    ratio = str(request.parameters.get("aspect_ratio", "16:9"))
    command = f"{request.prompt} --resolution {resolution} --duration {duration} --ratio {ratio}"
    content: list[dict[str, Any]] = [{"type": "text", "text": command}]
    first_frame = request.parameters.get("first_frame_url")
    if first_frame:
        content.append({"type": "image_url", "image_url": {"url": str(first_frame)}})
    model = request.model if request.model != "seedance" else DEFAULT_MODEL_ID
    return {"model": model, "content": content}


def extract_video_url(task_payload: dict[str, Any]) -> str | None:
    status = str(task_payload.get("status", "")).lower()
    if status == "succeeded":
        url = (task_payload.get("content") or {}).get("video_url")
        if not url:
            raise ProviderError("Provider returned success without a video URL")
        return str(url)
    if status in ("failed", "cancelled", "canceled", "expired"):
        raise ProviderError(f"Generation failed with status {status}")
    return None


class SeedanceProvider(GenerationProvider):
    name = "bytedance"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> Path:
        if not context.api_key:
            raise ProviderError("ARK API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or ARK_BASE).rstrip("/")
        tasks_path = "/contents/generations/tasks" if base_url.endswith("/api/v3") else TASKS_PATH
        headers = {"Authorization": f"Bearer {context.api_key}"}
        try:
            with httpx.Client(base_url=base_url, timeout=30, headers=headers) as client:
                submit = client.post(tasks_path, json=build_submit_payload(request))
                submit.raise_for_status()
                task_id = submit.json().get("id") or ""
                if not task_id:
                    raise ProviderError("Provider did not return a task id")

                deadline = time.time() + POLL_TIMEOUT_SECONDS
                url: str | None = None
                while time.time() < deadline:
                    poll = client.get(f"{tasks_path}/{task_id}")
                    poll.raise_for_status()
                    url = extract_video_url(poll.json())
                    if url:
                        break
                    time.sleep(POLL_INTERVAL_SECONDS)
                if not url:
                    raise ProviderError("Generation timed out")

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                with client.stream("GET", url) as download:
                    download.raise_for_status()
                    with target.open("wb") as out:
                        for chunk in download.iter_bytes():
                            out.write(chunk)
                return target
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("ARK request failed", exc, context.api_key)) from exc
