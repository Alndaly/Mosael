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
from cloud.generation.validation import estimated_units, normalize_job_input
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

ACTIVE = frozenset({"queued", "submitting", "submitted", "running", "cancel_requested"})
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
#: 一次 claim 的租约。它挡住「上一个 worker 还活着、只是慢」时的第二个 claim;到期由下一个 worker 接管。
LEASE_SECONDS = 120
#: 排队超过这么久还没有 worker 处理:不再无限占积分,直接失败并释放预占。桌面端自己等 Cloud 的上限是 1 小时。
QUEUED_TTL = timedelta(hours=1)


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
    input = normalize_job_input(input)
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
        raise CloudError(422, "gateway_model_price_incomplete", units=", ".join(missing))
    estimate = estimated_units(reservation, input)
    missing_estimate = [unit for unit in estimate if unit not in units]
    if missing_estimate:
        raise CloudError(422, "gateway_model_price_incomplete", units=", ".join(missing_estimate))
    reserved = max(1, credits.cost_for_units(units, estimate))
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


def find_by_idempotency(db: Session, *, user_id: str, idempotency_key: str) -> CloudGenerationJob | None:
    """同一个用户、同一个幂等键已有的任务。API 在 worker 能力 gate 之前先查它:重放旧请求要拿到旧任务,不能被 503。"""
    return db.scalar(
        select(CloudGenerationJob).where(
            CloudGenerationJob.user_id == user_id,
            CloudGenerationJob.idempotency_key == idempotency_key,
        )
    )


def reconcile_uncertain_submits(db: Session, *, at: datetime) -> int:
    """收尾「提交已经发出、结果没写回」的任务。**绝不自动重提** —— 上游可能已经收下并扣费。

    有 `provider_job_id` 的接回轮询;没有的记 `submit_outcome_unknown` 并按预占收费(与「取消时撤销
    没确认」同一条风控:宁可让用户找客服退,也不白送一次上游生成)。返回处理了几条。
    """
    rows = list(db.scalars(
        select(CloudGenerationJob)
        .where(CloudGenerationJob.status == "submitting")
        .with_for_update(skip_locked=True)
    ))
    for job in rows:
        if job.provider_job_id:
            job.status = "submitted"
            job.next_poll_at = at
        else:
            job.status = "failed"
            job.error_code = "submit_outcome_unknown"
            job.error_detail = "worker stopped between submit and provider job id; not resubmitted"
            job.finished_at = at
            job.updated_at = at
            job.next_poll_at = None
            call = db.get(CloudGatewayCall, job.call_id)
            if call is not None and call.status == "reserved":
                credits.settle(db, call, charged=call.reserved, at=at)
        job.lease_until = None
        job.updated_at = at
    return len(rows)


def expire_queued_jobs(db: Session, *, at: datetime, older_than: timedelta = QUEUED_TTL) -> int:
    """没有 worker 的部署不能无限接单:排队超过 TTL 的任务失败并全额释放预占。"""
    rows = list(db.scalars(
        select(CloudGenerationJob)
        .where(CloudGenerationJob.status == "queued", CloudGenerationJob.created_at <= at - older_than)
        .with_for_update(skip_locked=True)
    ))
    for job in rows:
        job.status = "failed"
        job.error_code = "worker_unavailable"
        job.error_detail = "no generation worker processed this job before its queue deadline"
        job.finished_at = at
        job.updated_at = at
        job.next_poll_at = None
        call = db.get(CloudGatewayCall, job.call_id)
        if call is not None and call.status == "reserved":
            credits.settle(db, call, charged=0, at=at)
    return len(rows)


def cancel_job(db: Session, *, user_id: str, job_id: str, at: datetime) -> CloudGenerationJob:
    #: **锁住任务行再判断。** worker 领到排队的任务后,在持锁状态下调上游 submit(要几秒);此前这里不加锁读,读到「还没提交」
    #: 就全额退预占,它的 UPDATE 等 worker 提交后再执行,把「已提交上游」覆盖成「已取消」—— 上游照跑、平台付钱、用户 0 扣。
    #: 现在等 worker 提交完再读:提交了的走下面「先请 worker 去取消」那条路。
    job = db.scalars(select(CloudGenerationJob).where(CloudGenerationJob.id == job_id).with_for_update()).first()
    if job is None or job.user_id != user_id:
        raise CloudError(404, "job_not_found")
    if job.status in TERMINAL:
        raise CloudError(409, "job_already_finished")
    if job.status == "cancel_requested":
        return job
    if job.provider_job_id or job.status == "submitting":
        # 已提交上游、或者提交请求正在路上:**先不要退款**。worker 会领取这个状态、尝试真正取消;
        # 只有适配器确认取消成功才释放预占。否则“提交后立刻取消”就是免费烧上游额度的入口。
        job.status = "cancel_requested"
        job.updated_at = at
        db.commit()
        return job
    job.status = "cancelled"
    job.finished_at = at
    job.updated_at = at
    call = db.get(CloudGatewayCall, job.call_id)
    if call is not None and call.status == "reserved":
        credits.settle(db, call, charged=0, at=at)
    db.commit()
    return job


def _claimed(db: Session, at: datetime) -> CloudGenerationJob | None:
    lease_ready = or_(CloudGenerationJob.lease_until.is_(None), CloudGenerationJob.lease_until <= at)
    statement = (
        select(CloudGenerationJob)
        .where(
            lease_ready,
            or_(
                CloudGenerationJob.status.in_(("queued", "cancel_requested")),
                and_(
                    CloudGenerationJob.status.in_(("submitted", "running")),
                    CloudGenerationJob.next_poll_at.is_not(None),
                    CloudGenerationJob.next_poll_at <= at,
                ),
            ),
        )
        .order_by(CloudGenerationJob.created_at)
        .with_for_update(skip_locked=True)
    )
    job = db.scalars(statement).first()
    if job is None:
        return None
    job.lease_until = at + timedelta(seconds=LEASE_SECONDS)
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
        if job.status == "cancel_requested":
            cancelled = False
            try:
                cancelled = bool(adapter.cancel(context, job.provider_job_id or ""))
            except Exception:  # noqa: BLE001 —— 取消失败不能留下“免费取消”的口子
                cancelled = False
            job.status = "cancelled"
            job.finished_at = at
            job.updated_at = at
            job.next_poll_at = None
            call = db.get(CloudGatewayCall, job.call_id)
            if call is not None and call.status == "reserved":
                #: 上游确认取消 → 全额释放；没确认 → 按预占收，避免反复提交/取消烧供应商额度。
                credits.settle(db, call, charged=0 if cancelled else call.reserved, at=at)
            db.commit()
            return True
        if job.status == "queued" or not job.provider_job_id:
            #: **先把「提交已经发出」落库,再发网络请求。** 中间崩溃时下一次启动看到 `submitting`
            #: 会按结局不明收尾,而不是再提交一次(上游可能已经扣过费)。
            job.status = "submitting"
            job.submit_started_at = at
            job.updated_at = at
            db.commit()
            try:
                result = adapter.submit(context)
            except Exception as exc:  # noqa: BLE001 —— 提交阶段异常可能是「对方收到了但没回」
                job.status = "failed"
                job.error_code = "submit_outcome_unknown"
                job.error_detail = str(exc)[:500]
                job.finished_at = at
                job.updated_at = at
                job.next_poll_at = None
                job.lease_until = None
                call = db.get(CloudGatewayCall, job.call_id)
                if call is not None and call.status == "reserved":
                    credits.settle(db, call, charged=call.reserved, at=at)
                db.commit()
                return True
        else:
            result = adapter.poll(context, job.provider_job_id)
        #: 提交期间用户可能点了取消。刷新后先尊重那一行,不把 result 覆盖上去。
        db.refresh(job)
        if job.status == "cancel_requested":
            if result.provider_job_id:
                job.provider_job_id = result.provider_job_id
            job.next_poll_at = at
            job.lease_until = None
            job.submit_started_at = None
            job.updated_at = at
            db.commit()
            return True
        job.updated_at = at
        job.lease_until = None
        job.submit_started_at = None
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
