"""OpenAI 兼容图片生成适配器:/images/generations,支持 b64_json 或结果 URL。"""

from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx2

from cloud.generation.adapters import AdapterArtifact, AdapterResult, JobContext


class OpenAIImagesAdapter:
    name = "openai_images"

    def __init__(self, *, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def submit(self, job: JobContext) -> AdapterResult:
        data = job.input
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return AdapterResult(status="failed", error_code="image_prompt_required", error_detail="prompt is required")
        count = int(data.get("n") or 1)
        payload: dict[str, Any] = {
            "model": job.upstream_model,
            "prompt": prompt,
            "n": count,
            "response_format": "b64_json",
        }
        for key in ("size", "quality", "background", "output_format"):
            if data.get(key) is not None:
                payload[key] = data[key]
        try:
            with httpx2.Client(transport=self._transport, timeout=120.0) as client:
                response = client.post(
                    f"{job.base_url.rstrip('/')}/images/generations",
                    headers={"Authorization": f"Bearer {job.api_key}"},
                    json=payload,
                )
            if response.status_code >= 400:
                return AdapterResult(
                    status="failed", error_code="upstream_rejected",
                    error_detail=f"{response.status_code} {response.text[:300]}",
                )
            body = response.json()
            artifacts = self._artifacts(body)
            if not artifacts:
                return AdapterResult(status="failed", error_code="image_empty", error_detail="no image in response")
            return AdapterResult(
                status="succeeded",
                artifacts=artifacts,
                usage={"image": len(artifacts)},
            )
        except (httpx2.HTTPError, ValueError, KeyError) as exc:
            return AdapterResult(status="failed", error_code="upstream_error", error_detail=str(exc)[:300])

    def _artifacts(self, body: dict[str, Any]) -> list[AdapterArtifact]:
        artifacts: list[AdapterArtifact] = []
        for index, item in enumerate(body.get("data") or []):
            if not isinstance(item, dict):
                continue
            encoded = item.get("b64_json")
            if isinstance(encoded, str) and encoded:
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError):
                    continue
                artifacts.append(AdapterArtifact(filename=f"image-{index + 1}.png", mime="image/png", data=raw))
                continue
            url = item.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                try:
                    with httpx2.Client(transport=self._transport, timeout=120.0) as client:
                        response = client.get(url)
                    if response.status_code < 400 and response.content:
                        mime = response.headers.get("content-type", "image/png").split(";")[0]
                        suffix = "png" if "png" in mime else "jpg"
                        artifacts.append(AdapterArtifact(filename=f"image-{index + 1}.{suffix}", mime=mime, data=response.content))
                except httpx2.HTTPError:
                    continue
        return artifacts

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult:
        return AdapterResult(status="failed", error_code="image_not_pollable", error_detail="image adapter is synchronous")

    def cancel(self, job: JobContext, provider_job_id: str) -> bool:
        return False


ADAPTER = OpenAIImagesAdapter()
