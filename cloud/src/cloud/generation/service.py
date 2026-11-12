"""通用异步生成任务:创建、取消、worker 单步。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.domain import catalog, credits
from cloud.domain.channel_keys import unseal
from cloud.errors import CloudError
from cloud.generation.adapters import AdapterResult, JobAdapter, JobContext
from cloud.generation.storage import ArtifactStorage
from cloud.models import (
    CloudGatewayCall,
    CloudGatewayModel,
    CloudGenerationJob,
    CloudJobUsage,
    CloudMediaArtifact,
    CloudUpstreamChannel,
    CloudUpstreamProvider,
    now,
)

ACTIVE = frozenset({"queued", "submitted", "running"})
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def create_job(
    db: Session,
    *,
    user_id: str,
    device_token_id: str | None,
    model_id: str,
    idempotency_key: str,
    input: dict[str, object],
    at: datetime,
) -> CloudGenerationJob:
    existing = db.scalar(
        select(CloudGenerationJob).where(
            CloudGenerationJob.user_id == user_id,
            CloudGenerationJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    model = db.get(CloudGatewayModel, model_id)
    if model is None or not model.enabled or model.interaction != "job":
        raise CloudError(404, "gateway_model_unknown")
    price = catalog.current_price(db, model_id, at=at)
    if price is None:
        raise CloudError(404, "gateway_model_unknown")
    units = catalog.price_components(db, price.id)
    reservation = model.capability.get("reservation")
    if not isinstance(reservation, dict) or not reservation:
        raise CloudError(400, "gateway_capability_invalid")
    missing = [unit for unit in reservation if unit not in units]
    if missing:
        raise CloudError(404, "gateway_model_unknown")
    reserved = max(1, credits.cost_for_units(units, {str(k): int(v) for k, v in reservation.items()}))
    call = CloudGatewayCall(
        user_id=user_id,
        device_token_id=device_token_id,
        model_id=model_id,
        reserved=reserved,
        created_at=at,
    )
    db.add(call)
    db.flush()
    credits.reserve(db, call, at=at)
    job = CloudGenerationJob(
        user_id=user_id,
        device_token_id=device_token_id,
        model_id=model_id,
        call_id=call.id,
        idempotency_key=idempotency_key,
        status="queued",
        input=input,
        capability=dict(model.capability),
        price_snapshot={"units": units},
        created_at=at,
        updated_at=at,
    )
    db.add(job)
    db.flush()
    db.commit()
    return job


def cancel_job(db: Session, *, user_id: str, job_id: str, at: datetime) -> CloudGenerationJob:
    job = db.get(CloudGenerationJob, job_id)
    if job is None or job.user_id != user_id:
        raise CloudError(404, "job_not_found")
    if job.status in TERMINAL:
        raise CloudError(409, "job_already_finished")
    if job.provider_job_id:
        # 真正调用上游取消由 worker 处理;这里先把取消意图落库。
        pass
    job.status = "cancelled"
    job.finished_at = at
    job.updated_at = at
    call = db.get(CloudGatewayCall, job.call_id)
    if call is not None and call.status == "reserved":
        credits.settle(db, call, charged=0, at=at)
    db.commit()
    return job


def _claimed(db: Session, at: datetime) -> CloudGenerationJob | None:
    statement = (
        select(CloudGenerationJob)
        .where(
            or_(
                CloudGenerationJob.status == "queued",
                and_(
                    CloudGenerationJob.status.in_(("submitted", "running")),
                    CloudGenerationJob.next_poll_at.is_not(None),
                    CloudGenerationJob.next_poll_at <= at,
                ),
            )
        )
        .order_by(CloudGenerationJob.created_at)
        .with_for_update(skip_locked=True)
    )
    job = db.scalars(statement).first()
    if job is None:
        return None
    job.lease_until = at + timedelta(seconds=120)
    db.flush()
    return job


def _context(
    db: Session, config: CloudConfig, job: CloudGenerationJob
) -> tuple[JobContext, CloudUpstreamProvider, CloudUpstreamChannel]:
    routed = catalog.channels_in_order(db, job.model_id, at=now())
    if not routed:
        raise CloudError(503, "upstream_unavailable")
    one = routed[0]
    return (
        JobContext(
            job_id=job.id,
            model_id=job.model_id,
            input=job.input,
            capability=job.capability,
            base_url=one.provider.base_url,
            upstream_model=one.channel.upstream_model,
            api_key=unseal(config, one.provider.api_key_encrypted),
            config=one.provider.config,
        ),
        one.provider,
        one.channel,
    )


def _succeed(
    db: Session,
    job: CloudGenerationJob,
    result: AdapterResult,
    storage: ArtifactStorage,
    at: datetime,
) -> None:
    artifact_ids: list[str] = []
    for artifact in result.artifacts:
        stored = storage.save(user_id=job.user_id, job_id=job.id, artifact=artifact)
        row = CloudMediaArtifact(
            job_id=job.id,
            user_id=job.user_id,
            filename=artifact.filename,
            mime=artifact.mime,
            size=stored.size,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
            created_at=at,
        )
        db.add(row)
        db.flush()
        artifact_ids.append(row.id)
    for unit, quantity in result.usage.items():
        db.add(CloudJobUsage(job_id=job.id, unit=unit, quantity=quantity, reported=True))
    units = job.price_snapshot.get("units", {})
    charged = credits.cost_for_units({str(k): int(v) for k, v in units.items()}, result.usage)
    call = db.get(CloudGatewayCall, job.call_id)
    if call is not None:
        credits.settle(db, call, charged=charged, at=at)
    job.status = "succeeded"
    job.result = {"artifact_ids": artifact_ids}
    job.finished_at = at
    job.updated_at = at
    job.next_poll_at = None


def _fail(db: Session, job: CloudGenerationJob, code: str, detail: str, at: datetime) -> None:
    job.status = "failed"
    job.error_code = code[:80]
    job.error_detail = detail[:500]
    job.finished_at = at
    job.updated_at = at
    job.next_poll_at = None
    call = db.get(CloudGatewayCall, job.call_id)
    if call is not None and call.status == "reserved":
        credits.settle(db, call, charged=0, at=at)


def run_one(db: Session, *, config: CloudConfig, adapters: dict[str, JobAdapter], storage: ArtifactStorage) -> bool:
    """处理一个到期任务。返回是否处理了任务;worker 自己循环调用它。"""
    at = now()
    job = _claimed(db, at)
    if job is None:
        return False
    try:
        context, provider, channel = _context(db, config, job)
        adapter = adapters.get(provider.adapter)
        if adapter is None:
            _fail(db, job, "adapter_unavailable", f"no adapter registered for {provider.adapter}", at)
            db.commit()
            return True
        if job.status == "queued" or not job.provider_job_id:
            result = adapter.submit(context)
        else:
            result = adapter.poll(context, job.provider_job_id)
        job.updated_at = at
        job.lease_until = None
        if result.provider_job_id:
            job.provider_job_id = result.provider_job_id
        if result.status == "succeeded":
            _succeed(db, job, result, storage, at)
        elif result.status in {"failed", "cancelled"}:
            _fail(db, job, result.error_code or "job_failed", result.error_detail, at)
        else:
            job.status = "running" if result.status == "running" else "submitted"
            job.next_poll_at = at + timedelta(seconds=5)
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 —— worker 不能让一条坏任务把整轮拖死
        _fail(db, job, "job_error", str(exc), at)
        db.commit()
        return True
