"""Voice-clone domain: manage cloned voices (reference clip + transcript) and
synthesize new speech in a voice via the external TTS worker. Synthesized speech
is registered as a normal audio asset (with waveform), so it can be dragged onto
the timeline like any other clip.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import provider_models
from app.domain.usage import billable
from app.audio import tts_daemon, tts_models
from app.audio.tts_models import WORKER_PATH
from app.core.db import SessionLocal
from app.domain.jobs import TTS_SLOTS, run_job_guarded
from app.db.models import Asset, Job, Voice
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job, dispatch_job, emit_job_event
from app.media.paths import resolve_key, voice_dir, voice_key
from app.media.probe import probe_media
from app.core.child_process import run_logged
from app.core.text import strip_ansi

logger = logging.getLogger(__name__)

REFERENCE_MAX_SECONDS = 15
#: 零样本克隆靠这几秒把音色条件化。给不够就条件化不起来,模型会一路漫游到 token 上限,
#: 出来是几十秒的胡话 —— 用户实测:2.6 秒的参考,换来四十多秒听不懂的东西。
#: 这个下限本来就写在界面提示里(「5–15 秒」),只是从来没有人执行它。
REFERENCE_MIN_SECONDS = 5.0

REFERENCE_TOO_SHORT_HINT = (
    f"参考音频太短(只有 {{actual:.1f}} 秒)。零样本克隆要听够才能学到音色,"
    f"请给 {REFERENCE_MIN_SECONDS:.0f}–{REFERENCE_MAX_SECONDS} 秒连续清晰的人声 —— "
    "太短的话合成出来会是一段听不懂的声音。"
)


def check_reference_duration(seconds: float) -> None:
    """够不够长。**在建音色之前问** —— 一条注定合成不出东西的音色会出现在音色库里,
    像个能用的选项;而它的代价要等到一次十分钟的合成之后才显现。"""
    if seconds < REFERENCE_MIN_SECONDS:
        raise VoiceError(REFERENCE_TOO_SHORT_HINT.format(actual=seconds))
TTS_TIMEOUT_SECONDS = 1200


class VoiceError(RuntimeError):
    pass


#: 纯文本,不要 markdown —— 这几句会原样显示在界面上。
_NO_RUNTIME = (
    "{label} 还没有运行环境:没有任何 Python 解释器装了它。"
    "去设置的「声音克隆」那一页点「下载」,装一次就好;"
    "想马上出声可以先在上面的引擎里选「Edge 免费在线合成」,它不需要安装。"
)
_NO_WEIGHTS = (
    "{label} 的模型权重还没下好,现在合成不出声音。"
    "去设置的「声音克隆」那一页点「下载」补上 —— "
    "这里不会替你下:那是几个 GB 的事,该由你决定什么时候开始。"
)


def resolve_clone_engine(requested: str = "") -> str:
    """这一次用哪个本地引擎。

    设置页那个是**默认**,不是唯一 —— 配音面板每次生成都可能想换一个(F5 快、Fish 支持情感
    标签),而此前想换只能跑去设置页改全局。请求带了就用请求的,没带才回落到默认。
    """
    from app.domain import tts_config

    engine = (requested or "").strip() or tts_config.get().engine
    if engine not in {item.id for item in tts_models.CATALOG}:
        raise VoiceError(f"不认识的本地引擎:{engine}")
    return engine


def explain_worker_failure(stderr: str) -> str:
    """把 worker 的 traceback 变成界面上那**一句**话。

    用户截图里那张卡片是四行文件路径 + 一排 `^^^^`(终端里指向出错列的记号,换到浏览器里
    只是噪声)+ 最后才是真正有用的 `ModuleNotFoundError: No module named 'natsort'`。
    traceback 的最后一行就是异常本身,前面那些是给读代码的人看的,不是给点了「生成配音」的人。

    完整 traceback 仍然进日志 —— 排查要它,界面不要。
    """
    text = strip_ansi(stderr or "").strip()
    if not text:
        return "合成失败,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。"
    last = next((line.strip() for line in reversed(text.splitlines()) if line.strip()), text)
    if "ModuleNotFoundError" in last or "ImportError" in last:
        # 缺依赖是**能行动**的:光扔一个模块名,用户只能去搜。
        return (
            f"{last[:200]} —— 引擎的运行环境不完整。"
            "去设置的「声音克隆」那一页点「下载」,它会把缺的依赖补上。"
        )
    return last[:400]


def _require_local_engine(engine: str) -> None:
    """跑得了**而且**出得了声,才让建任务。

    两件事:解释器能不能 import 这个引擎,以及权重在不在盘上。此前只挡前者 —— 于是权重缺席时
    任务照建,worker 在首次合成里顺手下 2GB:界面上是一个看不出在干嘛、卡几十分钟的任务。
    下载是用户在设置页按「下载」时明确要做的事,不该由一次"生成配音"顺带触发。
    """
    label = next((item.label for item in tts_models.CATALOG if item.id == engine), engine)
    if tts_models.resolve_engine_python(engine) is None:
        raise VoiceError(_NO_RUNTIME.format(label=label))
    if not tts_models.is_installed(engine):
        raise VoiceError(_NO_WEIGHTS.format(label=label))


def _transcode_reference(source: Path, target: Path) -> None:
    """Normalize any uploaded audio/video to 24k mono WAV, capped at 15s."""
    result = run_logged(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "24000",
         "-t", str(REFERENCE_MAX_SECONDS), str(target)],
        capture_output=True, text=True, timeout=300, what="参考音频转码")
    if result.returncode != 0 or not target.exists():
        raise VoiceError(f"参考音频处理失败: {result.stderr[-300:]}")


def create_from_upload(db: Session, *, workspace_id: str, source: Path, name: str, reference_text: str) -> Voice:
    from app.db.models import new_id

    # 时长从**转码之前**的原文件量:转码会截到 15 秒上限,量转码后的等于用我们自己的裁剪
    # 结果去判用户给了多长。
    check_reference_duration(float(probe_media(source).get("duration") or 0.0))
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
    result = run_logged(
        ["ffmpeg", "-y", "-v", "error", "-i", str(resolve_key(asset.file_key)), "-vn",
         "-af", f"aselect='{expr}',asetpts=N/SR/TB", "-ac", "1", "-ar", "24000", str(ref)],
        capture_output=True, text=True, timeout=300, what="说话人片段提取")
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
    created_by: str | None,
    voice_id: str | None = None,
    workspace_id: str = "",
    engine: str = "clone",
    engine_voice: str = "",
    engine_voice_resource: str = "",
    provider_profile_id: str | None = None,
    engine_model: str = "",
    speed: float = 1.0,
    clone_engine: str = "",
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
        # 参考音频够不够长,先查 —— 这是**用户自己的输入**,和这台机器装没装引擎无关,
        # 所以排在引擎检查前面。库里已经有的短音色(下限是后加的)也要挡在这儿,否则它会
        # 安安静静换来一次十分钟的合成和一段听不懂的声音。
        reference = reference_path(voice)
        if reference.is_file():
            check_reference_duration(float(probe_media(reference).get("duration") or 0.0))
        # 本地克隆跑不跑得起来,**建任务之前**就知道:探一次解释器、看一眼权重目录而已。
        # 不挡的话它会一路跑到 worker:导不进引擎就写一段正弦音(用户说的「根本克隆不了」),
        # 权重缺席就顺手下 2GB(用户说的「不该自动开启下载」)。
        clone_engine = resolve_clone_engine(clone_engine)
        _require_local_engine(clone_engine)
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
        created_by=created_by,
        payload={
            "voice_id": voice_id,
            "project_id": project_id,
            "text": text[:200],
            "engine": engine,
            "clone_engine": clone_engine if engine == "clone" else "",
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
            clone_engine,
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
    clone_engine: str = "",
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
        clone_engine,
    )
    if engine == "clone":
        with TTS_SLOTS:
            run_job_guarded(job_id, lambda: _run_synthesis_body(*args), what="配音")
    else:
        run_job_guarded(job_id, lambda: _run_synthesis_body(*args), what="配音")


def _update_progress(job_id: str, event: dict) -> None:
    """把 worker 报的阶段落到任务上。

    **只报它真的知道的**:阶段名 + 一个粗粒度比例。不拿"当前 token / 上限"编细进度 ——
    解码通常远早于上限就停,那条进度会永远走不到头,又是一个答非所问的数字。
    """
    fraction = event.get("fraction")
    message = event.get("message") or ""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return
        if isinstance(fraction, (int, float)):
            job.progress = max(job.progress or 0.0, min(0.95, float(fraction)))
        if message:
            job.message = message
        db.commit()


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
    clone_engine: str = "",
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

            # 用**建任务时**定下的那个引擎:中途有人去设置页改了默认,这一单不该跟着漂。
            engine = clone_engine or tts_config.get().engine
            python = tts_models.resolve_engine_python(engine)
            if python is None:  # 建任务时还在,跑起来时被卸了
                raise VoiceError(_NO_RUNTIME.format(label=engine))
            # env 也只有一份:此前这里手拼 `{**os.environ, "HF_ENDPOINT": …}`,漏了 fish-speech
            # 要的检出目录和权重目录 —— 于是装好了 fish 的机器也照样导不进引擎、照样出占位音。
            worker_env = tts_models._worker_env()
            with tempfile.TemporaryDirectory(prefix="open-studio-tts-") as tmp:
                out_wav = Path(tmp) / "speech.wav"
                request = {
                    "action": "synthesize",
                    "engine": engine,
                    "reference_wav": str(ref),
                    "reference_text": voice.reference_text,
                    "text": text,
                }
                request["output_path"] = str(out_wav)

                # 进度从 worker 一路报回来。此前这里只有一个开头写死的 0.2 —— 用户看到的
                # 「20% 卡了 14 分钟」不是进度慢,是**根本没有进度上报**。
                def report(event: dict) -> None:
                    _update_progress(job_id, event)

                try:
                    result = tts_daemon.pool().request(
                        engine, python, request, on_progress=report, timeout=TTS_TIMEOUT_SECONDS, env=worker_env,
                    )
                except RuntimeError as exc:
                    raise VoiceError(f"语音合成失败:{explain_worker_failure(str(exc))}") from exc
                if not out_wav.exists():
                    raise VoiceError("语音合成失败:worker 报成功却没有产出音频")
                used = result.get("engine", engine)
                job = db.get(Job, job_id)
                job.progress = 0.95
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
            job.message = "配音已生成"
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
    # 这次配音替谁干,job 上记着 —— 后台线程手里只有它(见 Job.created_by)。
    profile = resolve_profile(db, engine, provider_profile_id, user_id=job.created_by)
    api_key = (profile.api_key if profile else None) or ""
    model = model_override or voice_resource or provider_models.model_id_for(db, profile, "tts")
    provider = build_remote_provider(
        engine,
        api_key=api_key,
        voice=engine_voice,
        model=model,
        base_url=(profile.base_url if profile else "") or "",
    )
    with tempfile.TemporaryDirectory(prefix="open-studio-tts-") as tmp:
        # 火山与 Edge 产出 mp3;其余(OpenAI 家族)按请求要的 wav 落盘。
        out = Path(tmp) / ("speech.mp3" if engine in {"volcano", "edge"} else "speech.wav")
        # 语音合成此前一条账都不记。各家 TTS 普遍按**字符**计费,所以计量是字符数而不是 token
        # —— 计量因供应商而异正是 billable 留给调用方的那一半。
        with billable(
            db,
            capability="tts",
            operation="synthesize_speech",
            workspace_id=workspace_id,
            provider=engine,
            model=model,
            provider_profile_id=profile.id if profile else None,
            source_type="job",
            source_id=job.id,
            job_id=job.id,
        ) as call:
            call.meter(characters=len(text), requests=1)
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
    created_by: str | None,
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
        created_by=created_by,
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

        profile = resolve_profile(db, "volcano-podcast", provider_profile_id, user_id=job.created_by)
        # The token lives in api_key and the appid in extra — the podcast socket takes both,
        # and neither is the v3 speech API Key.
        token = (profile.api_key if profile else None) or ""
        appid = profile_extra(db, "volcano-podcast", "appid")

        with tempfile.TemporaryDirectory(prefix="open-studio-podcast-") as tmp:
            out = Path(tmp) / "podcast.mp3"
            with billable(
                db,
                capability="podcast",
                operation="synthesize_podcast",
                workspace_id=workspace_id,
                provider="volcano-podcast",
                provider_profile_id=profile.id if profile else None,
                source_type="job",
                source_id=job_id,
                job_id=job_id,
            ) as call:
                # 播客按输入文本量计费,和 TTS 同一类;说话人数会影响时长,一并记下来。
                call.meter(characters=len(text or topic or ""), speakers=len(speakers or []), requests=1)
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
