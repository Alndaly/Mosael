"""画板上的「剪一段」:把一段视频/音频截出起止,产出一份新素材。

**为什么不建时间线。** 这个应用真正的剪辑台是序列(sequence),而序列必须挂在项目下 ——
为画板上的一次「掐头去尾」凭空造一个项目,会往用户的项目列表里塞进一堆他没建过的东西。
画板上的剪辑是**探索期的动作**:先截出想要的那几秒,拼片子是后面在编辑器里的事。

所以这里只做一件自足的事:调一次 ffmpeg,把结果登记成新素材。原素材不动 —— 画板上的每一步
都该是可回头的,就地改会让上一版消失。

任务化(而不是同步返回)是因为长素材截取要几十秒:同步的话请求会挂在那儿,而用户已经在看画布了。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.child_process import run_logged
from app.core.i18n import LocalizedError
from app.core.config import settings
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import TRIM, derived
from app.domain.jobs import create_job, dispatch_job, emit_job_event, ensure_wanted, finish_job, say, start_job
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)


class TrimError(LocalizedError, ValueError):
    pass


def start_trim(
    db: Session,
    *,
    asset: Asset,
    start: float,
    end: float,
    mute: bool = False,
    created_by: str | None,
) -> Job:
    """起一个截取任务。范围在这里就校验 —— 让 ffmpeg 去发现「end 比 start 小」的话,
    用户拿到的是一句英文报错。"""
    if asset.kind not in ("video", "audio"):
        raise TrimError("trimErr_unsupportedKind")
    if not asset.file_key:
        raise TrimError("trimErr_noLocalFile")
    if end <= start:
        raise TrimError("trimErr_endBeforeStart")
    if start < 0:
        raise TrimError("trimErr_negativeStart")
    #: 「去掉声音」只对有画面的有意义:音频本身就是那段声音,`-an` 之后什么都不剩 —— ffmpeg
    #: 交出一个空文件,任务几秒后才报错。
    if mute and asset.kind != "video":
        raise TrimError("trimErr_muteNeedsVideo")

    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="trim",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name},
        message="jobMsg_trimQueued",
    )
    # 经总线派发(dispatch_job 先提交再起线程,线程读得到这一行)。此前这里是一句裸的线程创建 —— 线程没有 JOB_THREAD_NAME,
    # `wait_for_idle_jobs()` 按名字找不到它(测试里 fresh_client() 就会在它还活着时
    # drop_all),而且这个 kind 的执行模式形同虚设:注册成 external 也照样在进程内跑。
    job_id, asset_id = job.id, asset.id
    dispatch_job(db, job, lambda: _trim_body(job_id, asset_id, start, end, mute))
    return job


def _trim_body(job_id: str, asset_id: str, start: float, end: float, mute: bool) -> None:
    # 任务线程的入口就是这次用例的边界:正常走完提交,抛出来回滚(失败由派发处套的 run_job_guarded 落进任务)。
    # 中间那次提交是有意的:ffmpeg 要跑一阵,「在截」得先让别的会话看得见。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        asset = db.get(Asset, asset_id)
        if job is None or asset is None:
            return
        # 状态经总线写:排队时被取消的,不在这里被写回「在跑」。
        if not start_job(db, job, progress=0.1):
            return
        say(job, "jobMsg_trimRunning")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        source = resolve_key(asset.file_key)
        if not source.is_file():
            raise TrimError("trimErr_fileMissing")

        suffix = source.suffix or (".mp4" if asset.kind == "video" else ".m4a")
        with tempfile.TemporaryDirectory(prefix="mosael-trim-") as tmp:
            target = Path(tmp) / f"trimmed{suffix}"
            #: **重新编码,不用 -c copy。** 流拷贝只能从关键帧切,用户要的 3.2 秒会变成最近
            #: 那个关键帧 —— 画面对不上,而且没有任何地方会说这件事。短素材重编码代价可以接受。
            args = [settings.ffmpeg, "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source)]
            if mute:
                args += ["-an"]
            args += [str(target)]
            try:
                run_logged(args, check=True, capture_output=True, timeout=600, what="素材截取")
            except subprocess.SubprocessError as exc:
                raise TrimError("trimErr_failed") from exc
            if not target.is_file() or target.stat().st_size == 0:
                raise TrimError("trimErr_empty")

            ensure_wanted()  # 截的时候被取消了:片段不进素材库
            made = register_file_asset(
                db,
                workspace_id=asset.workspace_id,
                project_id=asset.project_id,
                source_path=target,
                #: 名字带上范围 —— 一张画板上截出五段,光看「xxx 的片段」分不出哪段是哪段。
                name=f"{asset.name} · {start:.1f}-{end:.1f}s",
                source="generated",
                derived_from=derived(TRIM, asset.id),
            )

        #: 和语音合成同一个形状(单数)—— 画板的回执两种都读得懂,见 domain/boards。
        if finish_job(db, job, status="succeeded", progress=1.0, result={"asset_id": made.id}):
            say(job, "jobMsg_trimDone")
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": made.id})
        logger.info("trim %s [%.2f, %.2f] -> asset %s", asset.id, start, end, made.id)
