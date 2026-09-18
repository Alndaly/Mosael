"""把一份素材拆成人声和背景音两份素材。

**这一层是"能力"和"素材"之间的那道缝**(ADR-0016):上面的调用方(工作流节点、配音流程、
以后的剪辑台和 MCP)只跟这里说话,不认识任何一个引擎;下面由 `providers.registry` 决定
这次用哪个 Adapter。所以加一个引擎不需要改这里,而这里改了也不会波及某个引擎。

两条硬规矩:

- **产出新素材,不就地改原素材。** 原片一个字节都不动,拆出来的是两份新的音频素材。
  和配音同一条原则:不删任何东西,所以每一步都能靠"删掉新加的"回退。
- **可用性是问出来的。** `available()` 不读配置,它问注册表里有没有现在就跑得起来的引擎。
  问不到时调用方退回没有这个能力的做法 —— 而不是先调一次再看报错,那一次可能已经等了十分钟。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.providers.contracts.separation import (
    BACKGROUND,
    VOCALS,
    SeparationError,
    SeparationRequest,
)
from app.ai.providers.registry import get_separation_adapter
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.media.audio_io import AudioIOError, as_audio
from app.domain.jobs import RENDER_SLOTS, create_job, dispatch_job, emit_job_event, run_job_guarded, say

logger = logging.getLogger(__name__)

#: 拆出来的两份素材,名字后面缀什么。取名要让人在素材库里一眼认出它是从哪儿来的。
#: 「背景音」而不是「伴奏」:对视频来说人声之外是音乐 + 环境声 + 音效,「伴奏」是个音乐术语,说窄了。
_SUFFIX = {VOCALS: "人声", BACKGROUND: "背景音"}


@dataclass(frozen=True)
class SeparatedAssets:
    """一次分离的产出。两份都是**新的**素材行。"""

    vocals: Asset
    background: Asset
    engine: str


def available(engine: str = "") -> bool:
    """现在有没有跑得起来的分离引擎。"""
    adapter = get_separation_adapter(engine)
    return bool(adapter and adapter.runtime_ready())


def separate_asset(
    db: Session,
    asset: Asset,
    *,
    engine: str = "",
    project_id: str | None = None,
) -> SeparatedAssets:
    """把这份素材拆成人声 + 背景音两份新素材。

    输入可以是视频:分离引擎只认音频,所以先抽一条 wav 出来。**用的是保留原采样率的那条**
    (media/audio_io)—— 此前借的是转写那条,会先降成 16 kHz 单声道,拆出来的背景音再进成片时
    音质已经没了(ADR-0017 决定 6)。
    """
    adapter = get_separation_adapter(engine)
    if adapter is None:
        raise SeparationError("没有可用的音频分离引擎")
    if not adapter.runtime_ready():
        # 装是显式的一步:第一次要建 venv、装 torch、拉权重,那是几分钟到几十分钟的事,
        # 不该藏在"点一下分离"后面一声不响地发生。
        #
        # **装不成也是"这次分离失败了"**,所以翻成这一层的错误类型:RuntimeError 逃出去
        # 就成了节点抓不住的异常,用户看到的是一条没有下文的红线,而原因(pip 说的那句话)
        # 恰好就在这个异常里。
        try:
            adapter.ensure_runtime()
        except SeparationError:
            raise
        except Exception as exc:  # noqa: BLE001 — 建环境失败的形状由下面那层决定,这里只负责翻译
            raise SeparationError(str(exc)) from exc

    source = _source_path(asset)
    if source is None or not source.is_file():
        raise SeparationError("这份素材的文件找不到了")

    with tempfile.TemporaryDirectory(prefix="mosael-separate-") as tmp:
        work = Path(tmp)
        try:
            audio = as_audio(source, work)
        except AudioIOError as exc:
            raise SeparationError(str(exc)) from exc
        stems = adapter.separate(SeparationRequest(audio_path=audio), work / "out")
        made: dict[str, Asset] = {}
        for stem in (VOCALS, BACKGROUND):
            path = stems.get(stem)
            if path is None or not path.is_file():
                raise SeparationError(f"分离结果里缺少:{_SUFFIX[stem]}")
            made[stem] = register_file_asset(
                db,
                workspace_id=asset.workspace_id,
                project_id=project_id or asset.project_id,
                source_path=path,
                name=f"{asset.name} · {_SUFFIX[stem]}",
                source="separated",
            )
    return SeparatedAssets(vocals=made[VOCALS], background=made[BACKGROUND], engine=adapter.engine_id)


def _source_path(asset: Asset) -> Path | None:
    """素材的本机文件。走 `file_key` + resolve_key —— 转写那条路也是这么问的,
    而 Asset 上并没有一个现成的 `path` 字段(顶层那几个常见字段其实住在 media_info 里)。"""
    from app.media.paths import resolve_key

    if not asset.file_key:
        return None
    return resolve_key(asset.file_key)


# ---------------------------------------------------------------------------
# 当作任务跑(界面和智能体走这条)
# ---------------------------------------------------------------------------
def start_separation_job(db: Session, *, asset: Asset, created_by: str | None, engine: str = "") -> Job:
    """把分离排成一个任务。

    **为什么不是一次同步请求**:一段长素材在 CPU 上要跑十几分钟,而一个十几分钟不返回的 HTTP
    请求在任何一层(浏览器、反向代理、我们自己的超时)都会先断掉,用户看到的是"失败了",
    而后台其实还在跑。工作流那条路本身已经在任务里,所以它直接调 `separate_asset`;
    界面和智能体这条要有自己的任务,才有进度、有取消、有失败原因可看。

    占 RENDER_SLOTS:它和导出、转 GIF 一样是"这台机器要忙很久"的活,不该几个一起抢 CPU。
    """
    if asset.kind not in {"audio", "video"}:
        raise SeparationError("只有音频或视频素材可以分离")
    if not asset.file_key:
        raise SeparationError("这份素材没有本地文件")
    if not available(engine):
        #: **排队之前就问**:没有引擎时排一个注定失败的任务,只是把同一句话推迟十秒说。
        raise SeparationError("没有可用的音频分离引擎 —— 先在设置里装一个")

    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="separate_audio",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "engine": engine},
        message="jobMsg_separateQueued",
    )
    db.commit()
    dispatch_job(db, job, lambda: _run_job(job.id, asset.id, engine))
    return job


def _run_job(job_id: str, asset_id: str, engine: str) -> None:
    with RENDER_SLOTS:
        run_job_guarded(job_id, lambda: _job_body(job_id, asset_id, engine), what="人声与背景音分离")


def _job_body(job_id: str, asset_id: str, engine: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        asset = db.get(Asset, asset_id)
        if job is None or asset is None:
            return
        job.status = "running"
        job.progress = 0.1
        say(job, "jobMsg_separateRunning")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        made = separate_asset(db, asset, engine=engine)
        # 派生关系放在新素材上;原素材不改一字(和转 GIF 同款)。
        for stem, produced in ((VOCALS, made.vocals), (BACKGROUND, made.background)):
            produced.media_info = {
                **(produced.media_info or {}),
                "derived_from_asset_id": asset.id,
                "derivation": "separate_audio",
                "stem": stem,
                "separation_engine": made.engine,
            }
        db.commit()

        job.status = "succeeded"
        job.progress = 1.0
        job.result = {
            "vocals_asset_id": made.vocals.id,
            "background_asset_id": made.background.id,
            "source_asset_id": asset.id,
            "engine": made.engine,
        }
        say(job, "jobMsg_separateDone")
        emit_job_event(db, job.id, "job.succeeded", dict(job.result))
        db.commit()
        logger.info("asset %s -> stems %s / %s", asset.id, made.vocals.id, made.background.id)
