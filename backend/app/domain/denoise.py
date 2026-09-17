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

from app.ai.providers.contracts.denoise import DEFAULT_STRENGTH, DenoiseAdapter, DenoiseError, DenoiseRequest, checked_strength
from app.ai.providers.registry import DENOISE_ADAPTERS, get_denoise_adapter
from app.ai.runtime import denoise_models
from app.core.db import SessionLocal
from app.core.i18n import t
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import RENDER_SLOTS, create_job, dispatch_job, emit_job_event, run_job_guarded, say
from app.media.audio_io import AudioIOError, as_audio, replace_audio

logger = logging.getLogger(__name__)

DENOISABLE_KINDS = frozenset({"audio", "video"})


def ready_adapter(engine: str = "") -> DenoiseAdapter:
    """这次用哪个引擎;没有、或者没准备好,就抛一句说得清下一步的话。

    **不替用户准备**(装依赖、拉权重)—— 那是设置里显式的一步(ADR-0016 同一条)。
    """
    adapter = get_denoise_adapter(engine)
    if adapter is None:
        raise DenoiseError(f"没有这个降噪引擎:{engine}" if engine not in ("", "auto") else "没有可用的降噪引擎")
    if not adapter.runtime_ready():
        raise DenoiseError(t(adapter.setup_hint_key) if adapter.setup_hint_key else f"降噪引擎 {adapter.engine_id} 还没准备好")
    return adapter


def list_engines() -> list[dict]:
    """给界面和节点的引擎清单。`label` / `description` / `setup_hint` 是 i18n key,在出口翻译。

    要下载安装的引擎(见 runtime/denoise_models.INSTALLABLE)多带安装状态;其余的 `status`
    只说能不能用。**引擎自己不知道"安装"这回事** —— 那是运行时那一层的事,在这里合起来。
    """
    rows = []
    for adapter in DENOISE_ADAPTERS.values():
        ready = adapter.runtime_ready()
        row = {
            "engine": adapter.engine_id,
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


def install_engine(engine: str) -> dict:
    """开始装这个引擎。装在后台跑;返回的是那一行的新状态。"""
    denoise_models.start_install(engine)
    return next(row for row in list_engines() if row["engine"] == engine)


def denoise_asset(
    db: Session,
    asset: Asset,
    *,
    engine: str = "",
    strength: str = DEFAULT_STRENGTH,
    project_id: str | None = None,
) -> tuple[Asset, str]:
    """降噪,返回 (新素材, 实际用的引擎 id)。"""
    if asset.kind not in DENOISABLE_KINDS:
        raise DenoiseError("只有音频或视频素材可以降噪")
    adapter = ready_adapter(engine)
    # 没有档位的引擎不看这个值 —— 但它照样要是一个认得出的档位。
    request_strength = checked_strength(strength)

    source = _source_path(asset)
    if source is None or not source.is_file():
        raise DenoiseError("这份素材的文件找不到了")

    with tempfile.TemporaryDirectory(prefix="mosael-denoise-") as tmp:
        work = Path(tmp)
        try:
            audio = as_audio(source, work)
            cleaned = adapter.denoise(DenoiseRequest(audio_path=audio, strength=request_strength), work / "denoised.wav")
            output = cleaned if asset.kind == "audio" else replace_audio(source, cleaned, work / f"denoised{_video_suffix(source)}")
        except AudioIOError as exc:
            raise DenoiseError(str(exc)) from exc
        made = register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=project_id or asset.project_id,
            source_path=output,
            name=f"{asset.name} · 降噪",
            source="denoised",
        )
    # 派生关系记在新素材上(同分离、转 GIF),否则"这份是从哪份降出来的"只能靠名字猜。
    made.media_info = {
        **(made.media_info or {}),
        "derived_from_asset_id": asset.id,
        "derivation": "denoise",
        "denoise_engine": adapter.engine_id,
        "denoise_strength": request_strength if adapter.strengths else None,
    }
    db.commit()
    return made, adapter.engine_id


def _source_path(asset: Asset) -> Path | None:
    from app.media.paths import resolve_key

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
        raise DenoiseError("只有音频或视频素材可以降噪")
    if not asset.file_key:
        raise DenoiseError("这份素材没有本地文件")
    strength = checked_strength(strength)
    ready_adapter(engine)

    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="denoise_audio",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name, "engine": engine, "strength": strength},
        message="jobMsg_denoiseQueued",
    )
    db.commit()
    dispatch_job(db, job, lambda: _run_job(job.id, asset.id, engine, strength))
    return job


def _run_job(job_id: str, asset_id: str, engine: str, strength: str) -> None:
    # 和导出、转 GIF 同一档:"这台机器要忙一阵",不该几个一起抢 CPU。
    with RENDER_SLOTS:
        run_job_guarded(job_id, lambda: _job_body(job_id, asset_id, engine, strength), what="降噪")


def _job_body(job_id: str, asset_id: str, engine: str, strength: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        asset = db.get(Asset, asset_id)
        if job is None or asset is None:
            return
        job.status = "running"
        job.progress = 0.1
        say(job, "jobMsg_denoiseRunning")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        made, used = denoise_asset(db, asset, engine=engine, strength=strength)

        job.status = "succeeded"
        job.progress = 1.0
        job.result = {"asset_id": made.id, "source_asset_id": asset.id, "engine": used}
        say(job, "jobMsg_denoiseDone")
        emit_job_event(db, job.id, "job.succeeded", dict(job.result))
        db.commit()
        logger.info("asset %s -> denoised %s (%s)", asset.id, made.id, used)
