"""给一份素材降噪,产出一份**新**素材。

**这一层是"能力"和"素材"之间的那道缝**(ADR-0017,形状同 ADR-0016 的分离):上面的入口
(工作流节点、智能体工具、素材库、剪辑台)只跟这里说话,不认识任何引擎;下面由
`providers.registry` 决定这次用哪个 Adapter。

- **产出新素材,原素材一个字节不动。** 音频进、音频出;视频进、视频出 —— 画面原样拷贝,只换声音。
  用户在素材库里对一段视频点「降噪」,要的是一段干净的视频,不是一段要自己再合回去的音频。
- **引擎只处理音频。** 抽声音、放回去是这一层的事(media/audio_io),引擎不必各自会一遍。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.providers.contracts.denoise import (
    DEFAULT_STRENGTH,
    STRENGTHS,
    DenoiseAdapter,
    DenoiseError,
    DenoiseRequest,
    checked_strength,
)
from app.ai.providers.registry import DENOISE_ADAPTERS
from app.ai.runtime import denoise_models
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import DENOISE, derived
from app.domain.jobs import (
    RENDER_SLOTS,
    create_job,
    dispatch_job,
    emit_job_event,
    ensure_wanted,
    finish_job,
    say,
    start_job,
)
from app.media.audio_io import AudioIOError, as_audio, replace_audio
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

DENOISABLE_KINDS = frozenset({"audio", "video"})


class DenoiseDomainError(DenoiseError):
    """这一层说的「降不了」:带文案 key(`denoiseErr_*`),按读的人的语言翻。

    仍是 DenoiseError —— 上面那些 `except DenoiseError` 照样接得住。
    """


def ready_adapter(db: Session, owner_user_id: str | None, engine: str = "") -> DenoiseAdapter:
    """这次用哪一家(ADR 0032):`engine` 是提供方 id(内置的 `builtin:<引擎>`、插件的连接 id),空 = 按这个人的默认,
    没定就用第一个跑得起来、不动配乐的内置引擎。挑不出来、没准备好,抛一句说得清下一步的话。

    **不替用户准备**(装依赖、拉权重)—— 那是设置里显式的一步(ADR-0016 同一条)。
    """
    from app.domain.audio_capabilities import denoise_adapter

    return denoise_adapter(db, owner_user_id, engine)


def list_engines(db: Session, owner_user_id: str | None) -> list[dict]:
    """给界面的候选:内置引擎(带安装状态)和这个人配好的降噪插件。`engine` 是提供方 id。
    内置的 `label` / `description` / `setup_hint` 是 i18n key,在出口翻译;插件的 `label` 就是连接名。

    要下载安装的引擎(见 runtime/denoise_models.INSTALLABLE)多带安装状态。**引擎自己不知道"安装"这回事** ——
    那是运行时那一层的事,在这里合起来。
    """
    from app.domain import capabilities
    from app.domain.audio_capabilities import BUILTIN_PREFIX, DENOISE

    rows = []
    for provider in capabilities.providers(db, owner_user_id, DENOISE):
        if not provider.builtin:
            ready = not provider.missing
            rows.append({
                "engine": provider.id, "label": provider.name, "description": "", "setup_hint": "",
                "ready": ready, "strengths": list(STRENGTHS), "removes_music": False, "installable": False,
                "status": "ready" if ready else "unavailable", "message": "；".join(provider.missing),
                "message_params": {}, "size_bytes": 0,
            })
            continue
        adapter = DENOISE_ADAPTERS[provider.id.removeprefix(BUILTIN_PREFIX)]
        ready = adapter.runtime_ready()
        row = {
            "engine": provider.id,
            "label": adapter.label_key,
            "description": adapter.description_key,
            "setup_hint": "" if ready else adapter.setup_hint_key,
            "ready": ready,
            "strengths": list(adapter.strengths),
            "removes_music": adapter.removes_music,
            "installable": adapter.engine_id in denoise_models.INSTALLABLE,
            "status": "ready" if ready else "unavailable",
            "message": "",
            "message_params": {},
            "size_bytes": 0,
        }
        if row["installable"]:
            row.update(denoise_models.install_status(adapter.engine_id))
        rows.append(row)
    return rows


def install_engine(db: Session, owner_user_id: str | None, engine: str) -> dict:
    """开始装这个内置引擎(提供方 id `builtin:<引擎>`)。装在后台跑;返回的是那一行的新状态。"""
    from app.domain.audio_capabilities import BUILTIN_PREFIX

    denoise_models.start_install(engine.removeprefix(BUILTIN_PREFIX))
    return next(row for row in list_engines(db, owner_user_id) if row["engine"] == engine)


def denoise_asset(
    db: Session,
    asset: Asset,
    *,
    engine: str = "",
    strength: str = DEFAULT_STRENGTH,
    project_id: str | None = None,
    owner_user_id: str | None = None,
) -> tuple[Asset, str]:
    """降噪,返回 (新素材, 实际用的提供方 id)。`owner_user_id`:谁在做 —— 用他的默认和他的插件连接。"""
    if asset.kind not in DENOISABLE_KINDS:
        raise DenoiseDomainError("denoiseErr_notMedia")
    adapter = ready_adapter(db, owner_user_id, engine)
    # 没有档位的引擎不看这个值 —— 但它照样要是一个认得出的档位。
    request_strength = checked_strength(strength)

    source = _source_path(asset)
    if source is None or not source.is_file():
        raise DenoiseDomainError("denoiseErr_fileMissing")

    with tempfile.TemporaryDirectory(prefix="mosael-denoise-") as tmp:
        work = Path(tmp)
        try:
            audio = as_audio(source, work)
            cleaned = adapter.denoise(DenoiseRequest(audio_path=audio, strength=request_strength), work / "denoised.wav")
            output = cleaned if asset.kind == "audio" else replace_audio(source, cleaned, work / f"denoised{_video_suffix(source)}")
        except AudioIOError as exc:
            raise DenoiseError(str(exc)) from exc
        # 降噪的时候这件活被取消了:ffmpeg / 引擎已被停下,产出不进素材库。
        ensure_wanted()
        made = register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=project_id or asset.project_id,
            source_path=output,
            name=f"{asset.name} · 降噪",
            source="denoised",
            # 派生关系记在新素材上(同分离、转 GIF),否则"这份是从哪份降出来的"只能靠名字猜。
            derived_from=derived(DENOISE, asset.id),
        )
    made.media_info = {
        **(made.media_info or {}),
        "denoise_engine": adapter.engine_id,
        "denoise_strength": request_strength if adapter.strengths else None,
    }
    return made, adapter.engine_id


def _source_path(asset: Asset) -> Path | None:
    """素材的本机文件。走 `file_key` + resolve_key —— 转写那条路也是这么问的,
    而 Asset 上并没有一个现成的 `path` 字段(顶层那几个常见字段其实住在 media_info 里)。"""
    if not asset.file_key:
        return None
    return resolve_key(asset.file_key)


def _video_suffix(source: Path) -> str:
    # mp4/mov/m4v 能装 aac;别的容器(webm、avi)不一定,统一出 mp4。
    return source.suffix.lower() if source.suffix.lower() in {".mp4", ".mov", ".m4v"} else ".mp4"


# ---------------------------------------------------------------------------
# 当作任务跑(界面和智能体走这条;工作流本身已经在任务里,直接调 denoise_asset)
# ---------------------------------------------------------------------------
def start_denoise_job(
    db: Session,
    *,
    asset: Asset,
    created_by: str | None,
    engine: str = "",
    strength: str = DEFAULT_STRENGTH,
) -> Job:
    """排成任务。一小时的素材滤一遍也要一两分钟,模型类引擎更久 —— 不挂在一个 HTTP 请求上。

    **排队之前就把能判的判掉**(素材类型、引擎在不在、档位认不认得):排一个注定失败的任务,
    只是把同一句话推迟几秒说。
    """
    if asset.kind not in DENOISABLE_KINDS:
        raise DenoiseDomainError("denoiseErr_notMedia")
    if not asset.file_key:
        raise DenoiseDomainError("denoiseErr_noLocalFile")
    strength = checked_strength(strength)
    ready_adapter(db, created_by, engine)

    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="denoise_audio",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "engine": engine, "strength": strength},
        message="jobMsg_denoiseQueued",
    )
    job_id, asset_id = job.id, asset.id
    dispatch_job(db, job, lambda: _run_job(job_id, asset_id, engine, strength))
    return job


def _run_job(job_id: str, asset_id: str, engine: str, strength: str) -> None:
    # 和导出、转 GIF 同一档:"这台机器要忙一阵",不该几个一起抢 CPU。
    with RENDER_SLOTS:
        _job_body(job_id, asset_id, engine, strength)


def _job_body(job_id: str, asset_id: str, engine: str, strength: str) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        asset = db.get(Asset, asset_id)
        if job is None or asset is None:
            return
        # 状态经 finish_job 写,理由同分离(见 separation._job_body)。
        if not start_job(db, job, progress=0.1):
            return
        say(job, "jobMsg_denoiseRunning")
        emit_job_event(db, job.id, "job.running", {})
        # 「在跑」先落库:降噪要跑一阵,界面要马上看得到;也把 finish_job 拿的写锁放掉。
        db.commit()

        made, used = denoise_asset(db, asset, engine=engine, strength=strength, owner_user_id=job.created_by)

        result = {"asset_id": made.id, "source_asset_id": asset.id, "engine": used}
        if finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_denoiseDone")
            emit_job_event(db, job.id, "job.succeeded", dict(result))
        logger.info("asset %s -> denoised %s (%s)", asset.id, made.id, used)
