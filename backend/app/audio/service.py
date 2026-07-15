"""Transcription service: extract audio, run the ASR worker in the configured
interpreter, and attach the resulting transcript (with word tokens) to the
asset. The worker subprocess keeps torch/funasr/whisperx out of this process.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job, TaskEvent
from app.domain.jobs import create_job
from app.domain.transcripts.operations import SegmentIn, TokenIn, attach_transcript
from app.media.paths import resolve_key

WORKER_PATH = Path(__file__).with_name("asr_worker.py")
ASR_TIMEOUT_SECONDS = 3600


class AsrError(RuntimeError):
    pass


def _candidate_pythons() -> list[Path]:
    candidates: list[Path] = []
    if settings.asr_python:
        candidates.append(Path(settings.asr_python).expanduser())
    # Dev convenience: reuse the sibling mibu-video venv (funasr + whisperx
    # plus their model caches are already there).
    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(repo_root.parent / "mibu-video" / "backend" / ".venv" / "bin" / "python")
    import sys

    candidates.append(Path(sys.executable))
    return candidates


@lru_cache(maxsize=1)
def resolve_asr_runtime() -> tuple[str, str]:
    """(python_path, provider). Probes each candidate interpreter for funasr,
    then whisperx. Cached — probing spawns interpreters."""
    preferred = settings.asr_provider.strip().lower()
    providers = ["funasr", "whisperx"] if preferred in ("", "auto") else [preferred]
    for python in _candidate_pythons():
        if not python.is_file():
            continue
        for provider in providers:
            probe = subprocess.run(
                [str(python), "-c", f"import {provider}"],
                capture_output=True,
                timeout=120,
            )
            if probe.returncode == 0:
                return str(python), provider
    raise AsrError(
        "未找到可用的转写环境:请安装 funasr 或 whisperx,"
        "或设置 MIBU_ASR_PYTHON 指向已安装它们的 Python 解释器"
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


def start_transcription(db: Session, asset_id: str) -> Job:
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
        message="转写排队中",
    )
    db.commit()
    thread = threading.Thread(target=_run_transcription, args=(job.id, asset_id), daemon=True)
    thread.start()
    return job


def _run_transcription(job_id: str, asset_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            python, provider = resolve_asr_runtime()
            job.status = "running"
            job.message = f"{provider} 转写中(首次会自动下载模型)"
            job.progress = 0.1
            db.add(TaskEvent(job_id=job.id, type="job.running", payload={"provider": provider}))
            db.commit()

            asset = db.get(Asset, asset_id)
            source = resolve_key(asset.file_key)
            with tempfile.TemporaryDirectory(prefix="mibu-asr-") as tmp:
                wav = Path(tmp) / "audio.wav"
                _extract_audio(source, wav)
                job.progress = 0.25
                db.commit()
                output = run_asr(wav, python, provider)

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
            db.add(TaskEvent(job_id=job.id, type="job.succeeded", payload={"transcript_id": transcript.id}))
            db.commit()
        except Exception as exc:  # noqa: BLE001 — worker thread must record, not die
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.message = "转写失败"
                job.error = str(exc)[:800]
                db.add(TaskEvent(job_id=job.id, type="job.failed", payload={}))
                db.commit()


__all__ = ["AsrError", "start_transcription", "resolve_asr_runtime", "to_segment_ins", "run_asr"]
