"""Voice-clone domain: manage cloned voices (reference clip + transcript) and
synthesize new speech in a voice via the external TTS worker. Synthesized speech
is registered as a normal audio asset (with waveform), so it can be dragged onto
the timeline like any other clip.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audio.tts_models import WORKER_PATH, resolve_tts_python
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job, TaskEvent, Voice
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job
from app.media.paths import resolve_key, voice_dir, voice_key

REFERENCE_MAX_SECONDS = 15
TTS_TIMEOUT_SECONDS = 1200


class VoiceError(RuntimeError):
    pass


def _transcode_reference(source: Path, target: Path) -> None:
    """Normalize any uploaded audio/video to 24k mono WAV, capped at 15s."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "24000",
         "-t", str(REFERENCE_MAX_SECONDS), str(target)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0 or not target.exists():
        raise VoiceError(f"参考音频处理失败: {result.stderr[-300:]}")


def create_from_upload(db: Session, *, workspace_id: str, source: Path, name: str, reference_text: str) -> Voice:
    from app.db.models import new_id

    voice_id = new_id()
    target_dir = voice_dir(workspace_id, voice_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ref = target_dir / "reference.wav"
    _transcode_reference(source, ref)

    voice = Voice(
        id=voice_id,
        workspace_id=workspace_id,
        name=name.strip() or "未命名音色",
        reference_text=reference_text.strip(),
        reference_key=voice_key(workspace_id, voice_id, "reference.wav"),
        source="upload",
    )
    db.add(voice)
    db.commit()
    db.refresh(voice)
    return voice


def create_from_speaker(db: Session, *, workspace_id: str, asset_id: str, speaker: str | None, name: str) -> Voice:
    """Clone a voice from a transcribed asset: pull up to ~8s of the given
    speaker's own audio (their transcript segments) as the reference clip, and
    their transcript text as the reference text."""
    from app.db.models import Transcript, new_id

    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise VoiceError("素材不存在")
    if not asset.file_key:
        raise VoiceError("素材没有本地文件")
    transcript = db.scalar(select(Transcript).where(Transcript.asset_id == asset_id))
    if transcript is None:
        raise VoiceError("该素材还没有逐字稿,请先转写")

    segments = [
        seg
        for seg in transcript.segments
        if (speaker is None or seg.speaker == speaker) and seg.end_time - seg.start_time >= 0.2
    ]
    picked: list = []
    total = 0.0
    for seg in segments:
        picked.append(seg)
        total += seg.end_time - seg.start_time
        if total >= 8.0:
            break
    if not picked:
        raise VoiceError("没有找到该说话人的可用片段")

    reference_text = " ".join(seg.text.strip() for seg in picked if seg.text.strip())[:2000]
    voice_id = new_id()
    target_dir = voice_dir(workspace_id, voice_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ref = target_dir / "reference.wav"
    # Select just this speaker's ranges in one pass and re-stamp timestamps.
    expr = "+".join(f"between(t,{seg.start_time:.3f},{seg.end_time:.3f})" for seg in picked)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(resolve_key(asset.file_key)), "-vn",
         "-af", f"aselect='{expr}',asetpts=N/SR/TB", "-ac", "1", "-ar", "24000", str(ref)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0 or not ref.exists():
        raise VoiceError(f"提取说话人音频失败: {result.stderr[-300:]}")

    voice = Voice(
        id=voice_id,
        workspace_id=workspace_id,
        name=name.strip() or (speaker or "说话人音色"),
        reference_text=reference_text,
        reference_key=voice_key(workspace_id, voice_id, "reference.wav"),
        source="speaker",
        source_asset_id=asset_id,
        source_speaker=speaker,
    )
    db.add(voice)
    db.commit()
    db.refresh(voice)
    return voice


def list_voices(db: Session, workspace_id: str) -> list[Voice]:
    return list(
        db.scalars(select(Voice).where(Voice.workspace_id == workspace_id).order_by(Voice.created_at.desc()))
    )


def get_voice(db: Session, voice_id: str) -> Voice | None:
    return db.get(Voice, voice_id)


def delete_voice(db: Session, voice: Voice) -> None:
    ref_dir = resolve_key(voice.reference_key).parent if voice.reference_key else None
    db.delete(voice)
    db.commit()
    if ref_dir is not None and ref_dir.is_dir():
        import shutil

        shutil.rmtree(ref_dir, ignore_errors=True)


def reference_path(voice: Voice) -> Path:
    return resolve_key(voice.reference_key)


def start_synthesis(db: Session, *, voice_id: str, text: str, project_id: str | None) -> Job:
    voice = db.get(Voice, voice_id)
    if voice is None:
        raise VoiceError("音色不存在")
    if not text.strip():
        raise VoiceError("合成文本不能为空")
    job = create_job(
        db,
        workspace_id=voice.workspace_id,
        kind="tts",
        payload={"voice_id": voice_id, "project_id": project_id, "text": text[:200]},
        message=f"合成《{voice.name}》配音中",
    )
    db.commit()
    thread = threading.Thread(target=_run_synthesis, args=(job.id, voice_id, text, project_id), daemon=True)
    thread.start()
    return job


def _run_synthesis(job_id: str, voice_id: str, text: str, project_id: str | None) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            voice = db.get(Voice, voice_id)
            if voice is None:
                raise VoiceError("音色不存在")
            job.status = "running"
            job.progress = 0.2
            job.message = f"合成《{voice.name}》配音中"
            db.add(TaskEvent(job_id=job.id, type="job.running", payload={}))
            db.commit()

            ref = reference_path(voice)
            if not ref.is_file():
                raise VoiceError("音色参考音频缺失")
            engine = settings.tts_engine
            python = resolve_tts_python(None)  # placeholder fallback works on any interpreter
            with tempfile.TemporaryDirectory(prefix="mibu-tts-") as tmp:
                out_wav = Path(tmp) / "speech.wav"
                request = {
                    "action": "synthesize",
                    "engine": engine,
                    "reference_wav": str(ref),
                    "reference_text": voice.reference_text,
                    "text": text,
                }
                proc = subprocess.run(
                    [python, str(WORKER_PATH), str(out_wav)],
                    input=json.dumps(request), capture_output=True, text=True, timeout=TTS_TIMEOUT_SECONDS,
                )
                if proc.returncode != 0 or not out_wav.exists():
                    raise VoiceError(f"语音合成失败: {proc.stderr[-400:]}")
                used = "placeholder"
                meta = Path(str(out_wav) + ".json")
                if meta.exists():
                    used = json.loads(meta.read_text()).get("engine", used)
                job.progress = 0.85
                db.commit()
                asset = register_file_asset(
                    db,
                    workspace_id=voice.workspace_id,
                    project_id=project_id,
                    source_path=out_wav,
                    name=f"{voice.name} · 配音",
                    source="tts",
                )
            job = db.get(Job, job_id)
            job.status = "succeeded"
            job.progress = 1.0
            job.message = "配音已生成" if used != "placeholder" else "配音已生成(占位音,装 f5-tts 后为真实音色)"
            job.result = {"asset_id": asset.id, "engine": used}
            db.add(TaskEvent(job_id=job.id, type="job.succeeded", payload={"asset_id": asset.id}))
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.message = "配音生成失败"
                job.error = str(exc)[:600]
                db.add(TaskEvent(job_id=job.id, type="job.failed", payload={}))
                db.commit()


__all__ = [
    "VoiceError",
    "create_from_upload",
    "create_from_speaker",
    "list_voices",
    "get_voice",
    "delete_voice",
    "reference_path",
    "start_synthesis",
]
