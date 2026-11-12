"""可灵视频:提交 text2video / image2video 任务,轮询后下载成片。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx2

from cloud.generation.adapters import AdapterArtifact, AdapterResult, JobContext


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _jwt(access_key: str, secret: str) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"iss": access_key, "exp": now + 1800, "nbf": now - 5}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}"
    signature = _b64(hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest())
    return f"{signing}.{signature}"


class KlingVideoAdapter:
    name = "kling"

    def __init__(self, *, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def _headers(self, job: JobContext) -> dict[str, str]:
        secret = str(job.config.get("secret_key") or "")
        token = _jwt(job.api_key, secret) if secret else job.api_key
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def submit(self, job: JobContext) -> AdapterResult:
        data = job.input
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return AdapterResult(status="failed", error_code="video_prompt_required", error_detail="prompt is required")
        first = data.get("first_frame") or data.get("image")
        mode = "image2video" if first else "text2video"
        body: dict[str, Any] = {
            "model_name": job.upstream_model,
            "prompt": prompt,
            "duration": str(int(data.get("duration_seconds") or 5)),
            "aspect_ratio": str(data.get("aspect_ratio") or "16:9"),
        }
        if data.get("negative_prompt"):
            body["negative_prompt"] = data["negative_prompt"]
        if first:
            body["image"] = first
        if data.get("last_frame"):
            body["image_tail"] = data["last_frame"]
        try:
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.post(
                    f"{job.base_url.rstrip('/')}/v1/videos/{mode}",
                    headers=self._headers(job),
                    json=body,
                )
            payload = response.json()
            if response.status_code >= 400 or payload.get("code") not in (None, 0):
                return AdapterResult(
                    status="failed", error_code="upstream_rejected",
                    error_detail=f"{response.status_code} {payload.get('message') or response.text[:300]}",
                )
            task_id = (payload.get("data") or {}).get("task_id")
            if not task_id:
                return AdapterResult(status="failed", error_code="kling_no_task", error_detail="no task_id")
            return AdapterResult(status="pending", provider_job_id=f"{mode}:{task_id}")
        except (httpx2.HTTPError, ValueError, KeyError) as exc:
            return AdapterResult(status="failed", error_code="upstream_error", error_detail=str(exc)[:300])

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult:
        mode, _, task_id = provider_job_id.partition(":")
        if not task_id:
            return AdapterResult(status="failed", error_code="kling_bad_job", error_detail=provider_job_id)
        try:
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.get(
                    f"{job.base_url.rstrip('/')}/v1/videos/{mode}/{task_id}",
                    headers=self._headers(job),
                )
            payload = response.json()
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            status = str(data.get("task_status") or "").lower()
            if status in {"submitted", "processing", "running", "queued"}:
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            if status in {"failed", "fail", "canceled", "cancelled"}:
                return AdapterResult(
                    status="failed", error_code="kling_failed",
                    error_detail=str(data.get("task_status_msg") or data.get("message") or status)[:300],
                )
            if status != "succeed":
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            result = data.get("task_result") or {}
            videos = result.get("videos") if isinstance(result, dict) else None
            url = None
            if isinstance(videos, list) and videos:
                url = videos[0].get("url") or videos[0].get("video_url")
            if not url:
                return AdapterResult(status="failed", error_code="kling_no_result", error_detail="no video URL")
            with httpx2.Client(transport=self._transport, timeout=300.0) as client:
                media = client.get(str(url))
            if media.status_code >= 400 or not media.content:
                return AdapterResult(status="failed", error_code="kling_download_failed", error_detail=str(media.status_code))
            mime = media.headers.get("content-type", "video/mp4").split(";")[0]
            seconds = int(job.input.get("duration_seconds") or 5)
            return AdapterResult(
                status="succeeded",
                provider_job_id=provider_job_id,
                artifacts=[AdapterArtifact(filename="video.mp4", mime=mime, data=media.content)],
                usage={"second": seconds},
            )
        except (httpx2.HTTPError, ValueError, KeyError) as exc:
            return AdapterResult(status="failed", error_code="upstream_error", error_detail=str(exc)[:300])

    def cancel(self, job: JobContext, provider_job_id: str) -> None:
        return None


ADAPTER = KlingVideoAdapter()
