"""Voice-clone domain: manage cloned voices (reference clip + transcript) and
synthesize new speech in a voice via the external TTS worker. Synthesized speech
is registered as a normal audio asset (with waveform), so it can be dragged onto
the timeline like any other clip.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audio.tts_models import WORKER_PATH, resolve_tts_python
from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.jobs import TTS_SLOTS, run_job_guarded
from app.db.models import Asset, Job, Voice
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job, dispatch_job, emit_job_event
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


def start_synthesis(
    db: Session,
    *,
    text: str,
    project_id: str | None,
    voice_id: str | None = None,
    workspace_id: str = "",
    engine: str = "clone",
    engine_voice: str = "",
    engine_voice_resource: str = "",
    provider_profile_id: str | None = None,
    engine_model: str = "",
    speed: float = 1.0,
) -> Job:
    """Queue a synthesis job.

    The clone engine needs a Voice row — it works from that reference clip. A remote engine does
    not: it speaks in a stock voice, so it needs a workspace to own the result and an engine
    voice id, and requiring a Voice there would mean inventing rows for voices we do not host.
    """
    if not text.strip():
        raise VoiceError("合成文本不能为空")
    voice = None
    if engine == "clone":
        voice = db.get(Voice, voice_id or "")
        if voice is None:
            raise VoiceError("音色不存在")
        workspace_id = voice.workspace_id
        label = voice.name
    else:
        if not workspace_id:
            raise VoiceError("需要指定工作区")
        label = engine_voice or engine
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="tts",
        payload={
            "voice_id": voice_id,
            "project_id": project_id,
            "text": text[:200],
            "engine": engine,
            "engine_voice": engine_voice,
            "provider_profile_id": provider_profile_id,
            "engine_model": engine_model,
        },
        message=f"合成《{label}》配音中",
    )
    job_id = job.id
    dispatch_job(
        db,
        job,
        lambda: _run_synthesis(
            job_id,
            voice_id,
            text,
            project_id,
            engine,
            engine_voice,
            speed,
            workspace_id,
            engine_voice_resource,
            provider_profile_id,
            engine_model,
        ),
    )
    return job


def _run_synthesis(
    job_id: str,
    voice_id: str | None,
    text: str,
    project_id: str | None,
    engine: str = "clone",
    engine_voice: str = "",
    speed: float = 1.0,
    workspace_id: str = "",
    engine_voice_resource: str = "",
    provider_profile_id: str | None = None,
    engine_model: str = "",
) -> None:
    """Take an admission slot before touching the database — see run_job_guarded.

    Only the local clone engine takes the slot. A remote engine is an HTTP request that holds no
    model in memory, so queueing it behind the single local slot would serialise work that has
    no reason to be serial.
    """
    args = (
        job_id,
        voice_id,
        text,
        project_id,
        engine,
        engine_voice,
        speed,
        workspace_id,
        engine_voice_resource,
        provider_profile_id,
        engine_model,
    )
    if engine == "clone":
        with TTS_SLOTS:
            run_job_guarded(job_id, lambda: _run_synthesis_body(*args), what="配音")
    else:
        run_job_guarded(job_id, lambda: _run_synthesis_body(*args), what="配音")


def _run_synthesis_body(
    job_id: str,
    voice_id: str | None,
    text: str,
    project_id: str | None,
    engine: str = "clone",
    engine_voice: str = "",
    speed: float = 1.0,
    workspace_id: str = "",
    engine_voice_resource: str = "",
    provider_profile_id: str | None = None,
    engine_model: str = "",
) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            voice = db.get(Voice, voice_id) if engine == "clone" else None
            if engine == "clone" and voice is None:
                raise VoiceError("音色不存在")
            job.status = "running"
            job.progress = 0.2
            job.message = f"合成《{voice.name if voice else (engine_voice or engine)}》配音中"
            emit_job_event(db, job.id, "job.running", {})
            db.commit()

            if engine != "clone":
                _synthesize_remote(
                    db, job, engine, engine_voice, text, speed,
                    workspace_id=workspace_id or job.workspace_id, project_id=project_id,
                    voice_resource=engine_voice_resource,
                    provider_profile_id=provider_profile_id,
                    model_override=engine_model,
                )
                return

            ref = reference_path(voice)
            if not ref.is_file():
                raise VoiceError("音色参考音频缺失")
            from app.domain import tts_config

            cfg = tts_config.get()
            engine = cfg.engine
            engine_module = "fish_speech" if engine == "fish-speech" else "f5_tts"
            python = resolve_tts_python(engine_module)  # real engine if installed, else placeholder fallback
            worker_env = {**os.environ, "HF_ENDPOINT": cfg.hf_endpoint}
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
                    [python, str(WORKER_PATH), str(out_wav)], input=json.dumps(request),
                    capture_output=True, text=True, timeout=TTS_TIMEOUT_SECONDS, env=worker_env,
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
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.message = "配音生成失败"
                job.error = str(exc)[:600]
                emit_job_event(db, job.id, "job.failed", {})
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


def _synthesize_remote(
    db,
    job,
    engine: str,
    engine_voice: str,
    text: str,
    speed: float,
    *,
    workspace_id: str,
    project_id: str | None,
    voice_resource: str = "",
    provider_profile_id: str | None = None,
    model_override: str = "",
) -> None:
    """Synthesise through a remote engine and register the result, mirroring the clone path.

    No reference clip and no local model, so none of the worker-subprocess machinery applies —
    but the outcome has to look identical to the caller: an audio asset on the job's result.
    """
    from app.audio.tts_providers import SpeechRequest, build_remote_provider
    from app.domain.providers import resolve_profile

    # The profile carries base_url too. Reading only the key would send a proxy user's request
    # to api.openai.com with a key that is not valid there — a 401 with no hint as to why.
    profile = resolve_profile(db, engine, provider_profile_id)
    api_key = (profile.api_key if profile else None) or ""
    model = model_override or voice_resource or ((profile.default_model if profile else "") or "")
    provider = build_remote_provider(
        engine,
        api_key=api_key,
        voice=engine_voice,
        model=model,
        base_url=(profile.base_url if profile else "") or "",
    )
    with tempfile.TemporaryDirectory(prefix="mibu-tts-") as tmp:
        # 火山与 Edge 产出 mp3;其余(OpenAI 家族)按请求要的 wav 落盘。
        out = Path(tmp) / ("speech.mp3" if engine in {"volcano", "edge"} else "speech.wav")
        provider.synthesize(SpeechRequest(text=text, voice=engine_voice, speed=speed), out)
        job.progress = 0.85
        db.commit()
        asset = register_file_asset(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            source_path=out,
            name=f"{engine_voice or provider.label} · 配音",
            source="tts",
        )
    job = db.get(Job, job.id)
    job.status = "succeeded"
    job.progress = 1.0
    job.message = "配音已生成"
    job.result = {"asset_id": asset.id, "engine": engine}
    emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
    db.commit()


def start_podcast(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    text: str = "",
    topic: str = "",
    mode: str = "summarize",
    speakers: list[str] | None = None,
    speed: float = 1.0,
    provider_profile_id: str | None = None,
) -> Job:
    """Queue a 火山 podcast job: two voices reading or discussing the given material.

    Separate from start_synthesis because it is a different product with a different
    credential and a different shape of request — one call produces a whole dialogue, not one
    utterance in a chosen voice.
    """
    from app.audio.podcast import Action

    actions = {"summarize": Action.SUMMARIZE, "read": Action.READ, "research": Action.RESEARCH}
    if mode not in actions:
        raise VoiceError(f"未知的播客模式:{mode}")
    if not workspace_id:
        raise VoiceError("播客需要指定工作区")

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="podcast",
        payload={
            "project_id": project_id,
            "mode": mode,
            "speakers": speakers or [],
            "text": text[:500],
            "topic": topic,
            "provider_profile_id": provider_profile_id,
        },
        message="生成播客中",
    )
    job_id = job.id
    action = actions[mode]
    dispatch_job(
        db,
        job,
        lambda: run_job_guarded(
            job_id,
            lambda: _run_podcast_body(
                job_id,
                workspace_id,
                project_id,
                text,
                topic,
                action,
                speakers or [],
                speed,
                provider_profile_id,
            ),
            what="播客",
        ),
    )
    return job


def _run_podcast_body(
    job_id: str,
    workspace_id: str,
    project_id: str | None,
    text: str,
    topic: str,
    action: int,
    speakers: list[str],
    speed: float,
    provider_profile_id: str | None = None,
) -> None:
    from app.audio.podcast import synthesize_podcast
    from app.domain.providers import profile_extra, resolve_profile

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        job.progress = 0.2
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        profile = resolve_profile(db, "volcano-podcast", provider_profile_id)
        # The token lives in api_key and the appid in extra — the podcast socket takes both,
        # and neither is the v3 speech API Key.
        token = (profile.api_key if profile else None) or ""
        appid = profile_extra(db, "volcano-podcast", "appid")

        with tempfile.TemporaryDirectory(prefix="mibu-podcast-") as tmp:
            out = Path(tmp) / "podcast.mp3"
            result = synthesize_podcast(
                appid,
                token,
                action=action,
                input_text=text,
                prompt_text=topic,
                speakers=speakers,
                speed=speed,
                out_path=out,
            )
            job = db.get(Job, job_id)
            job.progress = 0.85
            db.commit()
            asset = register_file_asset(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                source_path=out,
                name="播客对话",
                source="podcast",
            )

        job = db.get(Job, job_id)
        job.status = "succeeded"
        job.progress = 1.0
        job.message = "播客已生成"
        # The dialogue text is returned without timings, and inventing them from character
        # counts would produce subtitles that drift audibly. Callers that need a timed
        # transcript can run the normal 转写 over the generated audio, which measures them.
        job.result = {"asset_id": asset.id, "texts": result.texts}
        emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
        db.commit()
