"""MosaelCloud job 的桌面端适配器:上传素材 → 提交任务 → 轮询 → 下载结果。

Cloud 的 job 端点不是 OpenAI 形状:它只有 `POST/GET/DELETE /gateway/v1/jobs`。对话仍走
OpenAI 兼容连接;图片/视频/音频走这里,两者共享同一条 Cloud 连接和设备令牌。

**提交和等待必须拆开**(ADR 0019):提交那一刻就已经在 Cloud 扣积分。回执(`/jobs/{id}`)
在开始等之前交给运行器落库;后端重启/用户取消之后,`resume` 只轮询这一条,不再提交。
`cancel_remote` 调 Cloud 的 DELETE,但 Cloud 对已提交任务的撤销是异步的(worker 再向
上游确认),所以只有当场看到 `cancelled` 才回 True;否则运行器会接着跟到终态、按实际结算记账。
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from app.ai.media_transfer import download_to_path
from app.ai.providers.adapters.shared.polling import poll_until_ready
from app.ai.providers.contracts.generation import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    ReportedUsage,
    metering_from_request,
)
from app.core.http_retry import RetryingClient

#: Cloud job 响应里的终态。`cancel_requested` 还在 worker 那边撤,属于进行中。
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def _job(payload: dict[str, Any]) -> dict[str, Any]:
    job = payload.get("job") if isinstance(payload, dict) else None
    return job if isinstance(job, dict) else {}


def _rejection_detail(response: object) -> str:
    """Cloud 的拒绝原因:优先取它给中英双语 `message` 的中文,取不到再退回原始响应。"""
    try:
        body = response.json()  # type: ignore[attr-defined]
    except ValueError:
        return response.text[:300]  # type: ignore[attr-defined]
    message = body.get("message") if isinstance(body, dict) else None
    if isinstance(message, dict):
        return str(message.get("zh") or message.get("en") or "")
    if isinstance(message, str):
        return message
    error = body.get("error") if isinstance(body, dict) else None
    return str(error or response.text[:300])  # type: ignore[attr-defined]


class MosaelCloudJobAdapter(GenerationAdapter):
    vendor_id = "mosael-cloud"
    supports_resume = True
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

    def reported_usage(self, raw_usage: dict[str, Any]) -> ReportedUsage:
        """Cloud 结算后回报的用量。单位按本地价目表翻译,`charged_credits` 只作核对,不冒充货币。"""
        usage = raw_usage.get("usage") if isinstance(raw_usage, dict) else None
        units: dict[str, int] = {}
        if isinstance(usage, dict):
            for unit, quantity in usage.items():
                if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
                    continue
                local = {
                    "second": "audio_second" if self.media_kind == "audio" else "video_second",
                    "image": "image",
                }.get(str(unit), str(unit))
                units[local] = quantity
        charged = raw_usage.get("charged_credits") if isinstance(raw_usage, dict) else None
        observed = {"cloud_charged_credits": charged} if isinstance(charged, int) and not isinstance(charged, bool) else {}
        return ReportedUsage(units=units, observed=observed)

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        with self._client(context) as client:
            payload = {
                "model": request.model,
                "input": self._input(request, client),
                #: 同一份生成记录的重试必须用同一个键。空串只出现在直接调 Adapter 的测试里。
                "idempotency_key": request.idempotency_key or uuid.uuid4().hex,
            }
            created = client.post("/jobs", json=payload)
            if created.status_code >= 400:
                raise GenerationAdapterError(
                    "providerErr_cloudRejected", vendor=self.vendor_id,
                    detail=_rejection_detail(created),
                )
            job = _job(created.json())
            job_id = str(job.get("id") or "")
            if not job_id:
                raise GenerationAdapterError("providerErr_cloudRejected", vendor=self.vendor_id, detail="no job id")
            return self._collect(client, f"/jobs/{job_id}", request, context, output_dir)

    def resume(
        self,
        poll_path: str,
        request: GenerationRequest,
        context: GenerationAdapterContext,
        output_dir: Path,
    ) -> GenerationResult:
        """只接着取,绝不重新提交 —— 提交一次就已经扣一次积分。"""
        with self._client(context) as client:
            return self._collect(client, poll_path, request, context, output_dir)

    def cancel_remote(
        self,
        poll_path: str,
        request: GenerationRequest,
        context: GenerationAdapterContext,
    ) -> bool:
        """请 Cloud 撤销。只有当场看到 `cancelled` 才算真的撤掉(没做、不扣)。

        Cloud 对已提交任务先落 `cancel_requested`,由 worker 向上游确认;那个过程可能失败、也可能
        来不及。返回 False 时运行器会继续跟到终态并按实际结算记账,不会把「请求撤销」当成「没扣费」。
        """
        try:
            with self._client(context) as client:
                response = client.delete(poll_path)
                if response.status_code >= 400:
                    return False
                status = client.get(poll_path)
                if status.status_code >= 400:
                    return False
                return str(_job(status.json()).get("status") or "") == "cancelled"
        except Exception:  # noqa: BLE001 —— 撤销是尽力而为,失败交给运行器跟终态
            return False

    def _collect(
        self,
        client: RetryingClient,
        poll_path: str,
        request: GenerationRequest,
        context: GenerationAdapterContext,
        output_dir: Path,
    ) -> GenerationResult:
        artifact_ids, payload = poll_until_ready(
            client, poll_path, self._extract, vendor="MosaelCloud",
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        base = (context.base_url or "").rstrip("/")
        paths: list[Path] = []
        for index, artifact_id in enumerate(artifact_ids, start=1):
            target = output_dir / f"cloud-{index}"
            content_type = download_to_path(
                f"{base}{poll_path}/artifacts/{artifact_id}",
                target,
                trusted_base_url=base,
                trusted_headers={"Authorization": f"Bearer {context.api_key}"},
                timeout=180,
            )
            suffix = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
            if suffix:
                renamed = target.with_suffix(suffix)
                target.replace(renamed)
                target = renamed
            paths.append(target)
        return GenerationResult(
            output_paths=paths,
            usage=metering_from_request(request),
            #: `reported_usage` 读的是 job 本体(usage / charged_credits);外面那层信封只属于协议。
            raw_usage=_job(payload),
        )

    def _extract(self, payload: dict[str, Any]) -> list[str] | None:
        """轮询回包 → 还没完成回 None,完成回 artifact id 串,失败抛出。"""
        job = _job(payload)
        status = str(job.get("status") or "")
        if status not in _TERMINAL:
            return None
        if status != "succeeded":
            detail = (job.get("error") or {}).get("detail") if isinstance(job.get("error"), dict) else None
            raise GenerationAdapterError(
                "providerErr_cloudFailed", vendor=self.vendor_id, detail=str(detail or status),
            )
        ids = (job.get("result") or {}).get("artifact_ids") if isinstance(job.get("result"), dict) else None
        artifact_ids = [str(one) for one in ids or [] if one]
        if not artifact_ids:
            raise GenerationAdapterError("providerErr_cloudNoResult", vendor=self.vendor_id)
        return artifact_ids
