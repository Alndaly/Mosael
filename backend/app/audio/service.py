"""Transcription service: extract audio, run the ASR worker in the configured
interpreter, and attach the resulting transcript (with word tokens) to the
asset. The worker subprocess keeps torch/funasr/whisperx out of this process.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.jobs import ASR_SLOTS, run_job_guarded
from app.db.models import Asset, Job
from app.domain.jobs import create_job, dispatch_job, emit_job_event
from app.domain.transcripts.operations import SegmentIn, TokenIn, attach_transcript
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

WORKER_PATH = Path(__file__).with_name("asr_worker.py")
ASR_TIMEOUT_SECONDS = 3600


class AsrError(RuntimeError):
    pass


def resolve_asr_runtime() -> tuple[str, str]:
    """(解释器路径, 引擎)。探测与缓存都在 asr_models —— **这件事只有一份实现**。

    此前这里自己又探测了一遍,和 asr_models 那份各带一份缓存。两份实现意味着两个答案:托管 venv
    加进了那一份、漏了这一份,于是模型页显示「已安装」而一点转写就报"没有运行环境"。
    """
    from app.audio.asr_models import resolve_engine_python

    preferred = settings.asr_provider.strip().lower()
    engines = ["funasr", "whisperx"] if preferred in ("", "auto") else [preferred]
    for engine in engines:
        python = resolve_engine_python(engine)
        if python:
            return python, engine
    raise AsrError(
        # 纯文本,不要 markdown —— 这句话会原样显示在界面上,星号只会以星号的样子出现。
        "缺的是运行环境,不是模型:模型权重已经下好的话不用再下一遍,"
        "但还没有任何 Python 解释器装了 funasr 或 whisperx。"
        "去设置的「转写模型」那一页点「安装运行环境」,装一次就好。"
    )


def _extract_audio(source: Path, target: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn",
         "-ac", "1", "-ar", "16000", "-f", "wav", str(target)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise AsrError(f"音频提取失败: {result.stderr[-400:]}")


def run_asr(audio_path: Path, python: str, provider: str) -> dict:
    request = {
        "audio_path": str(audio_path),
        "provider": provider,
        "whisper_model": settings.asr_whisper_model,
    }
    # Results travel via a file: funasr and hub downloads write progress bars
    # straight to stdout, which would corrupt an inline JSON pipe.
    output_path = audio_path.with_name("asr-result.json")
    result = subprocess.run(
        [python, str(WORKER_PATH), str(output_path)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=ASR_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise AsrError(f"转写失败 ({provider}): {result.stderr[-600:]}")
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AsrError(f"转写输出无法解析: {result.stdout[-300:]}") from exc


def to_segment_ins(segments: list[dict]) -> list[SegmentIn]:
    parsed: list[SegmentIn] = []
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        if end <= start:
            continue
        tokens = tuple(
            TokenIn(start_time=float(w["start"]), end_time=max(float(w["end"]), float(w["start"]) + 0.001),
                    text=str(w["word"]))
            for w in (segment.get("words") or [])
            if str(w.get("word", "")).strip()
        )
        parsed.append(
            SegmentIn(
                start_time=start,
                end_time=end,
                text=str(segment.get("text") or ""),
                speaker=segment.get("speaker"),
                tokens=tokens,
            )
        )
    return parsed


def _watch_model_download(job_id: str, provider: str) -> threading.Event:
    """While a transcribe is running, if its model isn't installed yet, poll the
    download and map it onto job progress 0.25→0.9. Returns a stop Event."""
    from app.audio import asr_models

    stop = threading.Event()
    entry = asr_models.entry_for_transcribe(provider)
    if entry is None or asr_models.is_installed(entry):
        return stop  # nothing to download → leave the job at 0.25 during inference

    def _loop() -> None:
        while not stop.wait(2.0):
            fraction = asr_models.measure_fraction(entry)
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is None or job.status != "running":
                    return
                job.progress = round(0.25 + fraction * 0.6, 4)  # 0.25..0.85
                job.message = f"首次转写:下载模型中 {int(fraction * 100)}%"
                db.commit()

    threading.Thread(target=_loop, daemon=True).start()
    return stop


def start_transcription(db: Session, asset_id: str, *, created_by: str | None) -> Job:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise AsrError("Asset not found")
    if asset.kind not in ("video", "audio"):
        raise AsrError("只有视频或音频素材可以转写")
    if not asset.file_key:
        raise AsrError("素材没有本地文件")
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="transcribe",
        payload={"asset_id": asset_id},
        created_by=created_by,
        message="转写排队中",
    )
    dispatch_job(db, job, lambda: _run_transcription(job.id, asset_id))
    return job


def _run_transcription(job_id: str, asset_id: str) -> None:
    """Take an admission slot before touching the database — see run_job_guarded."""
    with ASR_SLOTS:
        run_job_guarded(job_id, lambda: _run_transcription_body(job_id, asset_id), what="转写")


def _run_transcription_body(job_id: str, asset_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            python, provider = resolve_asr_runtime()
            job.status = "running"
            job.message = f"{provider} 转写中(首次会自动下载模型)"
            job.progress = 0.1
            emit_job_event(db, job.id, "job.running", {"provider": provider})
            db.commit()
            logger.info("transcription job %s: provider=%s asset=%s", job_id, provider, asset_id)

            asset = db.get(Asset, asset_id)
            source = resolve_key(asset.file_key)
            with tempfile.TemporaryDirectory(prefix="open-studio-asr-") as tmp:
                wav = Path(tmp) / "audio.wav"
                _extract_audio(source, wav)
                job.progress = 0.25
                db.commit()
                # First transcribe on a machine downloads ~2GB of models inside the
                # library — surface that as job progress instead of a frozen 25%.
                stop = _watch_model_download(job_id, provider)
                try:
                    output = run_asr(wav, python, provider)
                finally:
                    stop.set()

            segments = to_segment_ins(output.get("segments") or [])
            if not segments:
                raise AsrError("转写结果为空")
            transcript = attach_transcript(
                db,
                asset_id=asset_id,
                language=str(output.get("language") or "zh"),
                segments=segments,
                source=f"asr:{provider}",
            )
            job = db.get(Job, job_id)
            job.status = "succeeded"
            job.progress = 1.0
            job.message = "转写完成"
            job.result = {"transcript_id": transcript.id, "segments": len(segments)}
            emit_job_event(db, job.id, "job.succeeded", {"transcript_id": transcript.id})
            db.commit()
            logger.info("transcription job %s succeeded: %d segments (%s)", job_id, len(segments), provider)
        except Exception as exc:  # noqa: BLE001 — worker thread must record, not die
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.message = "转写失败"
                job.error = str(exc)[:800]
                emit_job_event(db, job.id, "job.failed", {})
                db.commit()
            logger.warning("transcription job %s failed: %s", job_id, exc)


__all__ = ["AsrError", "start_transcription", "resolve_asr_runtime", "to_segment_ins", "run_asr"]
