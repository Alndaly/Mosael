from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from app.ai.providers import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    GenerationRequest,
    GenerationResult,
    GenerationAdapterContext,
    GenerationAdapterError,
    SourceAsset,
    get_generation_adapter,
)
from app.ai.providers.contracts.generation import sanitize_adapter_error
from app.core.db import SessionLocal
from app.db.models import Asset, GeneratedAsset, GenerationJob, Job
from app.domain import provider_models
from app.domain.jobs import dispatch_job, emit_job_event, say
from app.domain.assets.importer import register_file_asset
from app.media.paths import resolve_key
from app.domain.usage import billable

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

        adapter = get_generation_adapter(generation.provider, generation.kind)
        if adapter is None:
            _fail(db, job, f"No adapter for provider {generation.provider}/{generation.kind}")
            return

        from app.domain.providers import resolve_connection

        # 这次生成替谁干:job 上记着(见 Job.created_by)—— 用他的钥匙、花他的额度。
        profile = resolve_connection(db, generation.provider, generation.provider_profile_id, user_id=job.created_by)
        if adapter.requires_credentials() and (profile is None or not profile.api_key):
            _fail(db, job, f"供应商 {generation.provider} 还没有配置你的密钥,请先在设置里填写")
            return
        context = GenerationAdapterContext(
            connection_id=profile.id if profile is not None else None,
            vendor_id=profile.vendor if profile is not None else generation.provider,
            api_key=profile.api_key if profile is not None else "",
            base_url=profile.base_url if profile is not None else "",
            # 这条连接在本次生成的能力下该用的模型。此前取 profile.default_model ——
            # 那个字段不区分能力,对话档案的默认模型被拿去当生图模型用过。
            configured_model_id=provider_models.model_id_for(db, profile, generation.kind),
            options=dict(profile.extra or {}) if profile is not None else {},
        )
        job.status = "running"
        say(job, "jobMsg_generationRunning")
        emit_job_event(db, job.id, "job.running", {"provider": generation.provider})
        db.commit()
        logger.info(
            "generation job %s: provider=%s model=%s kind=%s",
            job.id,
            generation.provider,
            generation.model,
            generation.kind,
        )

        workdir = Path(tempfile.mkdtemp(prefix="mosael-gen-"))
        request: GenerationRequest | None = None
        started = time.monotonic()
        try:
            request = GenerationRequest(
                kind=generation.kind,
                model=generation.model,
                prompt=str(generation.request.get("prompt", "")),
                negative_prompt=str(generation.request.get("negative_prompt", "")),
                parameters=dict(generation.request.get("parameters") or {}),
                sources=_sources_for_generation(db, generation),
            )
            adapter.validate_request(request)
            if adapter.supports_progress_callbacks:
                result = adapter.generate(request, context, workdir, callbacks=_job_callbacks(db, job))
            else:
                result = adapter.generate(request, context, workdir)
            #: **每一份产出都登记。** 图像接口的 n 一次会返回多张,此前这里只收一份 ——
            #: 用户选了 4 张、按 4 张计了费,库里只多出一张,其余的连同它们的钱一起消失。
            assets = [
                register_file_asset(
                    db,
                    workspace_id=job.workspace_id,
                    project_id=generation.request.get("project_id"),
                    source_path=path,
                    name=_asset_name(request.prompt, generation.model),
                    source="generated",
                )
                for path in result.output_paths
            ]
            if not assets:
                raise GenerationAdapterError("Provider returned no output")
            for asset in assets:
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
            #: 这一栏是**封面**:一次生成对多份产出,而它只放得下一个。想要全部的走
            #: GeneratedAsset(每一份都有一行),或者读回执里的 asset_ids。
            generation.result_asset_id = assets[0].id
            asset_ids = [one.id for one in assets]
            job.status = "succeeded"
            job.progress = 1.0
            say(job, "jobMsg_generationDone")
            #: 回执里放**一串**。收成单数的话,消费方拿到的永远只是第一张 —— 而这正是
            #: 多出来那几张此前消失的地方。
            job.result = {"asset_ids": asset_ids}
            _record_generation_usage(db, generation, job, request, context, result, started, "succeeded")
            emit_job_event(db, job.id, "job.succeeded", {"asset_ids": asset_ids})
            db.commit()
            logger.info(
                "generation job %s succeeded in %.1fs (%s/%s) → assets %s",
                job.id,
                time.monotonic() - started,
                generation.provider,
                generation.model,
                ", ".join(asset_ids),
            )
        except GenerationAdapterError as exc:
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
            _fail(db, job, sanitize_adapter_error(str(exc), context.api_key))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _job_callbacks(db, job: Job):
    """Bridge an Adapter's poll loop to the job row: progress writes through (capped below
    1.0 — completion belongs to asset registration), cancellation reads the row back so a
    user cancel reaches the Adapter between round-trips."""
    from app.ai.providers import GenerationProgressCallbacks

    def on_progress(fraction: float, message: str) -> None:
        job.progress = min(0.95, max(float(job.progress or 0.0), float(fraction)))
        if message:
            say(job, message[:200])
        db.commit()

    def is_cancelled() -> bool:
        db.refresh(job)
        return job.status not in ("queued", "running")

    return GenerationProgressCallbacks(on_progress=on_progress, is_cancelled=is_cancelled)


def _fail(db, job: Job, message: str) -> None:
    job.status = "failed"
    say(job, "jobMsg_generationFailed")
    job.error = message[:500]
    emit_job_event(db, job.id, "job.failed", {})
    db.commit()
    logger.warning("generation job %s failed: %s", job.id, message)


#: 每种角色收什么素材。参考视频收视频,其余收图片 —— 这一条是**校验**,不是描述:
#: 把一段视频当首帧递上去,各家的报错五花八门(有的干脆生成出一片黑),不如在这里拦住。
ROLE_ASSET_KIND = {
    FIRST_FRAME: "image",
    LAST_FRAME: "image",
    REFERENCE_IMAGE: "image",
    REFERENCE_VIDEO: "video",
}

#: 报错里那个词。写死「首帧」的话,尾帧缺文件时用户看到的是「首帧素材文件不存在」。
ROLE_LABEL = {
    FIRST_FRAME: "首帧",
    LAST_FRAME: "尾帧",
    REFERENCE_IMAGE: "参考图",
    REFERENCE_VIDEO: "参考视频",
}


def _sources_for_generation(db, generation: GenerationJob) -> tuple[SourceAsset, ...]:
    """把请求里记的素材引用解析成本地文件,**保住各自的角色**。"""
    sources: list[SourceAsset] = []
    for entry in generation.request.get("source_assets") or []:
        role = str(entry.get("role") or FIRST_FRAME)
        label = ROLE_LABEL.get(role, role)
        asset = db.get(Asset, str(entry.get("asset_id") or ""))
        if asset is None or asset.workspace_id != generation.workspace_id:
            raise GenerationAdapterError(f"{label}素材不存在或不属于当前工作区")
        expected = ROLE_ASSET_KIND.get(role, "image")
        if asset.kind != expected:
            raise GenerationAdapterError(f"{label}素材必须是{'视频' if expected == 'video' else '图片'}")
        if not asset.file_key:
            raise GenerationAdapterError(f"{label}素材缺少本地文件")
        path = resolve_key(asset.file_key)
        if not path.is_file():
            raise GenerationAdapterError(f"{label}素材文件不存在")
        sources.append(SourceAsset(role=role, path=path))
    return tuple(sources)


def _record_generation_usage(
    db,
    generation: GenerationJob,
    job: Job,
    request: GenerationRequest,
    context: GenerationAdapterContext,
    result: GenerationResult | None,
    started: float,
    status: str,
) -> None:
    units = dict(result.usage if result is not None else {})
    if "requests" not in units:
        units["requests"] = 1
    if request.kind == "image":
        units.setdefault("images", int(request.parameters.get("num_images", 1)))
        units.setdefault("source_images", len(request.sources))
        if request.parameters.get("size"):
            units.setdefault("size", str(request.parameters["size"]).replace("*", "x"))
    if request.kind == "video":
        units.setdefault("videos", 1)
        units.setdefault("video_seconds", float(request.parameters.get("duration_seconds", 5)))
        units.setdefault("resolution", str(request.parameters.get("resolution", "720p")))
        units.setdefault("aspect_ratio", str(request.parameters.get("aspect_ratio", "")))
        units.setdefault("source_images", len(request.sources))
    with billable(
        db,
        capability=generation.kind,
        operation="generation_job",
        workspace_id=job.workspace_id,
        provider_profile_id=context.connection_id,
        provider=generation.provider,
        model=generation.model,
        source_type="generation_job",
        source_id=generation.id,
        job_id=job.id,
        idempotency_key=f"generation:{generation.id}:{status}",
        started=started,
    ) as call:
        call.meter(units, raw=result.raw_usage if result is not None else {})
        if status != "succeeded":
            # 这里的失败是**捕获后**记的(runner 自己处理了异常),billable 看不见,得显式说。
            call.mark_failed()

def _asset_name(prompt: str, model: str) -> str:
    summary = prompt.strip().splitlines()[0][:40] if prompt.strip() else "Generation"
    return f"{summary} · {model}"
