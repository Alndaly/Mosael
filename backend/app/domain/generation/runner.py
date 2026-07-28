from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path

from app.ai.providers import GenerationRequest, GenerationResult, ProviderContext, ProviderError, get_provider
from app.ai.providers.base import sanitize_provider_error
from app.core.db import SessionLocal
from app.db.models import Asset, GeneratedAsset, GenerationJob, Job
from app.domain.jobs import dispatch_job, emit_job_event
from app.domain.assets.importer import register_file_asset
from app.media.paths import resolve_key
from app.domain.usage import record_usage

"""
Generation runner: executes a generation job off-thread. Results always land
as assets + generated_assets rows (plan §18.4) — never as loose temp files.
"""

logger = logging.getLogger(__name__)


def start_generation_thread(generation_id: str) -> None:
    """按 ai_generation 的执行模式派发(名字保留:四个调用方不需要知道派发细节)。

    调用方先 create_generation_job + commit 再调这里,所以能安全地重开会话取 job;
    external 模式下 dispatch 只把 job 标成等待认领,不起线程。"""
    with SessionLocal() as db:
        generation = db.get(GenerationJob, generation_id)
        job = db.get(Job, generation.job_id) if generation is not None and generation.job_id else None
        if job is None:
            return
        dispatch_job(db, job, lambda: _run_generation(generation_id))


def _run_generation(generation_id: str) -> None:
    with SessionLocal() as db:
        generation = db.get(GenerationJob, generation_id)
        if generation is None or not generation.job_id:
            return
        job = db.get(Job, generation.job_id)
        if job is None:
            return

        provider = get_provider(generation.provider, generation.kind)
        if provider is None:
            _fail(db, job, f"No adapter for provider {generation.provider}/{generation.kind}")
            return

        from app.domain.providers import resolve_profile

        profile = resolve_profile(db, generation.provider, generation.provider_profile_id)
        if provider.requires_credentials() and (profile is None or not profile.api_key):
            _fail(db, job, f"Provider profile for {generation.provider} is not configured")
            return
        context = ProviderContext(
            profile_id=profile.id if profile is not None else None,
            vendor=profile.vendor if profile is not None else generation.provider,
            api_key=profile.api_key if profile is not None else "",
            base_url=profile.base_url if profile is not None else "",
            default_model=profile.default_model if profile is not None else "",
            extra=dict(profile.extra or {}) if profile is not None else {},
        )
        job.status = "running"
        job.message = "Generating"
        emit_job_event(db, job.id, "job.running", {"provider": generation.provider})
        db.commit()
        logger.info(
            "generation job %s: provider=%s model=%s kind=%s",
            job.id,
            generation.provider,
            generation.model,
            generation.kind,
        )

        workdir = Path(tempfile.mkdtemp(prefix="open-studio-gen-"))
        request: GenerationRequest | None = None
        started = time.monotonic()
        try:
            request = GenerationRequest(
                kind=generation.kind,
                model=generation.model,
                prompt=str(generation.request.get("prompt", "")),
                negative_prompt=str(generation.request.get("negative_prompt", "")),
                parameters=dict(generation.request.get("parameters") or {}),
                source_files=_source_files_for_generation(db, generation),
            )
            provider.validate_request(request)
            if getattr(provider, "supports_callbacks", False):
                result = provider.generate(request, context, workdir, callbacks=_job_callbacks(db, job))
            else:
                result = provider.generate(request, context, workdir)
            asset = register_file_asset(
                db,
                workspace_id=job.workspace_id,
                project_id=generation.request.get("project_id"),
                source_path=result.output_path,
                name=_asset_name(request.prompt, generation.model),
                source="generated",
            )
            db.add(
                GeneratedAsset(
                    asset_id=asset.id,
                    provider=generation.provider,
                    model=generation.model,
                    prompt=request.prompt,
                    parameters=request.parameters,
                    job_id=job.id,
                )
            )
            generation.result_asset_id = asset.id
            job.status = "succeeded"
            job.progress = 1.0
            job.message = "Generation complete"
            job.result = {"asset_id": asset.id}
            _record_generation_usage(db, generation, job, request, context, result, started, "succeeded")
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
            db.commit()
            logger.info(
                "generation job %s succeeded in %.1fs (%s/%s) → asset %s",
                job.id,
                time.monotonic() - started,
                generation.provider,
                generation.model,
                asset.id,
            )
        except ProviderError as exc:
            if request is not None:
                _record_generation_usage(db, generation, job, request, context, None, started, "failed")
            # 用户取消时 cancel_job 已落终态并写好「已取消」;再 _fail 会把它改写成
            # 泛化的 Generation failed,取消看起来就像出了错。
            if job.status in ("queued", "running"):
                _fail(db, job, str(exc))
            else:
                db.commit()
        except Exception as exc:  # defensive: worker threads must never die silently
            if request is not None:
                _record_generation_usage(db, generation, job, request, context, None, started, "failed")
            _fail(db, job, sanitize_provider_error(str(exc), context.api_key))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _job_callbacks(db, job: Job):
    """Bridge a provider's poll loop to the job row: progress writes through (capped below
    1.0 — completion belongs to asset registration), cancellation reads the row back so a
    user cancel reaches the provider between round-trips."""
    from app.ai.providers import GenerationCallbacks

    def on_progress(fraction: float, message: str) -> None:
        job.progress = min(0.95, max(float(job.progress or 0.0), float(fraction)))
        if message:
            job.message = message[:200]
        db.commit()

    def is_cancelled() -> bool:
        db.refresh(job)
        return job.status not in ("queued", "running")

    return GenerationCallbacks(on_progress=on_progress, is_cancelled=is_cancelled)


def _fail(db, job: Job, message: str) -> None:
    job.status = "failed"
    job.message = "Generation failed"
    job.error = message[:500]
    emit_job_event(db, job.id, "job.failed", {})
    db.commit()
    logger.warning("generation job %s failed: %s", job.id, message)


def _source_files_for_generation(db, generation: GenerationJob) -> tuple[Path, ...]:
    source_asset_ids = generation.request.get("source_asset_ids") or []
    paths: list[Path] = []
    for asset_id in source_asset_ids:
        asset = db.get(Asset, str(asset_id))
        if asset is None or asset.workspace_id != generation.workspace_id:
            raise ProviderError("首帧素材不存在或不属于当前工作区")
        if asset.kind != "image":
            raise ProviderError("首帧素材必须是图片")
        if not asset.file_key:
            raise ProviderError("首帧素材缺少本地文件")
        path = resolve_key(asset.file_key)
        if not path.is_file():
            raise ProviderError("首帧素材文件不存在")
        paths.append(path)
    return tuple(paths)


def _record_generation_usage(
    db,
    generation: GenerationJob,
    job: Job,
    request: GenerationRequest,
    context: ProviderContext,
    result: GenerationResult | None,
    started: float,
    status: str,
) -> None:
    duration_seconds = round(max(0.0, time.monotonic() - started), 1)
    units = dict(result.usage if result is not None else {})
    if "requests" not in units:
        units["requests"] = 1
    if request.kind == "image":
        units.setdefault("images", int(request.parameters.get("num_images", 1)))
        units.setdefault("source_images", len(request.source_files))
        if request.parameters.get("size"):
            units.setdefault("size", str(request.parameters["size"]).replace("*", "x"))
    if request.kind == "video":
        units.setdefault("videos", 1)
        units.setdefault("video_seconds", float(request.parameters.get("duration_seconds", 5)))
        units.setdefault("resolution", str(request.parameters.get("resolution", "720p")))
        units.setdefault("aspect_ratio", str(request.parameters.get("aspect_ratio", "")))
        units.setdefault("source_images", len(request.source_files))
    record_usage(
        db,
        workspace_id=job.workspace_id,
        provider_profile_id=context.profile_id,
        provider=generation.provider,
        model=generation.model,
        capability=generation.kind,
        operation="generation_job",
        source_type="generation_job",
        source_id=generation.id,
        idempotency_key=f"generation:{generation.id}:{status}",
        status=status,
        duration_seconds=duration_seconds,
        units=units,
        raw_usage=result.raw_usage if result is not None else {},
        job_id=job.id,
    )


def _asset_name(prompt: str, model: str) -> str:
    summary = prompt.strip().splitlines()[0][:40] if prompt.strip() else "Generation"
    return f"{summary} · {model}"
