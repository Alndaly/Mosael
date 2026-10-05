from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from app.ai.providers import (
    DRIVING_AUDIO,
    FIRST_CLIP,
    FIRST_FRAME,
    LAST_FRAME,
    MASK,
    REFERENCE_AUDIO,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    SOURCE_VIDEO,
    GenerationRequest,
    GenerationResult,
    GenerationAdapterContext,
    GenerationAdapterError,
    RemoteTaskWatch,
    SourceAsset,
    get_generation_adapter,
    watching_remote_tasks,
)
from app.ai.providers.contracts.generation import (
    GenerationAdapter,
    ReportedUsage,
    direct_media_url,
    metering_from_request,
    reported_on_failure,
    sanitize_adapter_error,
    with_reported,
)
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.core.i18n import LocalizedError, tr
from app.db.models import Asset, GeneratedAsset, GenerationJob, Job, now
from app.domain.providers import models as provider_models
from app.domain.generation.operations import prompt_for_provider
from app.domain.jobs import (
    blame,
    dispatch_job,
    emit_job_event,
    finish_job,
    register_resumer,
    register_settle_listener,
    say,
)
from app.domain.assets.importer import register_file_asset
from app.media.paths import resolve_key
from app.domain.billing.usage import billable, price_usage, usage_mismatches

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
    external 模式下 dispatch 只把 job 标成等待认领,不起线程。

    自己开的会话,自己就是入口:用 unit_of_work 包住,提交之后 dispatch_job 登记的线程才起来。"""
    with unit_of_work() as db:
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
    with unit_of_work() as db:
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

        from app.domain.providers.selection import resolve_connection

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
        result: GenerationResult | None = None
        #: 服务商的终态回包,一到手就由轮询循环 / 同步适配器交到这里(见 RemoteTaskWatch.settled)。
        #: 远端已经生成扣了费、接着下载失败时,失败的那条账照它记,而不是记 0。
        settled: list[dict] = []
        started = time.monotonic()
        try:
            request = GenerationRequest(
                kind=generation.kind,
                model=generation.model,
                prompt=prompt_for_provider(generation.request),
                negative_prompt=str(generation.request.get("negative_prompt", "")),
                parameters=dict(generation.request.get("parameters") or {}),
                sources=_sources_for_generation(db, generation),
            )
            adapter.validate_request(request)
            #: 远端任务一出现就落库(见 contracts.generation.watching_remote_tasks)——从那一刻起
            #: 它在花钱,回执只活在适配器的局部变量里的话,线程一死就再也找不回来。
            with watching_remote_tasks(_remote_task_watch(db, job, settled=settled.append)):
                if resume_from and adapter.supports_progress_callbacks:
                    # 接着取的那一段也要有进度和取消 —— 一段本地长视频重启后可能还要跑一小时。
                    result = adapter.resume(resume_from, request, context, workdir, callbacks=_job_callbacks(db, job))
                elif resume_from:
                    result = adapter.resume(resume_from, request, context, workdir)
                elif adapter.supports_progress_callbacks:
                    result = adapter.generate(request, context, workdir, callbacks=_job_callbacks(db, job))
                else:
                    result = adapter.generate(request, context, workdir)
            if not finish_job(db, job, status="running"):
                _record_generation_usage(db, generation, job, adapter, request, context, result, started, "succeeded")
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
                    #: 生成任务的每一份产出都是 AI 生成的(AI 工作台、画板、智能体、工作流都走这个漏斗)。
                    ai_generated=True,
                )
                for path in result.output_paths
            ]
            if not assets:
                raise GenerationAdapterError("Provider returned no output")
            #: 每份产出实际用的参数(ComfyUI 循环提交时每张一个种子):记在它自己那一行上,也进任务结果。
            used = [dict(one) for one in result.output_parameters[: len(assets)]]
            used += [{}] * (len(assets) - len(used))
            for asset, own in zip(assets, used, strict=True):
                db.add(
                    GeneratedAsset(
                        asset_id=asset.id,
                        provider=generation.provider,
                        model=generation.model,
                        prompt=request.prompt,
                        parameters={**request.parameters, **own},
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
            #: 供应商说了一句(循环里有一次失败、成功了几张)就把它当这一次的最后一句话,没说才是「生成完成」。
            if result.note:
                say(job, result.note)
            else:
                say(job, "jobMsg_generationDone")
            #: 回执里放**一串**。收成单数的话,消费方拿到的永远只是第一张 —— 而这正是
            #: 多出来那几张此前消失的地方。
            job.result = {
                "asset_ids": asset_ids,
                #: 每份用的参数各不一样时(每张一个种子)记一份对照,运行记录里看得到
                **({"outputs": [{"asset_id": asset.id, "parameters": own} for asset, own in zip(assets, used, strict=True)]}
                   if any(used) else {}),
                **({"note": result.note} if result.note else {}),
            }
            _record_generation_usage(
                db, generation, job, adapter, request, context, result, started, "succeeded",
                measured_seconds=_measured_seconds(assets) if generation.kind in ("audio", "video") else None,
            )
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
                _record_generation_usage(db, generation, job, adapter, request, context, result, started, "failed",
                                         settled=settled[-1] if settled else None)
            # 用户取消时 cancel_job 已落终态并写好「已取消」;再 _fail 会把它改写成
            # 泛化的 Generation failed,取消看起来就像出了错。
            if job.status in ("queued", "running"):
                _fail(db, job, exc)
            else:
                db.commit()
        except Exception as exc:  # defensive: worker threads must never die silently
            if request is not None:
                _record_generation_usage(db, generation, job, adapter, request, context, result, started, "failed",
                                         settled=settled[-1] if settled else None)
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


def _remote_task_watch(db, job: Job, *, settled: Callable[[dict], None]) -> RemoteTaskWatch:
    def remember(poll_path: str) -> None:
        job.payload = {**(job.payload or {}), REMOTE_TASK_FIELD: {"poll_path": poll_path}}
        db.commit()
        logger.info("generation job %s: remote task %s", job.id, poll_path)

    def is_cancelled() -> bool:
        db.refresh(job)
        return job.status not in ("queued", "running")

    return RemoteTaskWatch(remember=remember, is_cancelled=is_cancelled, settled=settled)


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


#: 每种角色收什么素材 —— 这一条是**校验**,不是描述:把一段视频当首帧递上去,各家的报错
#: 五花八门(有的干脆生成出一片黑),不如在这里拦住。
#:
#: 此前这张表只写了四个角色,其余一律按「图片」查 —— 于是从素材库挂一段待编辑的视频、一段参考
#: 音频,在这里被判成「必须是图片」。每个角色都要写,漏写的由 `expected_asset_kind` 当场报错。
ROLE_ASSET_KIND = {
    FIRST_FRAME: "image",
    LAST_FRAME: "image",
    REFERENCE_IMAGE: "image",
    REFERENCE_VIDEO: "video",
    REFERENCE_AUDIO: "audio",
    SOURCE_VIDEO: "video",
    DRIVING_AUDIO: "audio",
    FIRST_CLIP: "video",
    MASK: "image",
}

#: 同一个角色在不同的生成种类下收不同的素材。**续写**在视频那边接的是一段视频,在音频那边
#: 接的是一段音频 —— 语义一样(产出以它开头、往下长),介质跟着产出走。
ROLE_ASSET_KIND_BY_GENERATION = {
    ("audio", FIRST_CLIP): "audio",
}


def expected_asset_kind(role: str, generation_kind: str) -> str:
    """这一次生成里,这个角色该挂哪种素材。"""
    return ROLE_ASSET_KIND_BY_GENERATION.get((generation_kind, role)) or ROLE_ASSET_KIND[role]


_ASSET_KIND_ERRORS = {
    "image": "genErr_sourceMustBeImage",
    "video": "genErr_sourceMustBeVideo",
    "audio": "genErr_sourceMustBeAudio",
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
        expected = expected_asset_kind(role, generation.kind)
        if asset.kind != expected:
            raise GenerationRunError(_ASSET_KIND_ERRORS[expected], label=label)
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
                #: 先建主体再引用的模型按它分组(`@资产` 时是资产 id,见 domain/entities/mentions)。
                subject=str(entry.get("subject") or ""),
            )
        )
    return tuple(sources)


def _measured_seconds(assets: list[Asset]) -> float | None:
    """产出的**真实**时长之和(探测出来的,见 assets.importer)。有一份量不出就不报 —— 少算一段
    比按零秒记更糟:按秒计价的规则会把它当成免费。"""
    total = 0.0
    for asset in assets:
        duration = (asset.media_info or {}).get("duration")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            return None
        total += float(duration)
    return round(total, 3)


def _record_generation_usage(
    db,
    generation: GenerationJob,
    job: Job,
    adapter: GenerationAdapter,
    request: GenerationRequest,
    context: GenerationAdapterContext,
    result: GenerationResult | None,
    started: float,
    status: str,
    *,
    measured_seconds: float | None = None,
    settled: dict | None = None,
) -> None:
    """记这一次生成的账。`settled` 是失败时手里最后一份服务商终态回包(适配器没交回结果就失败了)。"""
    # 服务商在回包里报的(实际计费的 token 数、平台回报的扣费)叠在请求侧计量上,以它为准。读法由适配器
    # 说了算(GenerationAdapter.reported_usage),补算老账的迁移对着库里存的回包读的是同一个函数。
    payload = result.raw_usage if result is not None else (settled or {})
    reported = ReportedUsage()
    if payload:
        try:
            reported = adapter.reported_usage(payload)
        except Exception:  # noqa: BLE001 — 记账是旁路:回包读不懂,不该把一次成功的生成判成失败
            logger.warning("读不懂 %s 的回包用量,按请求侧计量记账", generation.provider, exc_info=True)
    if result is None and (reported.units or reported.cost_micros is not None):
        # 适配器没交回结果就失败了,但服务商的终态回包到了手、报了用量或扣费 —— 远端已经生成、扣了费,
        # 是我们这边下载失败。只按服务商报的计:请求了几秒几张不等于扣了多少。
        units, raw = reported_on_failure(metering_from_request(request), reported.units), payload
    else:
        # 什么都没报的失败(请求被当场拒掉、服务商判了失败没扣钱)回包也不记:record_usage 据此记 0。
        units = _with_request_facts(
            with_reported(dict(result.usage if result is not None else {}), reported.units),
            request, result, measured_seconds,
        )
        raw = result.raw_usage if result is not None else {}
    check = _cross_check(db, generation, job, context, units, reported)
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
        call.meter(units, raw=raw)
        if reported.cost_micros is not None:
            call.report_cost(reported.cost_micros, reported.currency)
        if check:
            call.annotate(usage_check=check)
        if status != "succeeded":
            # 这里的失败是**捕获后**记的(runner 自己处理了异常),billable 看不见,得显式说。
            call.mark_failed()


#: 回报的扣费和按价目对回包明细算出来的钱,差多少算对不上:一成,或者不到一分钱的零头不算。
_COST_TOLERANCE = 0.10
_COST_TOLERANCE_MICROS = 100


def _cross_check(
    db, generation: GenerationJob, job: Job, context: GenerationAdapterContext, units: dict, reported: ReportedUsage,
) -> dict | None:
    """服务商回包里现成的用量字段和我们记的账互相印证(不改记账的依据)。

    - 回包说的事实(出了几秒、什么分辨率档)和记下的计量比;
    - 服务商回报了扣费、回包又带着明细(Evolink 出图的 token 数)时,按价目对明细算一遍,和回报的扣费比。
    对不上记一条警告,连同核对的依据一起留在这条账的 raw_usage 里(`usage_check`),事后对账查得到。
    """
    if not reported.observed:
        return None
    check: dict = {"observed": dict(reported.observed)}
    mismatched = usage_mismatches(units, reported.observed)
    if reported.cost_micros is not None:
        basis = {key: value for key, value in units.items() if key != "token_estimate"} | reported.observed
        try:
            priced = price_usage(
                db, workspace_id=job.workspace_id, provider_profile_id=context.connection_id, provider=generation.provider,
                capability=generation.kind, model=generation.model, units=basis, moment=now(),
            )
        except Exception:  # noqa: BLE001 — 核对是旁路,算不出来不该影响记账
            logger.warning("核对 %s %s 的扣费时按价目算不出来", generation.provider, generation.model, exc_info=True)
            priced = None
        if priced is not None and priced.cost_micros is not None:
            check["priced"] = {"micros": priced.cost_micros, "currency": priced.currency}
            gap = abs(priced.cost_micros - reported.cost_micros)
            if priced.currency.upper() == reported.currency.upper() and gap > max(
                _COST_TOLERANCE_MICROS, reported.cost_micros * _COST_TOLERANCE
            ):
                mismatched["cost"] = {"billed": reported.cost_micros, "priced": priced.cost_micros}
    if mismatched:
        check["mismatched"] = mismatched
        logger.warning(
            "%s %s 的回包用量和记账对不上(生成 %s):%s", generation.provider, generation.model, generation.id, mismatched
        )
    return check


def _with_request_facts(
    units: dict, request: GenerationRequest, result: GenerationResult | None, measured_seconds: float | None
) -> dict:
    """补上请求侧的计量(适配器没写的那几格):请求了几张、几秒、什么分辨率。"""
    if "requests" not in units:
        units["requests"] = 1
    if request.kind == "image":
        units.setdefault("images", int(request.parameters.get("num_images", 1)))
        units.setdefault("source_images", len(request.sources))
        if request.parameters.get("size"):
            units.setdefault("size", str(request.parameters["size"]).replace("*", "x"))
    if request.kind == "video":
        units.setdefault("videos", 1)
        # 请求说了时长的按请求记(供应商按所选时长收费);没说的(数字人:成片跟着驱动音频走)按产出的真实时长。
        # 两样都没有就不记 —— 按秒计价的规则把它当「没计上」,比记一个猜的 5 秒诚实。
        if request.parameters.get("duration_seconds") is not None:
            units.setdefault("video_seconds", float(request.parameters["duration_seconds"]))
        elif measured_seconds is not None:
            units.setdefault("video_seconds", measured_seconds)
        units.setdefault("resolution", str(request.parameters.get("resolution", "720p")))
        units.setdefault("aspect_ratio", str(request.parameters.get("aspect_ratio", "")))
        units.setdefault("source_images", len(request.sources))
    if request.kind == "audio":
        # 按条:产出了几份就是几份(一次出两首的那家,两首都在库里)。按秒:供应商回报了计费时长
        # 的以它为准(Adapter 已写进 usage),没报的用探测到的真实时长 —— 请求里的时长只是期望,
        # 多数音乐模型按歌词长短自己定曲长。
        if result is not None:
            # 交回了几首就是几首 —— Adapter 在请求时只知道「这是一次」,不知道对面会交回两首。
            units["audios"] = len(result.output_paths)
        units.setdefault("audios", 1)
        if measured_seconds is not None:
            units.setdefault("audio_seconds", measured_seconds)
    return units

def _asset_name(prompt: str, model: str) -> str:
    summary = prompt.strip().splitlines()[0][:40] if prompt.strip() else "Generation"
    return f"{summary} · {model}"


def record_failure(db, job: Job) -> None:
    """生成任务失败了:把失败原因抄到**生成记录自己**身上(`error` / `error_key` / `error_params`,和任务同形)。

    任务是会被清掉的(任务中心的「清空已结束」,见 jobs.clear_finished_jobs),生成记录不会 —— 它是创作历史,
    `job_id` 在任务删掉时置空。此前失败原因只在任务上,清一次之后 AI 工作台的失败卡只剩一句泛泛的「生成失败」。

    挂在任务**落终态**那一刻(jobs.register_settle_listener),而不是写在 `_fail` 里:让任务失败的不止执行体
    自己 —— 用户取消(cancel_job)、重启时接不回来(reconcile_orphaned_jobs)、外部 worker 租约过期,这几条都不经过
    `_fail`,而它们都经过这一道。存的是 key 加参数,读的时候按读的人的语言翻(GenerationJobOut),和任务同一条规矩。
    """
    if job.kind != "ai_generation" or job.status != "failed":
        return
    for generation in db.scalars(select(GenerationJob).where(GenerationJob.job_id == job.id)):
        generation.error = job.error
        generation.error_key = job.error_key or ""
        generation.error_params = dict(job.error_params or {})


#: 重启后这一类任务**接着取**,而不是判失败。登记在总线上(见 jobs.register_resumer),
#: 总线不认识"生成"这件事,只认识"这一类有办法接着干"。
register_resumer("ai_generation", can_resume=can_resume, resume=resume_generation)
register_settle_listener("generation_failure", record_failure)
