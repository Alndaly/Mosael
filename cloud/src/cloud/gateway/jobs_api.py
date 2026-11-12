"""通用异步生成任务的 HTTP 入口;鉴权只认设备令牌。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from cloud.api.deps import CurrentConfig, DbSession
from cloud.config import API_PREFIX
from cloud.errors import CloudError
from cloud.gateway.deps import CurrentDevice
from cloud.generation import service
from cloud.generation.adapters import AdapterArtifact
from cloud.models import CloudGenerationJob, CloudMediaArtifact, CloudMediaUpload, now
from cloud.security import new_token

router = APIRouter(prefix="/gateway/v1", tags=["gateway"])

#: 输入素材上限;视频首帧/参考视频可到几十 MB,留足余量。
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class UploadTicketIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    mime: str = Field(min_length=1, max_length=120)
    size: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    sha256: str = Field(default="", max_length=64)


class JobIn(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    input: dict[str, object]
    idempotency_key: str = Field(min_length=1, max_length=120)


def _view(job: CloudGenerationJob) -> dict[str, object]:
    return {
        "id": job.id,
        "model": job.model_id,
        "status": job.status,
        "result": job.result,
        "error": {"code": job.error_code, "detail": job.error_detail} if job.error_code else None,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("/jobs", status_code=201)
def create_job(body: JobIn, device: CurrentDevice, db: DbSession) -> dict[str, object]:
    job = service.create_job(
        db,
        user_id=device.user.id,
        device_token_id=device.token.id,
        model_id=body.model,
        idempotency_key=body.idempotency_key,
        input=body.input,
        at=now(),
    )
    return {"job": _view(job)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, device: CurrentDevice, db: DbSession) -> dict[str, object]:
    job = db.get(CloudGenerationJob, job_id)
    if job is None or job.user_id != device.user.id:
        raise CloudError(404, "job_not_found")
    return {"job": _view(job)}


@router.delete("/jobs/{job_id}", status_code=204)
def cancel_job(job_id: str, device: CurrentDevice, db: DbSession) -> Response:
    service.cancel_job(db, user_id=device.user.id, job_id=job_id, at=now())
    return Response(status_code=204)


@router.get("/jobs/{job_id}/artifacts/{artifact_id}")
def get_artifact(job_id: str, artifact_id: str, request: Request, device: CurrentDevice, db: DbSession) -> FileResponse:
    artifact = db.get(CloudMediaArtifact, artifact_id)
    if artifact is None or artifact.job_id != job_id or artifact.user_id != device.user.id:
        raise CloudError(404, "artifact_not_found")
    storage = request.app.state.artifact_storage
    if storage.direct_upload:
        public = storage.public_url(artifact.storage_key)
        if public is None:
            raise CloudError(503, "storage_not_configured")
        return RedirectResponse(public, status_code=302)
    path = storage.path(artifact.storage_key)
    if not path.is_file():
        raise CloudError(404, "artifact_not_found")
    return FileResponse(path, media_type=artifact.mime, filename=artifact.filename)


@router.post("/uploads/presign", status_code=201)
def presign_upload(body: UploadTicketIn, request: Request, device: CurrentDevice, config: CurrentConfig, db: DbSession) -> dict[str, object]:
    storage = request.app.state.artifact_storage
    if not storage.direct_upload:
        raise CloudError(503, "direct_upload_not_configured")
    filename = Path(body.filename).name[:200] or "upload.bin"
    token = new_token(24)
    storage_key = f"uploads/{device.user.id}/{token}-{filename}"
    at = now()
    row = CloudMediaUpload(
        user_id=device.user.id,
        filename=filename,
        mime=body.mime,
        size=body.size,
        sha256=body.sha256,
        storage_key=storage_key,
        public_token=token,
        created_at=at,
        expires_at=at + timedelta(days=1),
    )
    db.add(row)
    db.commit()
    public = storage.public_url(storage_key)
    if public is None:
        raise CloudError(503, "storage_not_configured")
    return {
        "id": row.id,
        "method": "PUT",
        "upload_url": storage.presign_put(storage_key=storage_key, mime=body.mime, size=body.size),
        "url": public,
        "headers": {"Content-Type": body.mime},
        "expires_at": row.expires_at.isoformat(),
    }


@router.post("/uploads", status_code=201)
async def upload_media(request: Request, device: CurrentDevice, config: CurrentConfig, db: DbSession) -> dict[str, object]:
    if request.app.state.artifact_storage.direct_upload:
        raise CloudError(410, "upload_via_presign")
    body = await request.body()
    if not body or len(body) > MAX_UPLOAD_BYTES:
        raise CloudError(413, "upload_too_large")
    filename = request.headers.get("x-filename", "upload.bin")[:200]
    mime = request.headers.get("content-type", "application/octet-stream").split(";")[0][:120]
    stored = request.app.state.artifact_storage.save(
        user_id=device.user.id, job_id="uploads",
        artifact=AdapterArtifact(filename=filename, mime=mime, data=body),
    )
    token = new_token(24)
    at = now()
    row = CloudMediaUpload(
        user_id=device.user.id,
        filename=filename,
        mime=mime,
        size=stored.size,
        sha256=stored.sha256,
        storage_key=stored.storage_key,
        public_token=token,
        created_at=at,
        expires_at=at + timedelta(days=1),
    )
    db.add(row)
    db.commit()
    public_url = f"{config.public_url}{API_PREFIX}/gateway/v1/uploads/public/{token}"
    return {"id": row.id, "url": public_url, "mime": mime, "size": stored.size, "sha256": stored.sha256}


@router.get("/uploads/public/{token}")
def public_upload(token: str, request: Request, db: DbSession) -> FileResponse:
    row = db.scalar(select(CloudMediaUpload).where(CloudMediaUpload.public_token == token))
    if row is None or row.expires_at <= now():
        raise CloudError(404, "upload_not_found")
    storage = request.app.state.artifact_storage
    if storage.direct_upload:
        public = storage.public_url(row.storage_key)
        if public is None:
            raise CloudError(503, "storage_not_configured")
        return RedirectResponse(public, status_code=302)
    path = storage.path(row.storage_key)
    if not path.is_file():
        raise CloudError(404, "upload_not_found")
    return FileResponse(path, media_type=row.mime, filename=row.filename)
