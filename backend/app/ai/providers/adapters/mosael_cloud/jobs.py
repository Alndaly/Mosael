"""MosaelCloud job 的桌面端适配器:上传素材 → 提交任务 → 轮询 → 下载结果。

Cloud 的 job 端点不是 OpenAI 形状:它只有 `POST/GET/DELETE /gateway/v1/jobs`。对话仍走
OpenAI 兼容连接;图片/视频走这里,两者共享同一条 Cloud 连接和设备令牌。
"""

from __future__ import annotations

import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.http_retry import RetryingClient

from app.ai.providers.contracts.generation import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
)

POLL_SECONDS = 2.0
TIMEOUT_SECONDS = 3600.0


class MosaelCloudJobAdapter(GenerationAdapter):
    vendor_id = "mosael-cloud"
    supports_resume = False
    surface_depends_on_model = False

    def __init__(self, media_kind: str) -> None:
        self.media_kind = media_kind
        self.parameter_surface = (
            ("num_images", "size", "aspect_ratio")
            if media_kind == "image"
            else ("duration_seconds", "resolution", "aspect_ratio", "generate_audio")
        )

    def _client(self, context: GenerationAdapterContext) -> RetryingClient:
        if not context.api_key:
            raise GenerationAdapterError("providerErr_apiKeyMissing", vendor=self.vendor_id)
        base = (context.base_url or "").rstrip("/")
        if not base.endswith("/gateway/v1"):
            raise GenerationAdapterError("providerErr_cloudEndpoint", vendor=self.vendor_id)
        return RetryingClient(
            base_url=base,
            headers={"Authorization": f"Bearer {context.api_key}"},
            timeout=60.0,
            follow_redirects=True,
        )

    def _upload(self, client: RetryingClient, path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        ticket = client.post("/uploads/presign", json={"filename": path.name, "mime": mime, "size": len(body)})
        if ticket.status_code == 201:
            data = ticket.json()
            with RetryingClient(timeout=120.0, follow_redirects=True) as uploader:
                uploaded = uploader.put(data["upload_url"], content=body, headers=data["headers"])
            uploaded.raise_for_status()
            return str(data["url"])
        if ticket.status_code == 503:
            response = client.post(
                "/uploads", content=body,
                headers={"Content-Type": mime, "X-Filename": path.name},
            )
            response.raise_for_status()
            return str(response.json()["url"])
        ticket.raise_for_status()
        raise GenerationAdapterError("providerErr_uploadRejected", vendor=self.vendor_id, detail=ticket.text[:300])

    def _input(self, request: GenerationRequest, client: RetryingClient) -> dict[str, Any]:
        data: dict[str, Any] = {"prompt": request.prompt}
        if request.negative_prompt:
            data["negative_prompt"] = request.negative_prompt
        for key in self.parameter_surface:
            if request.parameters.get(key) is not None:
                data["n" if key == "num_images" else key] = request.parameters[key]
        if self.media_kind == "image":
            data["n"] = int(request.parameters.get("num_images", 1))
        roles = (FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE)
        for role in roles:
            values = list(request.sources_for(role))
            if not values:
                continue
            if role == REFERENCE_IMAGE:
                urls = [item.public_url or self._upload(client, item.path) for item in request.sources if item.role == role]
                data["reference_images"] = urls
            else:
                source = values[0]
                item = next(one for one in request.sources if one.role == role)
                data[role] = item.public_url or self._upload(client, source)
        return data

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        with self._client(context) as client:
            payload = {
                "model": request.model,
                "input": self._input(request, client),
                "idempotency_key": uuid.uuid4().hex,
            }
            created = client.post("/jobs", json=payload)
            if created.status_code >= 400:
                raise GenerationAdapterError("providerErr_cloudRejected", vendor=self.vendor_id, detail=created.text[:300])
            job = created.json()["job"]
            job_id = job["id"]
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while job["status"] not in {"succeeded", "failed", "cancelled"}:
                if time.monotonic() > deadline:
                    raise GenerationAdapterError("providerErr_cloudTimeout", vendor=self.vendor_id)
                time.sleep(POLL_SECONDS)
                status = client.get(f"/jobs/{job_id}")
                status.raise_for_status()
                job = status.json()["job"]
            if job["status"] != "succeeded":
                detail = (job.get("error") or {}).get("detail") or job["status"]
                raise GenerationAdapterError("providerErr_cloudFailed", vendor=self.vendor_id, detail=detail)
            output_dir.mkdir(parents=True, exist_ok=True)
            paths: list[Path] = []
            for index, artifact_id in enumerate((job.get("result") or {}).get("artifact_ids") or []):
                download = client.get(f"/jobs/{job_id}/artifacts/{artifact_id}")
                download.raise_for_status()
                suffix = Path(download.headers.get("content-disposition", "")).suffix or (".png" if self.media_kind == "image" else ".mp4")
                path = output_dir / f"cloud-{index + 1}{suffix}"
                path.write_bytes(download.content)
                paths.append(path)
            return GenerationResult(
                output_paths=paths,
                usage=metering_from_request(request),
                raw_usage=job,
            )

    def cancel_remote(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext) -> bool:
        return False
