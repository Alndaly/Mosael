"""ComfyUI API graph 适配器:按 bindings 填图、上传图片并收集历史产物。"""

from __future__ import annotations

import base64
import copy
import mimetypes
from typing import Any
from urllib.parse import quote, unquote, unquote_to_bytes, urlparse

import httpx2

from cloud.generation.adapters import AdapterArtifact, AdapterResult, JobContext

_IMAGE_INPUTS = {"first_frame", "last_frame", "image", "reference_image"}
_OUTPUT_KINDS = ("images", "gifs", "videos", "audio")
_FAILED_STATUSES = {"error", "failed", "fail", "cancelled", "canceled"}


def _headers(job: JobContext) -> dict[str, str]:
    return {"Authorization": f"Bearer {job.api_key}"} if job.api_key else {}


def _failed(code: str, detail: object) -> AdapterResult:
    return AdapterResult(status="failed", error_code=code, error_detail=str(detail)[:300])


def _set_binding(graph: dict[str, Any], path: str, value: object) -> None:
    parts = path.split(".")
    if len(parts) < 3 or any(not part for part in parts):
        raise ValueError(f"invalid ComfyUI binding: {path}")
    current = graph
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise ValueError(f"ComfyUI binding does not resolve: {path}")
        current = child
    current[parts[-1]] = copy.deepcopy(value)


def _data_image(value: str) -> tuple[bytes, str, str]:
    header, separator, payload = value[5:].partition(",")
    if not separator:
        raise ValueError("invalid data image")
    parts = header.split(";")
    mime = parts[0].lower()
    if not mime.startswith("image/"):
        raise ValueError("data input is not an image")
    if parts[-1].lower() == "base64":
        data = base64.b64decode(payload, validate=True)
    else:
        data = unquote_to_bytes(payload)
    if not data:
        raise ValueError("empty data image")
    extension = mimetypes.guess_extension(mime) or ".png"
    return data, mime, f"image{extension}"


def _download_name(url: str, mime: str) -> str:
    name = unquote(urlparse(url).path).rsplit("/", 1)[-1] or "image"
    if "." not in name:
        name += mimetypes.guess_extension(mime) or ".png"
    return name


class ComfyUIAdapter:
    name = "comfyui"

    def __init__(self, *, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def _upload_image(self, job: JobContext, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("image input must be a URL or data URI")
        if value.startswith("data:"):
            data, mime, filename = _data_image(value)
        else:
            with httpx2.Client(transport=self._transport, timeout=300.0) as client:
                response = client.get(value)
            if response.status_code >= 400 or not response.content:
                raise ValueError(f"image download failed: {response.status_code}")
            mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if not mime.startswith("image/"):
                mime = mimetypes.guess_type(urlparse(value).path)[0] or "image/png"
            data = response.content
            filename = _download_name(value, mime)
        with httpx2.Client(transport=self._transport, timeout=60.0) as client:
            uploaded = client.post(
                f"{job.base_url.rstrip('/')}/upload/image",
                headers=_headers(job),
                data={"type": "input"},
                files={"image": (filename, data, mime)},
            )
        if uploaded.status_code >= 400:
            raise ValueError(f"image upload failed: {uploaded.status_code} {uploaded.text[:200]}")
        body = uploaded.json()
        if not isinstance(body, dict) or not body.get("name"):
            raise ValueError("ComfyUI upload response has no input filename")
        return str(body["name"])

    def submit(self, job: JobContext) -> AdapterResult:
        try:
            workflows = job.config.get("workflows")
            workflow = workflows.get(job.upstream_model) if isinstance(workflows, dict) else None
            if not isinstance(workflow, dict) or not isinstance(workflow.get("prompt"), dict):
                return _failed("comfyui_config", f"unknown workflow: {job.upstream_model}")
            bindings = workflow.get("bindings")
            if not isinstance(bindings, dict) or not isinstance(bindings.get("prompt"), str):
                return _failed("comfyui_prompt_binding", "prompt binding is required")
            graph = copy.deepcopy(workflow["prompt"])
            for key, value in job.input.items():
                binding = bindings.get(key)
                if binding is None:
                    continue
                if key == "reference_images":
                    if not isinstance(value, list) or not isinstance(binding, list) or not all(
                        isinstance(path, str) for path in binding
                    ):
                        raise ValueError("reference_images bindings must be a path array")
                    if len(value) > len(binding):
                        return _failed("comfyui_reference_images", "more reference images than bindings")
                    for item, path in zip(value, binding):
                        _set_binding(graph, path, self._upload_image(job, item))
                elif key in _IMAGE_INPUTS:
                    if not isinstance(binding, str):
                        raise ValueError(f"{key} binding must be a path")
                    _set_binding(graph, binding, self._upload_image(job, value))
                else:
                    if not isinstance(binding, str):
                        raise ValueError(f"{key} binding must be a path")
                    _set_binding(graph, binding, value)
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.post(
                    f"{job.base_url.rstrip('/')}/prompt",
                    headers=_headers(job),
                    json={"prompt": graph, "client_id": job.job_id},
                )
            if response.status_code >= 400:
                return _failed("upstream_rejected", f"{response.status_code} {response.text[:300]}")
            body = response.json()
            if not isinstance(body, dict) or not body.get("prompt_id"):
                return _failed("comfyui_no_prompt", "no prompt_id in ComfyUI response")
            return AdapterResult(status="pending", provider_job_id=str(body["prompt_id"]))
        except Exception as exc:  # noqa: BLE001 —— 上游与配置错误统一进入任务失败结果
            return _failed("upstream_error", exc)

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult:
        try:
            base = job.base_url.rstrip("/")
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.get(
                    f"{base}/history/{quote(provider_job_id, safe='')}", headers=_headers(job)
                )
            if response.status_code >= 400:
                return _failed("upstream_rejected", f"{response.status_code} {response.text[:300]}")
            body = response.json()
            if not isinstance(body, dict):
                return _failed("comfyui_bad_history", "history response is not an object")
            record = body.get(provider_job_id)
            if record is None:
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            if not isinstance(record, dict):
                return _failed("comfyui_bad_history", "history entry is not an object")
            state = record.get("status") if isinstance(record.get("status"), dict) else {}
            status = str(state.get("status_str") or "").lower()
            if status in _FAILED_STATUSES:
                return _failed("comfyui_failed", status)
            completed = state.get("completed")
            if completed is False or (state and completed is not True and status != "success"):
                return AdapterResult(status="running", provider_job_id=provider_job_id)
            outputs = record.get("outputs")
            if not isinstance(outputs, dict):
                return _failed("comfyui_no_artifacts", "no outputs in completed history")

            artifacts: list[AdapterArtifact] = []
            image_count = 0
            timed_output = False
            for node_output in outputs.values():
                if not isinstance(node_output, dict):
                    return _failed("comfyui_bad_outputs", "output node is not an object")
                for kind in _OUTPUT_KINDS:
                    entries = node_output.get(kind, [])
                    if not isinstance(entries, list):
                        return _failed("comfyui_bad_outputs", f"{kind} output is not an array")
                    for entry in entries:
                        if not isinstance(entry, dict) or not entry.get("filename"):
                            return _failed("comfyui_bad_outputs", "output has no filename")
                        filename = str(entry["filename"])
                        params = {
                            "filename": filename,
                            "subfolder": str(entry.get("subfolder") or ""),
                            "type": str(entry.get("type") or "output"),
                        }
                        with httpx2.Client(transport=self._transport, timeout=300.0) as client:
                            media = client.get(f"{base}/view", params=params, headers=_headers(job))
                        if media.status_code >= 400 or not media.content:
                            return _failed("comfyui_download_failed", f"{filename}: {media.status_code}")
                        mime = media.headers.get("content-type", "").split(";")[0].strip().lower()
                        if not mime or mime == "application/octet-stream":
                            mime = mimetypes.guess_type(filename)[0] or (
                                "audio/octet-stream" if kind == "audio" else "video/octet-stream"
                                if kind == "videos" else "image/octet-stream"
                            )
                        artifacts.append(AdapterArtifact(filename=filename, mime=mime, data=media.content))
                        if kind in {"images", "gifs"}:
                            image_count += 1
                        else:
                            timed_output = True
            if not artifacts:
                return _failed("comfyui_no_artifacts", "completed history has no downloadable artifacts")
            usage: dict[str, int] = {}
            if image_count:
                usage["image"] = image_count
            if timed_output:
                usage["second"] = int(job.input.get("duration_seconds") or 5)
            return AdapterResult(
                status="succeeded",
                provider_job_id=provider_job_id,
                artifacts=artifacts,
                usage=usage,
            )
        except Exception as exc:  # noqa: BLE001 —— 轮询不能让 worker 因上游坏响应退出
            return _failed("upstream_error", exc)

    def cancel(self, job: JobContext, provider_job_id: str) -> bool:
        if not provider_job_id:
            return False
        try:
            base = job.base_url.rstrip("/")
            headers = _headers(job)
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                response = client.get(f"{base}/queue", headers=headers)
            if response.status_code >= 400:
                return False
            queue = response.json()
            if not isinstance(queue, dict):
                return False

            def contains(entries: object) -> bool:
                return isinstance(entries, list) and any(
                    isinstance(entry, list) and len(entry) > 1 and str(entry[1]) == provider_job_id
                    for entry in entries
                )

            if contains(queue.get("queue_pending")):
                with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                    deleted = client.post(f"{base}/queue", headers=headers, json={"delete": [provider_job_id]})
                return deleted.status_code < 400
            if contains(queue.get("queue_running")):
                with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                    interrupted = client.post(f"{base}/interrupt", headers=headers)
                return interrupted.status_code < 400
            with httpx2.Client(transport=self._transport, timeout=60.0) as client:
                history = client.get(f"{base}/history/{quote(provider_job_id, safe='')}", headers=headers)
            if history.status_code >= 400:
                return False
            body = history.json()
            return isinstance(body, dict) and provider_job_id in body
        except Exception:  # noqa: BLE001 —— 无法确认取消时不得释放预占
            return False


ADAPTER = ComfyUIAdapter()
