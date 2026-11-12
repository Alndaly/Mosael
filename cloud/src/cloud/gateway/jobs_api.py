"""通用异步生成任务的 HTTP 入口;鉴权只认设备令牌。"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from cloud.api.deps import DbSession
from cloud.errors import CloudError
from cloud.gateway.deps import CurrentDevice
from cloud.generation import service
from cloud.models import CloudGenerationJob, CloudMediaArtifact, now

router = APIRouter(prefix="/gateway/v1", tags=["gateway"])


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
    path = request.app.state.artifact_storage.path(artifact.storage_key)
    if not path.is_file():
        raise CloudError(404, "artifact_not_found")
    return FileResponse(path, media_type=artifact.mime, filename=artifact.filename)
