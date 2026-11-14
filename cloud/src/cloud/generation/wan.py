"""阿里云百炼 / 千问 AI 的万相 Wan 图片与视频异步任务。"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx2

from cloud.generation.adapters import AdapterArtifact, AdapterResult, JobContext

IMAGE_PATH = "/api/v1/services/aigc/text2image/image-synthesis"
VIDEO_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"
TASKS_PATH = "/api/v1/tasks"

_LEGACY_SIZES = {
    ("480P", "16:9"): "832*480",
    ("480P", "9:16"): "480*832",
    ("480P", "1:1"): "624*624",
    ("720P", "16:9"): "1280*720",
    ("720P", "9:16"): "720*1280",
    ("720P", "1:1"): "960*960",
    ("720P", "4:3"): "1088*832",
    ("720P", "3:4"): "832*1088",
    ("1080P", "16:9"): "1920*1080",
    ("1080P", "9:16"): "1080*1920",
    ("1080P", "1:1"): "1440*1440",
    ("1080P", "4:3"): "1632*1248",
    ("1080P", "3:4"): "1248*1632",
}


def _failed(code: str, detail: object) -> AdapterResult:
    return AdapterResult(status="failed", error_code=code, error_detail=str(detail)[:300])


def _headers(job: JobContext) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {job.api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }


def _size(value: object) -> str:
    text = str(value or "").strip().lower()
    return text.replace("x", "*") if "*" in text or "x" in text else ""


def _resolution(value: object) -> str:
    text = str(value or "").strip().upper()
    if text.isdigit():
        return f"{text}P"
    return text


def _image_submit(job: JobContext, transport: httpx2.BaseTransport | None) -> AdapterResult:
    data = job.input
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return _failed("wan_prompt_required", "prompt is required")
    inputs: dict[str, object] = {"prompt": prompt}
    if data.get("negative_prompt"):
        inputs["negative_prompt"] = data["negative_prompt"]
    reference = data.get("image") or data.get("reference_image")
    if reference:
        inputs["ref_img"] = reference
    parameters: dict[str, object] = {"n": int(data.get("n") or data.get("num_images") or 1)}
    size = _size(data.get("size"))
    if size:
        parameters["size"] = size
    return _submit(transport, job, IMAGE_PATH, {"model": job.upstream_model, "input": inputs, "parameters": parameters})


def _video_submit(job: JobContext, transport: httpx2.BaseTransport | None) -> AdapterResult:
    data = job.input
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return _failed("wan_prompt_required", "prompt is required")
    model = job.upstream_model
    new_protocol = model.startswith(("wan3", "wan2.7"))
    inputs: dict[str, object] = {"prompt": prompt}
    if data.get("negative_prompt"):
        inputs["negative_prompt"] = data["negative_prompt"]
    media: list[dict[str, str]] = []
    if new_protocol:
        frames = [
            {"type": kind, "url": str(data[key])}
            for key, kind in (("first_frame", "first_frame"), ("last_frame", "last_frame"))
            if data.get(key)
        ]
        if frames:
            media = frames
        elif model.startswith("wan3"):
            references = list(data.get("reference_images") or [])
            single = data.get("image") or data.get("reference_image")
            if single:
                references.append(single)
            media = [{"type": "reference_image", "url": str(value)} for value in references]
        if media:
            inputs["media"] = media
    else:
        first = data.get("first_frame") or data.get("image")
        if first:
            inputs["img_url"] = first

    parameters: dict[str, object] = {"duration": int(data.get("duration_seconds") or 5)}
    resolution = _resolution(data.get("resolution")) or ("1080P" if new_protocol else "720P")
    ratio = str(data.get("aspect_ratio") or "").strip()
    if new_protocol:
        parameters["resolution"] = resolution
        if ratio and not media:
            parameters["ratio"] = ratio
        if model.startswith("wan3") and data.get("generate_audio") is not None:
            parameters["audio"] = bool(data["generate_audio"])
    else:
        size = _size(data.get("size")) or _LEGACY_SIZES.get((resolution, ratio), "1280*720")
        parameters["size"] = size
    return _submit(transport, job, VIDEO_PATH, {"model": model, "input": inputs, "parameters": parameters})


def _submit(transport: httpx2.BaseTransport | None, job: JobContext, path: str, body: dict[str, object]) -> AdapterResult:
    try:
        with httpx2.Client(transport=transport, timeout=60.0) as client:
            response = client.post(f"{job.base_url.rstrip('/')}{path}", headers=_headers(job), json=body)
        payload = response.json()
        if response.status_code >= 400:
            return _failed("upstream_rejected", f"{response.status_code} {payload.get('message') or response.text[:200]}")
        task_id = (payload.get("output") or {}).get("task_id") if isinstance(payload, dict) else None
        if not task_id:
            return _failed("wan_no_task", "no task_id in response")
        return AdapterResult(status="pending", provider_job_id=str(task_id))
    except (httpx2.HTTPError, ValueError, TypeError) as exc:
        return _failed("upstream_error", exc)


def _filename(url: str, fallback: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or fallback


def _download(client: httpx2.Client, url: str, fallback: str) -> AdapterArtifact | None:
    response = client.get(url)
    if response.status_code >= 400 or not response.content:
        return None
    filename = _filename(url, fallback)
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return AdapterArtifact(filename=filename, mime=mime, data=response.content)


class WanAdapter:
    name = "wan"

    def __init__(self, *, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def submit(self, job: JobContext) -> AdapterResult:
        if job.upstream_model.startswith("wanx"):
            return _image_submit(job, self._transport)
        return _video_submit(job, self._transport)

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult:
        try:
            base = job.base_url.rstrip("/")
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.get(f"{base}{TASKS_PATH}/{provider_job_id}", headers=_headers(job))
            payload = response.json()
            if response.status_code >= 400 or not isinstance(payload, dict):
                return _failed("upstream_rejected", f"{response.status_code} {response.text[:200]}")
            output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
            status = str(output.get("task_status") or "").upper()
            if status in {"PENDING", "RUNNING"}:
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            if status != "SUCCEEDED":
                return _failed("wan_failed", output.get("message") or output.get("code") or status or "unknown")
            artifacts: list[AdapterArtifact] = []
            with httpx2.Client(transport=self._transport, timeout=300.0) as client:
                results = output.get("results") if isinstance(output.get("results"), list) else []
                for index, item in enumerate(results, start=1):
                    url = item.get("url") if isinstance(item, dict) else None
                    if url:
                        artifact = _download(client, str(url), f"image-{index}.png")
                        if artifact:
                            artifacts.append(artifact)
                video_url = output.get("video_url")
                if video_url:
                    artifact = _download(client, str(video_url), "video.mp4")
                    if artifact:
                        artifacts.append(artifact)
            if not artifacts:
                return _failed("wan_no_artifacts", "completed task has no downloadable result")
            usage: dict[str, int] = {}
            if output.get("video_url"):
                reported = (payload.get("usage") or {}).get("output_video_duration") if isinstance(payload.get("usage"), dict) else None
                usage["second"] = int(reported or job.input.get("duration_seconds") or 5)
            else:
                reported = (payload.get("usage") or {}).get("image_count") if isinstance(payload.get("usage"), dict) else None
                usage["image"] = int(reported or len(artifacts))
            return AdapterResult(status="succeeded", provider_job_id=provider_job_id, artifacts=artifacts, usage=usage)
        except (httpx2.HTTPError, ValueError, TypeError) as exc:
            return _failed("upstream_error", exc)

    def cancel(self, job: JobContext, provider_job_id: str) -> bool:
        try:
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.post(
                    f"{job.base_url.rstrip('/')}{TASKS_PATH}/{provider_job_id}/cancel",
                    headers=_headers(job),
                )
            return response.status_code < 400
        except httpx2.HTTPError:
            return False


ADAPTER = WanAdapter()
