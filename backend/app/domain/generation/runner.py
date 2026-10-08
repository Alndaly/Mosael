from __future__ import annotations

import logging
import shutil
import threading
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
    RemoteTaskSettled,
    RemoteTaskWatch,
    SourceAsset,
    get_generation_adapter,
    watching_remote_tasks,
)
from app.ai.media_transfer import MediaDownloadError
from app.ai.providers.contracts.generation import (
    IMAGE_INPUT_ROLES,
    GenerationAdapter,
    ReportedUsage,
    source_image_count,
    direct_media_url,
    metering_from_request,
    reported_on_failure,
    sanitize_adapter_error,
    with_reported,
)
from sqlalchemy import func, or_, select

from app.core.db import SessionLocal
from app.core.http_retry import sent_but_unanswered
from app.core.unit_of_work import after_commit, unit_of_work
from app.core.i18n import DEFAULT_LOCALE, LocalizedError, t, tr
from app.db.models import Asset, GeneratedAsset, GenerationJob, Job, now
from app.domain.providers import models as provider_models
from app.domain.generation.operations import prompt_for_provider
from app.domain.jobs import (
    CANCELLED,
    CANCELLED_ERROR_KEY,
    RESTART_ERROR_KEY,
    blame,
    dispatch_job,
    emit_job_event,
    finish_job,
    lock_active_job,
    register_resumer,
    register_settle_listener,
    say,
    waiting_on_other_jobs,
    was_cancelled,
)
from app.domain.assets.importer import register_file_asset
from app.media.paths import resolve_key
from app.media.scratch import GENERATION as GENERATION_SCRATCH, scratch_dir
from app.domain.billing.usage import billable, price_usage, superseded_attempt, usage_mismatches

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


#: 「正在调服务商」的标记,在 Job.payload 里。进调用之前写上、走完(成败都记过账)摘掉;进程中途没了的,它还在 ——
#: 重启时据此估一笔账(见 reconcile_unsettled_charges)。此前调到一半重启,任务被判「后端重启中断」、一条用量都没有:
#: 同步接口的那张图、异步提交的那个远端任务,对方多半照样做完、照样扣钱(GEN-6)。
PROVIDER_CALL_FIELD = "provider_call"


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


#: **远端可能已经做完、是我们没拿到结果**的那几种失败(按任务记下的失败原因认):成片下载断了、付费请求发出去没等到回答、等远端
#: 等过了上限、等的时候后端重启了(GEN-1 / 5 / 6)。插件生成另看它说的失败的样子(见 result_may_exist)。
RESULT_MAY_EXIST_KEYS = frozenset({
    "genErr_resultNotCollected",
    "genErr_outcomeUnknown",
    "providerErr_pollTimeout",
    "providerErr_vendorPollTimeout",
    RESTART_ERROR_KEY,
})


def result_may_exist(error_key: str, error_params: dict | None) -> bool:
    """这次失败的**性质**:远端那边可能已经做完(或者还在做)、是我们没拿到结果 —— 再问一次值得;不是这一种的(远端明确报了错、
    当场被拒、还没交出去)再问也只会拿到同一句。

    插件生成(`providerErr_pluginFailed`)按插件说的失败的样子判(`remote`,见 plugin_connections._plugin_failed):`pending` 是交出去了、
    没等到或没拿到;`failed` 是远端明确失败了(ComfyUI 报了执行错误)—— 此前不分这个,ComfyUI 已经报了「KSampler 出错」,失败卡上照样摆
    「重新取回」,点了只会拿到同一个错误。没说的(老记录、插件没说)按「不知道」算,不摆。"""
    if error_key in RESULT_MAY_EXIST_KEYS:
        return True
    return error_key == "providerErr_pluginFailed" and (error_params or {}).get("remote") == "pending"


def retrievable(db, generation: GenerationJob, job: Job | None) -> bool:
    """这条失败了的生成能不能「重新取回」:远端任务交出去了(有回执)、这一家能接着取、没有产出、**不是被停下的**,而且失败的
    性质是「远端可能做完了、我们没拿到」(见 result_may_exist)。

    停下 = 用户说了「这一份我不要了」(ADR 0019 Consequences);跑挂了的才值得再问一次。任务被任务中心清掉之后回执跟着没了,
    那时也取不回。
    """
    if job is None or job.status != "failed" or generation.result_asset_id:
        return False
    if not result_may_exist(str(job.error_key or ""), dict(job.error_params or {})):
        return False
    return can_resume(db, job)


def start_retrieval_thread(generation_id: str) -> None:
    """「重新取回」:派发一次**接着取**的运行 —— 不提交,只问远端要结果、下载、登记。和重启后接着取同一条路
    (`_run_generation(resume_from=…)`)。调用方先建好新任务、提交,再调这里。"""
    with unit_of_work() as db:
        generation = db.get(GenerationJob, generation_id)
        job = db.get(Job, generation.job_id) if generation is not None and generation.job_id else None
        if job is None:
            return
        poll_path = remote_poll_path(job)
        dispatch_job(db, job, lambda: _run_generation(generation_id, resume_from=poll_path))


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

        profile, context = _connection(db, generation, job)
        if adapter.requires_credentials() and (profile is None or not profile.api_key):
            _fail(db, job, GenerationRunError("genErr_noApiKey", provider=generation.provider))
            return
        if not finish_job(db, job, status="running"):
            db.commit()
            return
        #: 接着取(重启后、或者「重新取回」)的那一句留着:「后端重启过,正在接着取回」「正在重新取回,不重新提交」说的正是
        #: 用户这时最想知道的 —— 此前一进来就换成「生成中」,那句话一闪就没了。
        if not resume_from:
            say(job, "jobMsg_generationRunning")
        emit_job_event(db, job.id, "job.running", {"provider": generation.provider})
        #: 从这里起在调服务商(见 PROVIDER_CALL_FIELD):进程这时没了,重启时按「调到一半」估一笔账。走完(成败都记过账)由
        #: 下面的 finally 摘掉 —— 进程被杀时 finally 不执行,摘不掉的正是要估的那些。
        job.payload = {**(job.payload or {}), PROVIDER_CALL_FIELD: True}
        db.commit()
        job_id = job.id
        logger.info(
            "generation job %s: provider=%s model=%s kind=%s",
            job.id,
            generation.provider,
            generation.model,
            generation.kind,
        )

        #: 在数据目录里,不在系统临时目录:进程中途没了,下次启动清掉(见 media/scratch)。
        workdir = scratch_dir(GENERATION_SCRATCH)
        request: GenerationRequest | None = None
        result: GenerationResult | None = None
        #: 服务商的终态回包,一到手就由轮询循环 / 同步适配器交到这里(见 RemoteTaskWatch.settled)。
        #: 远端已经生成扣了费、接着下载失败时,失败的那条账照它记,而不是记 0。
        settled: list[dict] = []
        started = time.monotonic()
        #: 接着取(重启后、或者「重新取回」)时送进去几张图:素材不再解析(见下),计量照提交时那一份数。
        source_images = _stored_source_image_count(generation) if resume_from else None
        try:
            #: **接着取不碰输入素材。**素材在提交那一刻就交出去了,接着取只需要轮询路径和模型;此前这里照样重新解析、
            #: 重新校验 —— 用户提交之后删了首帧、或者升级后校验变严,接着取就在问远端之前失败,付过钱的成片没人去取,
            #: 账也一笔不记(ADR 0019 修订)。
            request = _request_for(generation, job, sources=() if resume_from else _resolved_sources(generation))
            if not resume_from:
                adapter.validate_request(request)
            #: 远端任务一出现就落库(见 contracts.generation.watching_remote_tasks)——从那一刻起
            #: 它在花钱,回执只活在适配器的局部变量里的话,线程一死就再也找不回来。
            side_calls = _side_call_recorder(generation, job, context)
            #: 走到这里,这个长会话上没有开着的事务(上面最后一步是提交;素材在短会话里解析,见 _resolved_sources)。
            #: 适配器一跑就是几分钟到几小时,等待期间要读写任务行的(取消、回执、断线提示、顺带的计费)各开各的短会话或
            #: 当场提交,见 _remote_task_watch —— 开着事务等,连接池里那一条就一直被攥着,十五个同时在等,整个后端就拿不到连接。
            with watching_remote_tasks(_remote_task_watch(db, job, settled=settled.append, side_call=side_calls)):
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
                _record_generation_usage(db, generation, job, adapter, request, context, result, started, "succeeded",
                                         source_images=source_images)
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
                    #: 下回来的落在这次的暂存目录里,是自己的:搬进去,不再复制一份。适配器交回的若是别处的文件(本机
                    #: 引擎自己的输出目录),不搬。
                    move=path.is_relative_to(workdir),
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
            measured = _measured_seconds(assets) if generation.kind in ("audio", "video") else None
            if not finish_job(db, job, status="succeeded"):
                #: 登记素材那几秒里被取消了(进度停在 95% 时点了停止、工作流连带取消):成片已经进了素材库(每份登记各自
                #: 提交),服务商也早扣了钱。此前这里直接提交返回,一笔账都不记 —— 钱扣了、成片在库、花费里没有。
                _record_generation_usage(
                    db, generation, job, adapter, request, context, result, started, "succeeded",
                    measured_seconds=measured, source_images=source_images, annotations={"cancelled_locally": True},
                )
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
                #: 每份用的参数各不一样时(每张一个种子)记一份对照,运行记录里看得到。**不叫 `outputs`**:那个键是
                #: 「这个任务交回了什么」(画板 / 任务详情读它,见 boards.outputs.outputs_of),占了它,这一次的素材
                #: 在画板上就成了「没有交回任何产出」。
                **({"output_parameters": [{"asset_id": asset.id, "parameters": own}
                                          for asset, own in zip(assets, used, strict=True)]}
                   if any(used) else {}),
                **({"note": result.note} if result.note else {}),
            }
            _record_generation_usage(
                db, generation, job, adapter, request, context, result, started, "succeeded",
                measured_seconds=measured, source_images=source_images,
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
        except (GenerationAdapterError, MediaDownloadError) as exc:
            #: 下载成片断了(接了几次都没接上、链接过期):服务商早就做完了。不是「供应商请求失败」,也不该让人以为要重新生成。
            not_collected = isinstance(exc, MediaDownloadError)
            #: 付费请求发出去了、没等到回答(读超时、网关 5xx):对方多半照样在做、照样扣钱。不是「当场被拒」。
            unknown = not not_collected and sent_but_unanswered(exc)
            if request is not None:
                _record_failed_or_cancelled(db, generation, job, adapter, request, context, result, workdir, started,
                                            settled, result_not_collected=not_collected, outcome_unknown=unknown)
            # 用户取消时 cancel_job 已落终态并写好「已取消」;再 _fail 会把它改写成
            # 泛化的 Generation failed,取消看起来就像出了错。
            if job.status in ("queued", "running"):
                if not_collected:
                    _fail(db, job, _result_not_collected(db, job, exc))
                elif unknown:
                    _fail(db, job, GenerationRunError("genErr_outcomeUnknown", detail=str(exc)))
                else:
                    _fail(db, job, exc)
            else:
                db.commit()
        except Exception as exc:  # defensive: worker threads must never die silently
            if request is not None:
                _record_failed_or_cancelled(db, generation, job, adapter, request, context, result, workdir, started,
                                            settled)
            _fail(db, job, sanitize_adapter_error(str(exc), context.api_key))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            _forget_provider_call(job_id)


def _record_failed_or_cancelled(
    db,
    generation: GenerationJob,
    job: Job,
    adapter: GenerationAdapter,
    request: GenerationRequest,
    context: GenerationAdapterContext,
    result: GenerationResult | None,
    workdir: Path,
    started: float,
    settled: list[dict],
    *,
    result_not_collected: bool = False,
    outcome_unknown: bool = False,
) -> None:
    """这次生成失败了,或者被取消了。适配器已经交回了结果(失败在我们这边,登记素材出错之类)的照结果记;没交回、
    而任务是被取消的,远端任务已经交出去的先把它了结(见 _settle_after_cancel)再记账。

    `outcome_unknown`:付费请求发出去了、没等到回答(读超时、网关 5xx,见 core/http_retry.sent_but_unanswered)。对方多半照样
    在做、照样扣钱 —— 按请求侧计量估一笔,写明「结局不明」,不记成「未扣费」(GEN-6)。

    **没被取消、却在远端任务交出去之后失败的**(等远端时出了确定性的错、六小时上限,或者 `result_not_collected`:服务商做完了、
    成片没下载回来),远端多半照样扣钱:有服务商的终态回包就照它记;没有回包、或者回包里没报用量,按请求侧计量估一笔并写明
    为什么 —— 不再记成「未扣费」(ADR 0019 修订)。之后「重新取回」拿到了成片,成功那一条接替这一条(见 billing.superseded_attempt)。"""
    if result is not None:
        _record_generation_usage(db, generation, job, adapter, request, context, result, started, "failed")
        return
    finished, outcome, poll_path = _settle_after_cancel(job.id, adapter, request, context, workdir, settled)
    _record_settled(db, generation, job, adapter, request, context, started, settled, finished, outcome, poll_path,
                    result_not_collected=result_not_collected, outcome_unknown=outcome_unknown)


def _record_settled(
    db,
    generation: GenerationJob,
    job: Job,
    adapter: GenerationAdapter,
    request: GenerationRequest,
    context: GenerationAdapterContext,
    started: float,
    settled: list[dict],
    finished: GenerationResult | None,
    outcome: str,
    poll_path: str,
    *,
    result_not_collected: bool = False,
    outcome_unknown: bool = False,
) -> None:
    """`_settle_after_cancel` 了结之后记这一笔(不提交)。拆出来是为了重启后接着跟的那条路(_follow_after_restart):
    跟的那一段不拿着会话,记账时才开一个。"""
    if outcome == "cancelled_remotely":
        emit_job_event(db, job.id, "job.remote_cancelled", {"poll_path": poll_path})
    if outcome in ("followed", "followed_to_done"):
        #: 跟完了:摘掉「正在跟」—— 在这一笔账提交**之后**(提交前进程没了,下次启动再跟一遍,账按幂等键只记一笔)。
        job_id = job.id
        after_commit(db, lambda: _forget_following(job_id))
    if finished is not None or outcome == "followed_to_done":
        #: 我们取消了、服务商照样做完:按它回包里实际计费的量记这一笔(成片没留,账照记)。跟到终态时成片不下
        #: (followed_to_done),回包在 settled 里。
        _record_generation_usage(db, generation, job, adapter, request, context, finished, started, "succeeded",
                                 settled=settled[-1] if finished is None and settled else None,
                                 annotations={"cancelled_locally": True})
        return
    annotations: dict | None = None
    if outcome == "unsettled" or (outcome == "not_cancelled" and poll_path and not settled):
        #: 远端任务交出去了、却没有了结(撤不掉也接不着取;或者没取消、等它时出了确定性的错):那一次多半照样扣钱,按请求侧
        #: 计量估一笔,写明远端任务没了结 —— 不再记成「没扣费」。
        annotations = {"unsettled_remote_task": poll_path}
    elif result_not_collected:
        #: 服务商报了做完,是我们没把成片拉回来:它说了扣多少就照它记;没说,按请求侧计量估 —— 做完了的不会是免费的。
        annotations = {"result_not_collected": poll_path or True}
    elif outcome_unknown and outcome == "not_cancelled":
        #: 请求送到了、没等到回答:不知道对方做没做,多半在做、会扣钱。按请求侧计量估一笔,写明结局不明。
        annotations = {"outcome_unknown": poll_path or True}
    _record_generation_usage(
        db, generation, job, adapter, request, context, None, started, "failed",
        settled=settled[-1] if settled else None, annotations=annotations,
    )


def _settle_after_cancel(
    job_id: str,
    adapter: GenerationAdapter,
    request: GenerationRequest,
    context: GenerationAdapterContext,
    workdir: Path,
    settled: list[dict],
) -> tuple[GenerationResult | None, str, str]:
    """任务被取消(用户点的,或者工作流里别的节点失败、把它连带取消)时,远端任务已经交出去了的:**它不会因为我们不等了
    就不扣钱。** 付费实测:配音失败把同一拍正在生成的视频取消掉,账上记 ¥0「没扣费」,方舟照样把那段视频做完、扣了 ¥1.87。

    先请服务商撤掉(见 GenerationAdapter.cancel_remote;方舟排队中的撤得掉,撤掉了才是真的不扣钱)。撤不掉的,接着把它
    等到终态 —— 交回远端做完的结果,按回包里实际计费的量记账;服务商自己判了失败的,终态回包落在 `settled` 里,照旧按它记。
    这家撤不掉也接不着取的,结局是 "unsettled"。

    返回 (远端做完交回的结果或 None, 结局, 回执):结局是 "not_cancelled" / "no_remote_task" / "cancelled_remotely" /
    "followed"(跟到了终态:交回了结果,或者服务商判了失败)/ "followed_to_done"(跟到远端做完,成片没下,回包在
    `settled` 里)/ "unsettled",回执是远端任务的轮询路径(没交出去是空串)。

    **不碰调用方的会话。**任务行用短会话读、标记用短会话写:跟到终态可能还要等几分钟到几小时,在长会话上读写会开一个
    事务、一直攥着连接池里的一条连接(见 _remote_task_watch)。撤掉了要发的那条事件由 `_record_settled` 发。
    """
    from app.core import abort

    cancelled, poll_path = _job_state(job_id)
    if not cancelled:
        return None, "not_cancelled", poll_path
    if not poll_path or settled:
        #: 没交出去(取消在提交之前),或者终态回包已经到手(那份回包说了扣没扣) —— 都不用再问服务商。
        return None, "no_remote_task", poll_path
    #: 取消掐掉了这件活名下的出站请求、也不许再发(core/abort);撤销和接着等是取消之后**该做的事**,换一个新的作用域发。
    with abort.scope(abort.AbortScope()):
        try:
            if adapter.cancel_remote(poll_path, request, context):
                logger.info("generation job %s: remote task %s cancelled at the provider", job_id, poll_path)
                return None, "cancelled_remotely", poll_path
        except Exception:  # noqa: BLE001 — 撤销是尽力而为;撤不成就照「撤不掉」接着往下走
            logger.warning("generation job %s: cancelling remote task %s failed", job_id, poll_path, exc_info=True)
        if not adapter.supports_resume:
            return None, "unsettled", poll_path
        logger.info("generation job %s: cancelled locally; following remote task %s to settle its charge", job_id, poll_path)
        #: 跟到一半进程没了,重启时接着跟(见 reconcile_unsettled_charges);记完账由 _record_settled 摘掉。
        _mark_following(job_id)
        #: 只等终态、不要成片(collect=False):成片拉回来也是马上删掉 —— 此前已取消的视频照样整份下载几分钟到几小时。
        follow = RemoteTaskWatch(remember=lambda _path: None, is_cancelled=lambda: False, settled=settled.append,
                                 collect=False)
        try:
            #: 任务已经停了,剩下的只是等服务商给个终态好记账:这段不占任务名额(和等子任务同一个机制,见 JobRunner.parked)。
            with watching_remote_tasks(follow), waiting_on_other_jobs():
                return adapter.resume(poll_path, request, context, workdir), "followed", poll_path
        except RemoteTaskSettled:
            return None, "followed_to_done", poll_path
        except Exception:  # noqa: BLE001 — 服务商判了失败(回包在 settled 里)或者取不回来:照手里有的记
            logger.info("generation job %s: remote task %s ended without a result", job_id, poll_path, exc_info=True)
            return None, "followed", poll_path


def _connection(db, generation: GenerationJob, job: Job):
    """这次生成用哪条连接、交给适配器的连接上下文。返回 (连接或 None, 上下文)。"""
    from app.domain.providers.selection import resolve_connection

    # 这次生成替谁干:job 上记着(见 Job.created_by)—— 用他的钥匙、花他的额度。
    profile = resolve_connection(db, generation.provider, generation.provider_profile_id, user_id=job.created_by)
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
    return profile, context


def _request_for(generation: GenerationJob, job: Job, *, sources: tuple[SourceAsset, ...]) -> GenerationRequest:
    return GenerationRequest(
        kind=generation.kind,
        model=generation.model,
        prompt=prompt_for_provider(generation.request),
        negative_prompt=str(generation.request.get("negative_prompt", "")),
        parameters=dict(generation.request.get("parameters") or {}),
        sources=sources,
        #: 工作台跑画布上那张图(ADR 0038 §6):图在任务载荷里,不在生成参数里
        graph=_workbench_graph(job),
    )


def _forget_provider_call(job_id: str) -> None:
    """摘掉「正在调服务商」的标记(见 PROVIDER_CALL_FIELD)。短会话:运行器的长会话这时可能处在任何状态。"""
    with unit_of_work() as fresh:
        row = fresh.get(Job, job_id)
        if row is not None and PROVIDER_CALL_FIELD in (row.payload or {}):
            row.payload = {key: value for key, value in row.payload.items() if key != PROVIDER_CALL_FIELD}


def _mark_following(job_id: str) -> None:
    """记下「停下之后正在替记账跟远端任务」,当场落库(短会话)—— 跟到一半进程没了,重启时接着跟(见 reconcile_unsettled_charges)。"""
    _set_following(job_id, True)


def _forget_following(job_id: str) -> None:
    """跟完、账记上之后摘掉「正在跟」。"""
    _set_following(job_id, False)


def _set_following(job_id: str, following: bool) -> None:
    with unit_of_work() as fresh:
        row = fresh.get(Job, job_id)
        if row is None:
            return
        remote = {key: value for key, value in ((row.payload or {}).get(REMOTE_TASK_FIELD) or {}).items()
                  if key != "following"}
        if following:
            remote["following"] = True
        row.payload = {**(row.payload or {}), REMOTE_TASK_FIELD: remote}


def reconcile_unsettled_charges(db) -> int:
    """重启前没来得及记的那几笔生成账。两种:

    - **停下之后正在替记账跟远端任务的**(`remote_task.following`):接着跟 —— 起一条线程,不占任务名额,只等终态、不下成片;
    - **调服务商调到一半进程没了的**(`provider_call` 还在,任务已被判「后端重启中断」;能接着取的那些已经被接走、不在其中):
      按请求侧计量估一笔,写明 `interrupted_by_restart`(交出去了远端任务、却接不着取的,另写 `unsettled_remote_task`)。

    已经有账的不再记(同一次生成的账按幂等键只有一笔)。返回处理了几条。排在 jobs 的收尾之后(见 domain/restart):要看的正是
    它刚判了「后端重启中断」的那些。**不提交、不当场起线程**:重启收尾是一次用例(domain/restart.settle_previous_run),
    接着跟的线程登记成提交之后再起。
    """
    from app.db.models import ProviderUsageEvent
    from app.domain.jobs import RESTART_ERROR_KEY

    #: 上一步(jobs 的收尾)只改了对象、没提交;这个会话不自动 flush,不先 flush 的话查询看不到它刚判的失败。
    db.flush()
    marked = func.json_extract(Job.payload, f"$.{PROVIDER_CALL_FIELD}")
    following = func.json_extract(Job.payload, f"$.{REMOTE_TASK_FIELD}.following")
    #: 只取带着这两个标记之一的那几行 —— 不把全部失败的生成读成对象(CONVENTIONS「批量维护不把行读成 ORM 对象」)。
    rows = db.scalars(select(Job).where(
        Job.kind == "ai_generation", Job.status.in_(("failed", CANCELLED)), or_(marked.is_not(None), following.is_not(None)),
    )).all()
    handled = 0
    followers: list[str] = []
    for job in rows:
        payload = job.payload or {}
        remote = payload.get(REMOTE_TASK_FIELD) or {}
        if remote.get("following") and was_cancelled(job):
            followers.append(job.id)
            handled += 1
            continue
        if not payload.get(PROVIDER_CALL_FIELD) or job.error_key != RESTART_ERROR_KEY:
            continue
        generation = db.scalars(select(GenerationJob).where(GenerationJob.job_id == job.id)).first()
        job.payload = {key: value for key, value in payload.items() if key != PROVIDER_CALL_FIELD}
        if generation is None:
            continue
        charged = db.scalar(select(ProviderUsageEvent.id).where(
            ProviderUsageEvent.source_type == "generation_job", ProviderUsageEvent.source_id == generation.id,
        ).limit(1))
        if charged is None:
            annotations: dict = {"interrupted_by_restart": True}
            if remote.get("poll_path"):
                annotations["unsettled_remote_task"] = remote["poll_path"]
            try:
                # 一条估不出来(连接删了、价目读不懂)不能让后端起不来,也不能拖着别的几条一起回滚。
                with db.begin_nested():
                    _, context = _connection(db, generation, job)
                    _record_generation_usage(
                        db, generation, job, get_generation_adapter(generation.provider, generation.kind),
                        _request_for(generation, job, sources=()), context, None, time.monotonic(), "failed",
                        annotations=annotations, source_images=_stored_source_image_count(generation),
                    )
            except Exception:  # noqa: BLE001 — 见上
                logger.exception("generation %s: could not record the charge of a call cut off by the restart", generation.id)
        handled += 1
    if followers:
        after_commit(db, lambda: _start_followers(followers))
    return handled


def _start_followers(job_ids: list[str]) -> None:
    for job_id in job_ids:
        threading.Thread(target=_follow_after_restart, args=(job_id,), daemon=True, name="generation-follow").start()


def _follow_after_restart(job_id: str) -> None:
    """重启前正在替记账跟的那个远端任务:接着跟到终态,记账。和取消那一刻走同一条路(_settle_after_cancel → _record_settled)。

    跟的那一段**不拿着会话**:读完要用的东西就把会话关掉,记账时再开一个(见 _job_state 说的连接池)。"""
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            generation = db.scalars(select(GenerationJob).where(GenerationJob.job_id == job_id)).first()
            adapter = get_generation_adapter(generation.provider, generation.kind) if generation is not None else None
            if job is None or generation is None or adapter is None:
                return
            generation_id = generation.id
            _, context = _connection(db, generation, job)
            request = _request_for(generation, job, sources=())
        settled: list[dict] = []
        started = time.monotonic()
        workdir = scratch_dir(GENERATION_SCRATCH)
        try:
            finished, outcome, poll_path = _settle_after_cancel(job_id, adapter, request, context, workdir, settled)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        with unit_of_work() as db:
            job, generation = db.get(Job, job_id), db.get(GenerationJob, generation_id)
            if job is not None and generation is not None:
                _record_settled(db, generation, job, adapter, request, context, started, settled, finished, outcome,
                                poll_path)
    except Exception:  # noqa: BLE001 — 后台线程不能无声地死;没跟完的标记还在,下次启动再跟
        logger.exception("generation job %s: following its remote task after a restart failed", job_id)


def _job_state(job_id: str) -> tuple[bool, str]:
    """任务行此刻的样子 —— (是不是被取消了, 远端回执) —— **用一个短会话读**,读完就把连接还回去。

    等远端的那一段(轮询、跟到终态)每隔几秒就要问一次「被取消了吗」。此前问法是 `db.refresh(job)`:在运行器那个长会话上开
    一个读事务、之后再没提交,整个等待期间(几分钟到六小时)连接池里那一条都被它攥着 —— 池子 5+10 条,十五个视频同时在等,
    整个后端的请求都拿不到连接(见 tests/test_waiting_generations_hold_no_connection.py)。
    """
    with SessionLocal() as fresh:
        row = fresh.get(Job, job_id)
        if row is None:
            return True, ""
        return was_cancelled(row), remote_poll_path(row)


def _still_wanted(job_id: str) -> bool:
    """任务还在排队 / 在跑(没被取消、没落别的终态)。短会话读,理由见 `_job_state`。"""
    with SessionLocal() as fresh:
        status = fresh.scalar(select(Job.status).where(Job.id == job_id))
    return status in ("queued", "running")


def _workbench_graph(job: Job) -> dict | None:
    """工作台交来的那张图(见 operations.WORKBENCH_GRAPH);普通的生成没有。"""
    from app.domain.generation.operations import WORKBENCH_GRAPH

    graph = (job.payload or {}).get(WORKBENCH_GRAPH)
    return graph if isinstance(graph, dict) else None


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
        #: 短会话读,不 refresh 这个长会话(见 _job_state:那样整个等待期都攥着一条连接)。
        return not _still_wanted(job.id)

    return GenerationProgressCallbacks(on_progress=on_progress, is_cancelled=is_cancelled)


def _side_call_recorder(generation: GenerationJob, job: Job, context: GenerationAdapterContext):
    """适配器为这次生成顺带调的那几个按次计费的模型(说话照片之前的人像预检,见 contracts.generation.report_side_call),
    **一调就记一笔**,和这次生成成不成无关 —— 预检不通过也扣钱,那时生成那一条是「失败、没扣费」。

    在自己的一次用例里记、当场落库:这是在适配器跑着的时候记的,记在运行器的长会话上的话,这个写事务(和 SQLite 的
    写锁)要一直挂到适配器返回。"""
    seen: dict[str, int] = {}
    facts = {
        "capability": generation.kind,
        "workspace_id": job.workspace_id,
        "provider_profile_id": context.connection_id,
        "provider": generation.provider,
        "source_id": generation.id,
        "job_id": job.id,
    }
    #: 替谁花的钱:发起这次生成的人(定时任务跑的是任务主人,ADR 0050 D30)。
    payer = job.created_by

    def record(model: str, units: dict, raw: dict) -> None:
        seen[model] = seen.get(model, 0) + 1
        with unit_of_work() as fresh, billable(
            fresh,
            user_id=payer,
            operation="generation_side_call",
            model=model,
            source_type="generation_job",
            idempotency_key=f"generation:{facts['source_id']}:side:{model}:{seen[model]}",
            **facts,
        ) as call:
            call.meter(units, raw=raw)

    return record


def _remote_task_watch(db, job: Job, *, settled: Callable[[dict], None],
                       side_call: Callable[[str, dict, dict], None]) -> RemoteTaskWatch:
    """等远端的那一段要碰任务行的几件事。**哪一件都不能让运行器的长会话开着事务等**:回执当场提交;「被取消了吗」和
    「连接断了」各开一个短会话,用完就还 —— 否则整个等待期(几分钟到六小时)都攥着连接池里的一条连接(见 _job_state)。"""
    job_id = job.id

    def remember(poll_path: str) -> None:
        job.payload = {**(job.payload or {}), REMOTE_TASK_FIELD: {"poll_path": poll_path}}
        db.commit()
        logger.info("generation job %s: remote task %s", job_id, poll_path)

    def is_cancelled() -> bool:
        return not _still_wanted(job_id)

    def interrupted(failures: int) -> None:
        #: 连不上时写一句「正在第 n 次重新连接」,接上了换回「生成中」—— 不然用户只看见进度停住,以为卡死了。
        with unit_of_work() as fresh:
            row = fresh.get(Job, job_id)
            if row is None or not lock_active_job(fresh, row):
                return
            if failures:
                say(row, "jobMsg_generationReconnecting", attempt=failures)
            else:
                say(row, "jobMsg_generationRunning")
        if failures:
            logger.info("generation job %s: provider unreachable while waiting (attempt %d), retrying", job_id, failures)

    return RemoteTaskWatch(remember=remember, is_cancelled=is_cancelled, settled=settled, side_call=side_call,
                           interrupted=interrupted)


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


def _result_not_collected(db, job: Job, exc: MediaDownloadError) -> GenerationRunError:
    """成片没拉回来时给人看的那句话:服务商做完了、多半扣了钱;远端任务还能再问的说去点「重新取回」,问不了的说只能重来。"""
    detail = str(exc.params.get("detail") or "")
    if can_resume(db, job):
        return GenerationRunError("genErr_resultNotCollected", detail=detail)
    return GenerationRunError("genErr_resultNotCollectedNoReceipt", detail=detail)


def _stored_source_image_count(generation: GenerationJob) -> int:
    """提交时交进去了几张图 —— 照生成记录里存的素材引用数,不去解析文件(接着取时素材可能已经删了,见 _run_generation)。
    和 `contracts.generation.source_image_count` 数的是同一样东西。"""
    return sum(
        1 for entry in generation.request.get("source_assets") or []
        if str(entry.get("role") or FIRST_FRAME) in IMAGE_INPUT_ROLES
    )


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


def _resolved_sources(generation: GenerationJob) -> tuple[SourceAsset, ...]:
    """`_sources_for_generation`,在一个**短会话**里查素材:运行器的长会话接下来要拿着去等适配器(几分钟到几小时),
    在它上面查库就开了一个读事务,整个等待期都攥着连接池里的一条连接(见 _job_state)。交回的是路径和角色,不是库里的行。"""
    with SessionLocal() as fresh:
        return _sources_for_generation(fresh, generation)


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
    annotations: dict | None = None,
    source_images: int | None = None,
) -> None:
    """记这一次生成的账。`settled` 是失败时手里最后一份服务商终态回包(适配器没交回结果就失败了)。

    `annotations` 记进 raw_usage 的注解(见 BillableCall.annotate)。失败而服务商什么都没回的一条只有在**没有任何
    凭据**时才记 0(record_usage);远端任务交出去了却没了结(`unsettled_remote_task`)本身就是凭据 —— 它多半在扣钱。

    `source_images`:接着取时请求里没有素材(见 _run_generation),交进去几张图按提交时那一份数记。

    **成功的一条接替同一次生成先前记下的失败那一条**(「重新取回」拿到了成片,见 billing.superseded_attempt):那是同一次服务商
    调用,不是又花了一次钱 —— 两条都留着,这次生成的花费会被加两遍。"""
    supersedes = f"generation:{generation.id}:failed" if status == "succeeded" else None
    replaced = superseded_attempt(db, supersedes) if supersedes else None
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
        if source_images is not None and request.kind in ("image", "video"):
            units["source_images"] = source_images
        raw = result.raw_usage if result is not None else {}
    check = _cross_check(db, generation, job, context, units, reported)
    with billable(
        db,
        user_id=job.created_by,
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
        supersedes=supersedes if replaced is not None else None,
    ) as call:
        call.meter(units, raw=raw)
        if reported.cost_micros is not None:
            call.report_cost(reported.cost_micros, reported.currency)
        if check:
            call.annotate(usage_check=check)
        if annotations:
            call.annotate(**annotations)
        if replaced is not None:
            call.annotate(replaces_failed_attempt=replaced)
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
        units.setdefault("source_images", source_image_count(request))
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
        #: 分辨率只记请求说了的(见 contracts.generation.metering_from_request),不猜 720p。
        if str(request.parameters.get("resolution") or "").strip():
            units.setdefault("resolution", str(request.parameters["resolution"]))
        units.setdefault("aspect_ratio", str(request.parameters.get("aspect_ratio", "")))
        units.setdefault("source_images", source_image_count(request))
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

    任务行可能已经不在了(老版本的「清空已结束」真删过;保留清理不删生成记录指着的,见 jobs.expired_job_trees),生成记录
    一直在 —— 它是创作历史,`job_id` 在任务删掉时置空。此前失败原因只在任务上,清一次之后 AI 工作台的失败卡只剩一句泛泛的
    「生成失败」。

    挂在任务**落终态**那一刻(jobs.register_settle_listener),而不是写在 `_fail` 里:让任务失败的不止执行体
    自己 —— 用户取消(cancel_job)、重启时接不回来(reconcile_orphaned_jobs)、外部 worker 租约过期,这几条都不经过
    `_fail`,而它们都经过这一道。存的是 key 加参数,读的时候按读的人的语言翻(GenerationJobOut),和任务同一条规矩。

    **不看任务种类,看有没有记录挂着它**:创作页的语音、播客记录挂的是 `tts` / `podcast` 任务(ADR 0055 §5)。
    """
    if job.status == CANCELLED:
        #: 停下的任务没有失败原因(ADR 0049);记录上照旧抄下「已停止」的记法 —— 卡片据此写「已停止」,不摆失败卡
        #: (见 GenerationJobOut.stopped)。记录活得比任务久,它得自己记得。
        error, error_key, error_params = t(CANCELLED_ERROR_KEY, DEFAULT_LOCALE), CANCELLED_ERROR_KEY, {}
    elif job.status == "failed":
        error, error_key, error_params = job.error, job.error_key or "", dict(job.error_params or {})
    else:
        return
    for generation in db.scalars(select(GenerationJob).where(GenerationJob.job_id == job.id)):
        generation.error, generation.error_key, generation.error_params = error, error_key, error_params


#: 重启后这一类任务**接着取**,而不是判失败。登记在总线上(见 jobs.register_resumer),
#: 总线不认识"生成"这件事,只认识"这一类有办法接着干"。
register_resumer("ai_generation", can_resume=can_resume, resume=resume_generation)
register_settle_listener("generation_failure", record_failure)
