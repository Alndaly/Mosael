"""火山方舟 Seedance 视频:提交 /contents/generations/tasks,轮询任务,下载成片。"""

from __future__ import annotations

from typing import Any

import httpx2

from cloud.generation.adapters import AdapterArtifact, AdapterResult, JobContext

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
TASKS = "/contents/generations/tasks"


class SeedanceAdapter:
    name = "seedance"

    def __init__(self, *, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def _headers(self, job: JobContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {job.api_key}", "Content-Type": "application/json"}

    def submit(self, job: JobContext) -> AdapterResult:
        data = job.input
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return AdapterResult(status="failed", error_code="video_prompt_required", error_detail="prompt is required")
        duration = int(data.get("duration_seconds") or 5)
        resolution = str(data.get("resolution") or "720p")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]
        first = data.get("first_frame")
        if first:
            content.append({"type": "image_url", "image_url": {"url": first}, "role": "first_frame"})
        last = data.get("last_frame")
        if last:
            content.append({"type": "image_url", "image_url": {"url": last}, "role": "last_frame"})
        payload: dict[str, Any] = {
            "model": job.upstream_model,
            "content": content,
            "duration": duration,
            "resolution": resolution,
            "watermark": False,
        }
        ratio = str(data.get("aspect_ratio") or "").strip()
        if ratio and not first:
            payload["ratio"] = ratio
        if data.get("generate_audio") is not None:
            payload["generate_audio"] = bool(data["generate_audio"])
        try:
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.post(f"{job.base_url.rstrip('/')}{TASKS}", headers=self._headers(job), json=payload)
            body = response.json()
            if response.status_code >= 400:
                return AdapterResult(
                    status="failed", error_code="upstream_rejected",
                    error_detail=f"{response.status_code} {body.get('error', {}).get('message') if isinstance(body.get('error'), dict) else response.text[:300]}",
                )
            task_id = body.get("id") or (body.get("data") or {}).get("id")
            if not task_id:
                return AdapterResult(status="failed", error_code="seedance_no_task", error_detail="no task id")
            return AdapterResult(status="pending", provider_job_id=str(task_id))
        except (httpx2.HTTPError, ValueError, KeyError) as exc:
            return AdapterResult(status="failed", error_code="upstream_error", error_detail=str(exc)[:300])

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult:
        try:
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.get(
                    f"{job.base_url.rstrip('/')}{TASKS}/{provider_job_id}",
                    headers=self._headers(job),
                )
            body = response.json()
            status = str(body.get("status") or "").lower()
            if status in {"queued", "running", "processing", "submitted"}:
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            if status in {"failed", "cancelled", "canceled", "expired"}:
                error = body.get("error") if isinstance(body.get("error"), dict) else {}
                return AdapterResult(
                    status="failed", error_code=str(error.get("code") or "seedance_failed"),
                    error_detail=str(error.get("message") or status)[:300],
                )
            if status != "succeeded":
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            content = body.get("content") if isinstance(body.get("content"), dict) else {}
            url = body.get("video_url") or content.get("video_url")
            if not url:
                return AdapterResult(status="failed", error_code="seedance_no_result", error_detail="no video URL")
            with httpx2.Client(transport=self._transport, timeout=300.0) as client:
                media = client.get(str(url))
            if media.status_code >= 400 or not media.content:
                return AdapterResult(status="failed", error_code="seedance_download_failed", error_detail=str(media.status_code))
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

    def cancel(self, job: JobContext, provider_job_id: str) -> bool:
        return False


ADAPTER = SeedanceAdapter()
