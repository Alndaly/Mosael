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
    RemoteTaskWatch,
    SourceAsset,
    get_generation_adapter,
    watching_remote_tasks,
)
from app.ai.providers.contracts.generation import direct_media_url, sanitize_adapter_error
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.i18n import LocalizedError, tr
from app.db.models import Asset, GeneratedAsset, GenerationJob, Job
from app.domain import provider_models
from app.domain.jobs import blame, dispatch_job, emit_job_event, finish_job, register_resumer, say
from app.domain.assets.importer import register_file_asset
from app.media.paths import resolve_key
from app.domain.usage import billable

"""
Generation runner: executes a generation job off-thread. Results always land
as assets + generated_assets rows (plan §18.4) — never as loose temp files.
"""

logger = logging.getLogger(__name__)


class GenerationRunError(GenerationAdapterError, LocalizedError):
    """执行时发现做不了(素材没了、密钥没配……)。带文案 key(`genErr_*`),失败原因经
    `jobs.blame` 记 key + 参数,任务中心按读的人的语言翻。"""


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


#: 远端任务回执在 Job.payload 里的那一栏。见 `_remember_remote_task`。
REMOTE_TASK_FIELD = "remote_task"


def remote_poll_path(job: Job) -> str:
    """这个生成任务已经提交出去的远端任务(轮询路径);还没提交过就是空串。"""
    return str(((job.payload or {}).get(REMOTE_TASK_FIELD) or {}).get("poll_path") or "")


def can_resume(db, job: Job) -> bool:
    """这个任务有没有一个已经提交出去、而且这一家能接着取的远端任务。"""
    poll_path = remote_poll_path(job)
    if not poll_path:
        return False
    generation = db.scalars(select(GenerationJob).where(GenerationJob.job_id == job.id)).first()
    adapter = get_generation_adapter(generation.provider, generation.kind) if generation is not None else None
    return bool(adapter is not None and adapter.supports_resume)


def resume_generation(job_id: str) -> bool:
    """**接着取**一个已经提交过的生成任务,不再提交。能开始取回就返回 True。

    后端重启时由 `jobs.reconcile_orphaned_jobs` 叫到(见文件末尾的 register_resumer):此前
    重启把正在生成的任务一律判成"中断,请重新发起" —— 而远端还在生成、还在扣费,用户照提示
    重来就是再付一次,第一次那条成片永远没人去取。开发时尤其要命:`--reload` 每改一行代码就
    重启一次。
    """
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or not can_resume(db, job):
            return False
        generation = db.scalars(select(GenerationJob).where(GenerationJob.job_id == job_id)).one()
        poll_path = remote_poll_path(job)
        generation_id = generation.id
        say(job, "jobMsg_generationResuming")
        emit_job_event(db, job.id, "job.resumed", {"poll_path": poll_path})
        return dispatch_job(db, job, lambda: _run_generation(generation_id, resume_from=poll_path))


def _run_generation(generation_id: str, *, resume_from: str = "") -> None:
    with SessionLocal() as db:
        generation = db.get(GenerationJob, generation_id)
        if generation is None or not generation.job_id:
            return
        job = db.get(Job, generation.job_id)
        if job is None:
            return

        if not finish_job(db, job, status="running"):
            db.commit()
            return
        db.commit()

        adapter = get_generation_adapter(generation.provider, generation.kind)
        if adapter is None:
            _fail(db, job, GenerationRunError(
                "genErr_adapterUnavailable", provider=generation.provider, kind=generation.kind
            ))
            return

        from app.domain.providers import resolve_connection

        # 这次生成替谁干:job 上记着(见 Job.created_by)—— 用他的钥匙、花他的额度。
        profile = resolve_connection(db, generation.provider, generation.provider_profile_id, user_id=job.created_by)
        if adapter.requires_credentials() and (profile is None or not profile.api_key):
            _fail(db, job, GenerationRunError("genErr_noApiKey", provider=generation.provider))
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
        if not finish_job(db, job, status="running"):
            db.commit()
            return
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
            #: 远端任务一出现就落库(见 contracts.generation.watching_remote_tasks)——从那一刻起
            #: 它在花钱,回执只活在适配器的局部变量里的话,线程一死就再也找不回来。
            with watching_remote_tasks(_remote_task_watch(db, job)):
                if resume_from:
                    result = adapter.resume(resume_from, request, context, workdir)
                elif adapter.supports_progress_callbacks:
                    result = adapter.generate(request, context, workdir, callbacks=_job_callbacks(db, job))
                else:
                    result = adapter.generate(request, context, workdir)
            if not finish_job(db, job, status="running"):
                _record_generation_usage(db, generation, job, request, context, result, started, "succeeded")
                db.commit()
                return
            db.commit()
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
            asset_ids = [one.id for one in assets]
            if not finish_job(db, job, status="succeeded"):
                db.commit()
                return
            generation.result_asset_id = assets[0].id
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
                _fail(db, job, exc)
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
        if not finish_job(db, job, status="running"):
            db.commit()
            return
        job.progress = min(0.95, max(float(job.progress or 0.0), float(fraction)))
        if message:
            say(job, message[:200])
        db.commit()

    def is_cancelled() -> bool:
        db.refresh(job)
        return job.status not in ("queued", "running")

    return GenerationProgressCallbacks(on_progress=on_progress, is_cancelled=is_cancelled)


def _remote_task_watch(db, job: Job) -> RemoteTaskWatch:
    def remember(poll_path: str) -> None:
        job.payload = {**(job.payload or {}), REMOTE_TASK_FIELD: {"poll_path": poll_path}}
        db.commit()
        logger.info("generation job %s: remote task %s", job.id, poll_path)

    def is_cancelled() -> bool:
        db.refresh(job)
        return job.status not in ("queued", "running")

    return RemoteTaskWatch(remember=remember, is_cancelled=is_cancelled)


def _fail(db, job: Job, reason: Exception | str) -> None:
    """任务失败。给的是异常就经 `blame` 记(带 key 的按读的人的语言翻);给的是一句话就是
    第三方的原话(已脱敏),原样记。"""
    fields = blame(reason) if isinstance(reason, Exception) else {"error": reason[:500]}
    if not finish_job(db, job, status="failed", **fields):
        db.commit()
        return
    say(job, "jobMsg_generationFailed")
    emit_job_event(db, job.id, "job.failed", {})
    db.commit()
    logger.warning("generation job %s failed: %s", job.id, fields["error"])


#: 每种角色收什么素材。参考视频收视频,其余收图片 —— 这一条是**校验**,不是描述:
#: 把一段视频当首帧递上去,各家的报错五花八门(有的干脆生成出一片黑),不如在这里拦住。
ROLE_ASSET_KIND = {
    FIRST_FRAME: "image",
    LAST_FRAME: "image",
    REFERENCE_IMAGE: "image",
    REFERENCE_VIDEO: "video",
}

#: 报错里那个词。写死「首帧」的话,尾帧缺文件时用户看到的是「首帧素材文件不存在」。
#: 名字是文案 `genRole_<role>`(和提交前校验用的同一份,见 operations._label)。
#: 这里跑在后台线程里,名字按缺省语言渲染 —— 它是参数,不是 key,落库后不再随读者变。
def _role_label(role: str) -> str:
    key = f"genRole_{role}"
    label = tr(key)
    return role if label == key else label


def _sources_for_generation(db, generation: GenerationJob) -> tuple[SourceAsset, ...]:
    """把请求里记的素材引用解析成本地文件,**保住各自的角色**。"""
    sources: list[SourceAsset] = []
    for entry in generation.request.get("source_assets") or []:
        role = str(entry.get("role") or FIRST_FRAME)
        label = _role_label(role)
        asset = db.get(Asset, str(entry.get("asset_id") or ""))
        if asset is None or asset.workspace_id != generation.workspace_id:
            raise GenerationRunError("genErr_sourceMissing", label=label)
        expected = ROLE_ASSET_KIND.get(role, "image")
        if asset.kind != expected:
            raise GenerationRunError(
                "genErr_sourceMustBeVideo" if expected == "video" else "genErr_sourceMustBeImage", label=label
            )
        if not asset.file_key:
            raise GenerationRunError("genErr_sourceNoLocalFile", label=label)
        path = resolve_key(asset.file_key)
        if not path.is_file():
            raise GenerationRunError("genErr_sourceFileMissing", label=label)
        # 这份素材在公网上的直链(只有"从链接导入的"素材才有)。有直链时,视频/音频角色
        # 优先走直链发出去 —— 见 contracts.generation.SourceAsset:方舟的参考视频只收链接。
        sources.append(
            SourceAsset(
                role=role,
                path=path,
                public_url=direct_media_url((asset.media_info or {}).get("source_url")),
            )
        )
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


#: 重启后这一类任务**接着取**,而不是判失败。登记在总线上(见 jobs.register_resumer),
#: 总线不认识"生成"这件事,只认识"这一类有办法接着干"。
register_resumer("ai_generation", can_resume=can_resume, resume=resume_generation)
