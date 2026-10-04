"""预览代理的**业务侧**:什么时候该生成、算不算一次任务、素材状态怎么改。

从 `app/media/proxy.py` 搬出来的。转码本身(ffmpeg 怎么调、并发几路)留在那边 —— 那是适配器
该管的;而建任务、发任务事件、把 `asset.media_info` 改成 pending/ready/failed,是业务决策。

一份素材最多有两样代理,同一个「proxy」任务一起出:
  ・**画面代理**(`proxy_status` / `proxy_key`):视频才有,WebCodecs 合成器解它。
  ・**音频代理**(`audio_proxy_status` / `audio_proxy_key`):有声音的素材(视频、音频)都有,预览混音器
    按需解它的一小段,而不是把整份原文件下下来全解。源文件没有音轨时记 `silent` —— 那是一个答案,
    不是失败:前端据此不再去取,启动扫描也不再替它排队(审查发现无声的 AI 视频曾被每 40ms 重下一遍)。

挤在一起时,`media` 反过来 import 了 `domain.jobs`:一个只该会干活的层认识了业务。方向反了
的直接代价是 `media` 用不了 —— 想在别处只调一次转码,会把整个任务系统拖进来。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain.assets.media_info import patch_media_info
from app.domain.jobs import create_job, dispatch_job, emit_job_event, run_job_guarded, say
from app.media.paths import resolve_key
from app.media.probe import probe_has_audio
from app.media.proxy import (
    AUDIO_PROXY_NAME,
    PROXY_NAME,
    TRANSCODE_SLOTS,
    audio_proxy_path,
    build_audio_proxy,
    build_proxy,
    proxy_path,
)

#: 这些状态下不用(再)转:已经有了、正在转。音频还多一个 silent —— 没有音轨,转不出东西。
_VIDEO_SETTLED = ("ready", "pending")
_AUDIO_SETTLED = ("ready", "pending", "silent")


def proxy_key_for(asset: Asset) -> str:
    """Storage key of the proxy sibling to the asset's own file."""
    return str(Path(asset.file_key).parent / PROXY_NAME)


def proxy_status(asset: Asset) -> str:
    """pending | ready | failed | none (not a video, or proxies disabled)."""
    return str((asset.media_info or {}).get("proxy_status") or "none")


def audio_proxy_key_for(asset: Asset) -> str:
    return str(Path(asset.file_key).parent / AUDIO_PROXY_NAME)


def audio_proxy_status(asset: Asset) -> str:
    """pending | ready | failed | silent(源文件没有音轨) | none(没声音的种类,或代理关了,或还没排过)。"""
    return str((asset.media_info or {}).get("audio_proxy_status") or "none")


def _set_proxy_meta(db: Session, asset_id: str, status: str, *, key: str | None = None) -> None:
    """只改代理自己那两个键(proxy_status / proxy_key),别的键不碰。

    转码线程在转码**之前**就读出了这份素材,转码一跑几十秒,这期间别人往 media_info 里补写的键
    (改口型记的块、配音记的音色)它手上的那份都没有 —— 此前拿它整份写回,把那些键全抹了
    (改口型的块缓存因此从来不命中)。见 assets/media_info。
    """
    if key is not None:
        patch_media_info(db, asset_id, {"proxy_status": status, "proxy_key": key})
    elif status != "ready":
        patch_media_info(db, asset_id, {"proxy_status": status}, drop=["proxy_key"])
    else:
        patch_media_info(db, asset_id, {"proxy_status": status})


def _set_audio_proxy_meta(db: Session, asset_id: str, status: str, *, key: str | None = None) -> None:
    """同 `_set_proxy_meta`,管音频代理那两个键。"""
    if key is not None:
        patch_media_info(db, asset_id, {"audio_proxy_status": status, "audio_proxy_key": key})
    else:
        patch_media_info(db, asset_id, {"audio_proxy_status": status}, drop=["audio_proxy_key"])


def proxies_possible(asset: Asset) -> bool:
    """这份素材**会不会**有代理 —— 三个条件和 `start_proxy_job` 的守卫是同一组。

    收敛成一个谓词,是因为这个答案要出现在**两个地方**:这里(建不建任务)和接口
    (`AssetOut.proxy_expected`,前端据此决定遮罩上说什么)。原先只有前者,后者靠前端猜:
    `generate_proxies` 关掉时后端不建任务、也不写 `proxy_status`,于是前端永远读到空串,
    落进「未知一律当作还在转」那一档 —— 遮罩上写着「转码中,等一会儿就好」,而那是一件
    **永远不会发生的事**,同时每 2 秒轮询一次素材。

    参数只用 `.kind` / `.file_key`,所以 ORM 行和出参模型都传得进来。
    """
    return bool(settings.generate_proxies and asset.kind == "video" and asset.file_key)


def audio_proxies_possible(asset: Asset) -> bool:
    """这份素材会不会有**音频**代理:有声音的种类(视频、音频)、有文件、代理开着。"""
    return bool(settings.generate_proxies and asset.kind in ("video", "audio") and asset.file_key)


def start_proxy_job(db: Session, asset: Asset, *, created_by: str | None, force: bool = False) -> Job | None:
    """Queue whichever proxies this asset still needs (in-process daemon thread).

    No-op (returns None) when proxies are disabled, the asset has nothing to proxy, or every
    proxy it can have is already ready/in-flight (unless `force`, which rebuilds them all).
    """
    video = proxies_possible(asset) and (force or proxy_status(asset) not in _VIDEO_SETTLED)
    audio = audio_proxies_possible(asset) and (force or audio_proxy_status(asset) not in _AUDIO_SETTLED)
    return queue_proxy_job(db, asset, created_by=created_by, video=video, audio=audio)


def queue_proxy_job(db: Session, asset: Asset, *, created_by: str | None, video: bool, audio: bool) -> Job | None:
    """排一个代理任务,只做点名的那几样;两样都不要就什么都不做。"""
    if not (video or audio):
        return None
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="proxy",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "video": video, "audio": audio},
        message="jobMsg_proxyQueued",
    )
    info = dict(asset.media_info or {})
    if video:
        info["proxy_status"] = "pending"
        info.pop("proxy_key", None)
    if audio:
        info["audio_proxy_status"] = "pending"
        info.pop("audio_proxy_key", None)
    asset.media_info = info
    # 经总线派发(它先提交再起线程,线程读得到这里刚写的 pending)。此前这里是一句裸的线程创建 ——
    # 线程没有 JOB_THREAD_NAME,`wait_for_idle_jobs()` 按名字找不到它(测试里 fresh_client() 就会在它还活着时
    # drop_all),而且这个 kind 的执行模式形同虚设:注册成 external 也照样在进程内跑。
    job_id, asset_id = job.id, asset.id
    dispatch_job(db, job, lambda: _run_proxy(job_id, asset_id))
    return job


def _run_proxy(job_id: str, asset_id: str) -> None:
    """Wait for a transcode slot BEFORE opening a database session.

    The slot used to be taken inside the session, so every queued worker sat in the semaphore
    while holding a pooled connection. The pool is 5 + 10 overflow with a 30s checkout timeout,
    so a startup backfill of 60 videos put 45 threads into that timeout — each dying with its
    job still `queued` and nothing to reconcile it. Queueing on the semaphore costs a sleeping
    thread; queueing on the connection pool costs the job.
    """
    with TRANSCODE_SLOTS:
        run_job_guarded(job_id, lambda: _proxy_body(job_id, asset_id), what="代理生成")


def _proxy_body(job_id: str, asset_id: str) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        # 做哪几样写在任务的 payload 里(排队时定的),worker 只认任务,不另传参数。
        video = bool(job.payload["video"])
        audio = bool(job.payload["audio"])
        try:
            job.status = "running"
            say(job, "jobMsg_proxyRunning")
            job.progress = 0.1
            emit_job_event(db, job.id, "job.running", {})
            # 「在跑」先落库:转码要一阵,界面要马上看得到。
            db.commit()

            asset = db.get(Asset, asset_id)
            if asset is None or not asset.file_key:
                _fail(db, job_id, asset_id, "素材文件缺失", video=video, audio=audio)
                return
            source = resolve_key(asset.file_key)
            result: dict[str, str] = {}
            failures: list[str] = []
            # 两样各自落各自的状态:画面代理转坏了,声音照样能听;反过来也一样。
            if video:
                if build_proxy(source, proxy_path(source.parent)):  # slot already held by _run_proxy
                    result["proxy_key"] = proxy_key_for(asset)
                    _set_proxy_meta(db, asset_id, "ready", key=result["proxy_key"])
                else:
                    _set_proxy_meta(db, asset_id, "failed")
                    failures.append("ffmpeg 代理转码失败")
            if audio:
                if not probe_has_audio(source):
                    _set_audio_proxy_meta(db, asset_id, "silent")
                elif build_audio_proxy(source, audio_proxy_path(source.parent)):
                    result["audio_proxy_key"] = audio_proxy_key_for(asset)
                    _set_audio_proxy_meta(db, asset_id, "ready", key=result["audio_proxy_key"])
                else:
                    _set_audio_proxy_meta(db, asset_id, "failed")
                    failures.append("ffmpeg 音频代理转码失败")
            job = db.get(Job, job_id)
            if failures:
                _fail_job(db, job, ";".join(failures))
                return
            job.status = "succeeded"
            job.progress = 1.0
            say(job, "jobMsg_proxyDone")
            job.result = result
            emit_job_event(db, job.id, "job.succeeded", result)
        except Exception as exc:  # a worker thread must record failure, never die silently
            db.rollback()
            _fail(db, job_id, asset_id, str(exc)[:500], video=video, audio=audio)


def _fail(db: Session, job_id: str, asset_id: str, reason: str, *, video: bool, audio: bool) -> None:
    """整次任务没跑完:点名要转、而此刻还挂在 pending 的那几样记成 failed(已经落了终态的不动)。"""
    asset = db.get(Asset, asset_id)
    if video and (asset is None or proxy_status(asset) == "pending"):
        _set_proxy_meta(db, asset_id, "failed")
    if audio and (asset is None or audio_proxy_status(asset) == "pending"):
        _set_audio_proxy_meta(db, asset_id, "failed")
    _fail_job(db, db.get(Job, job_id), reason)


def _fail_job(db: Session, job: Job | None, reason: str) -> None:
    if job is not None:
        job.status = "failed"
        say(job, "jobMsg_proxyFailed")
        job.error = reason
        emit_job_event(db, job.id, "job.failed", {"reason": reason})


def reconcile_missing_proxies(db: Session) -> int:
    """Startup: (re)queue the proxies (picture and audio) that are missing on disk.

    A backend restart orphans the daemon thread, leaving media_info stuck at
    "pending"; here we re-drive anything whose proxy file is actually missing,
    and repair the status of proxies that exist on disk but lost their flag.

    这也是**音频代理的补建流程**:音频代理是后来加的,之前入库的素材一份都没有,启动扫描替它们
    各排一次(和画面代理当初上线时一样)。字段是新增的、旧素材上没有就是「还没排过」,不需要迁移。
    """
    if not settings.generate_proxies:
        return 0
    queued = 0
    for asset in db.scalars(select(Asset).where(Asset.kind.in_(("video", "audio")))):
        if not asset.file_key:
            continue
        directory = resolve_key(asset.file_key).parent
        video = False
        if proxies_possible(asset):
            if proxy_path(directory).is_file():
                if proxy_status(asset) != "ready":
                    _set_proxy_meta(db, asset.id, "ready", key=proxy_key_for(asset))
            # failed 是**判定过的终态**,不是"还没跑":源文件坏的素材每次转必败,启动扫描再替它
            # 排队只会无限重试 —— dev 模式每次热重启跑一轮,两个坏素材曾这样滚出上千条失败任务。
            # 这里只救 pending 孤儿(重启害死的)和从没跑过的;想再试坏素材走手动重试(那是人的判断)。
            elif proxy_status(asset) != "failed":
                video = True
        audio = False
        if audio_proxies_possible(asset):
            if audio_proxy_path(directory).is_file():
                if audio_proxy_status(asset) != "ready":
                    _set_audio_proxy_meta(db, asset.id, "ready", key=audio_proxy_key_for(asset))
            # silent 同理是终态:没有音轨的素材转一万次也没有声音。
            elif audio_proxy_status(asset) not in ("failed", "silent"):
                audio = True
        if queue_proxy_job(db, asset, created_by=None, video=video, audio=audio):  # 启动时的补齐扫描,没有操作人
            queued += 1
    return queued
