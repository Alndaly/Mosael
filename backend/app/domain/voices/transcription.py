"""素材转写领域流程。

本 Module 负责抽取音轨、选择已安装的 ASR 引擎、调用隔离 worker，并把词级结果装配成 Transcript。
模型加载与依赖探测属于 ``ai.runtime``；这里不重复实现运行时判断。
"""
from __future__ import annotations

import json
import logging
import threading
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.runtime import asr_models
from app.core.config import settings
from app.core.text import blame_line
from app.core.db import SessionLocal
from app.domain.jobs import ASR_SLOTS, run_job_guarded, say
from app.db.models import Asset, Job
from app.domain.jobs import create_job, dispatch_job, emit_job_event
from app.domain.transcripts.operations import SegmentIn, TokenIn, attach_transcript
from app.media.paths import resolve_key
from app.media.probe import probe_has_audio
from app.core.child_process import run_logged

logger = logging.getLogger(__name__)

# worker 住在 ai/runtime(它是"在这台机器上跑模型"的那一层),这个文件是领域流程 —— 不同目录。
# **从 runtime 那边取,而不是在这里拼路径**:那个模块自己知道 worker 在哪,而打包检查
# (test_frozen_build_is_not_a_python_interpreter)也是顺着 `__file__.with_name` 去发现
# "哪些脚本要被当文件打开"的 —— 在这里另拼一份,它就会去找一个不存在的路径。
WORKER_PATH = asr_models.WORKER_PATH
ASR_TIMEOUT_SECONDS = 3600


class ASRError(RuntimeError):
    pass


def resolve_transcription_runtime(language: str = "") -> tuple[str, str]:  # noqa: ARG001 — 语言不选引擎,见下
    """(解释器路径, 引擎)。探测与缓存都在 asr_models —— **这件事只有一份实现**。

    此前这里自己又探测了一遍,和 asr_models 那份各带一份缓存。两份实现意味着两个答案:托管 venv
    加进了那一份、漏了这一份,于是模型页显示「已安装」而一点转写就报"没有运行环境"。

    ## 语言不决定**引擎**,只决定**模型**

    FunASR 不是中文引擎 —— 它的 SenseVoice 系列按官方说明支持 50+ 种语言。是我们此前只装了一套
    中文预设(paraformer-zh),于是"英文素材转出一堆错字"看起来像 FunASR 的毛病,其实是拿错了模型。

    所以这里只管"哪个引擎装好了",语言留给 transcribe_with_engine 去挑模型(见那里的 funasr_model)。
    曾经在这里写过「非中文一律走 WhisperX」—— 那是把"我们装的是中文预设"错记成了"FunASR 只能中文",
    等于把一个包装选择固化成了引擎的属性。
    """
    from app.ai.runtime.asr_models import resolve_engine_python

    preferred = settings.asr_provider.strip().lower()
    engines = ["funasr", "whisperx"] if preferred in ("", "auto") else [preferred]
    for engine in engines:
        python_executable = resolve_engine_python(engine)
        if python_executable:
            return python_executable, engine
    raise ASRError(
        # 纯文本,不要 markdown —— 这句话会原样显示在界面上,星号只会以星号的样子出现。
        "缺的是运行环境,不是模型:模型权重已经下好的话不用再下一遍,"
        "但还没有任何 Python 解释器装了 funasr 或 whisperx。"
        "去设置的「转写模型」那一页点「安装运行环境」,装一次就好。"
    )


def _extract_audio(source: Path, target: Path) -> None:
    result = run_logged(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn",
         "-ac", "1", "-ar", "16000", "-f", "wav", str(target)],
        capture_output=True,
        text=True,
        timeout=600, what="音频提取")
    if result.returncode != 0:
        raise ASRError(f"音频提取失败:{blame_line(result.stderr, fallback='ffmpeg 没有说明原因')}")


def transcribe_with_engine(
    audio_path: Path,
    python_executable: str,
    engine_id: str,
    language: str = "",
) -> dict:
    request: dict[str, Any] = {
        "audio_path": str(audio_path),
        # Worker protocol keeps the historical key for compatibility; inside this Module the
        # value is an ASR engine id, not a commercial provider connection.
        "provider": engine_id,
        "whisper_model": settings.asr_whisper_model,
        # 空 = 让引擎自己检测(两个引擎都会:WhisperX 自带检测,SenseVoice 收 language="auto")。
        # 现在 FunASR 只有多语种这一个模型,所以"没说"就是"自动",不再有第二种含义。
        "language": language or "",
    }
    if engine_id == "funasr":
        request["funasr_model"] = FUNASR_MODEL
    return _invoke_asr_worker(audio_path, python_executable, request)


#: FunASR 用的识别模型。**只有一个,而且是多语种的** ——「支持超过 50 种语言」(官方说明)。
#: 曾经这里按语言在「中文预设 / 多语种」之间挑,那是把"我们当初只装了中文权重"当成了产品结构:
#: 用户于是要在两个 FunASR 之间选一个,而这个选择本不该存在。
FUNASR_MODEL = "iic/SenseVoiceSmall"


def _invoke_asr_worker(audio_path: Path, python_executable: str, request: dict[str, Any]) -> dict:
    # Results travel via a file: funasr and hub downloads write progress bars
    # straight to stdout, which would corrupt an inline JSON pipe.
    output_path = audio_path.with_name("asr-result.json")
    result = run_logged(
        [python_executable, str(WORKER_PATH), str(output_path)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=ASR_TIMEOUT_SECONDS,
        what="转写 worker",
    )
    if result.returncode != 0:
        engine_id = str(request.get("provider") or "unknown")
        raise ASRError(
            f"转写失败({engine_id}):{blame_line(result.stderr, fallback='子进程没有留下原因')}"
        )
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # **这一处回显原文,不挑行**:读不出 JSON 时想看的就是"它到底吐了什么",而
        # blame_line 挑的是"哪一行像错误" —— 一段截断的 JSON 里一行都不像,反倒会说成
        # 「输出是空的」,而它并不空。和插件那处同一个判断(见 plugins/runtime)。
        # worker 真打了 traceback 时,异常行本来就在这段原文的末尾。
        raw = (result.stdout or "").strip()
        raise ASRError(f"转写输出无法解析:{raw[-300:] if raw else '子进程什么都没输出'}") from exc


def parse_transcript_segments(segments: list[dict]) -> list[SegmentIn]:
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


def _mirror_model_download_progress(job_id: str, engine_id: str) -> threading.Event:
    """While a transcribe is running, if its model isn't installed yet, poll the
    download and map it onto job progress 0.25→0.9. Returns a stop Event."""
    from app.ai.runtime import asr_models

    stop = threading.Event()
    entry = asr_models.entry_for_transcribe(engine_id)
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
                say(job, "jobMsg_asrDownloading", percent=int(fraction * 100))
                db.commit()

    threading.Thread(target=_loop, daemon=True).start()
    return stop


def start_transcription(db: Session, asset_id: str, *, created_by: str | None, language: str = "") -> Job:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ASRError("Asset not found")
    if asset.kind not in ("video", "audio"):
        raise ASRError("只有视频或音频素材可以转写")
    if not asset.file_key:
        raise ASRError("素材没有本地文件")
    # **没有音轨就当场说** —— 屏幕录制、无声的生成视频本来就没有音频,这是正常输入不是异常。
    # 不挡的话它会一路走到 ffmpeg:提取命令带 `-vn`,源里又没有音频,于是输出一条流都没有,
    # 用户看到的是「Output file does not contain any stream … Invalid argument」。
    # 判据项目里早就有(渲染路径一直在用),只是这条路没用它。
    #
    # 挡在**建任务之前**:起一个注定失败的任务,等于把这句话藏进任务列表里让他自己去翻。
    source = resolve_key(asset.file_key)
    if source.exists() and not probe_has_audio(source):
        raise ASRError(f"「{asset.name}」没有音轨,没有可以转写的声音。")
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="transcribe",
        payload={"asset_id": asset_id, "language": (language or "").strip(), "subject": asset.name},
        created_by=created_by,
        message="jobMsg_asrQueued",
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
            language = str((job.payload or {}).get("language") or "")
            python_executable, engine_id = resolve_transcription_runtime(language)
            job.status = "running"
            say(job, "jobMsg_asrRunning", provider=engine_id)
            job.progress = 0.1
            emit_job_event(db, job.id, "job.running", {"provider": engine_id})
            db.commit()
            logger.info("transcription job %s: engine=%s asset=%s", job_id, engine_id, asset_id)

            asset = db.get(Asset, asset_id)
            source = resolve_key(asset.file_key)
            with tempfile.TemporaryDirectory(prefix="open-studio-asr-") as tmp:
                wav = Path(tmp) / "audio.wav"
                _extract_audio(source, wav)
                job.progress = 0.25
                db.commit()
                # First transcribe on a machine downloads ~2GB of models inside the
                # library — surface that as job progress instead of a frozen 25%.
                stop = _mirror_model_download_progress(job_id, engine_id)
                try:
                    output = transcribe_with_engine(wav, python_executable, engine_id, language)
                finally:
                    stop.set()

            segments = parse_transcript_segments(output.get("segments") or [])
            if not segments:
                raise ASRError("转写结果为空")
            transcript = attach_transcript(
                db,
                asset_id=asset_id,
                language=str(output.get("language") or "zh"),
                segments=segments,
                source=f"asr:{engine_id}",
            )
            job = db.get(Job, job_id)
            job.status = "succeeded"
            job.progress = 1.0
            say(job, "jobMsg_asrDone")
            job.result = {"transcript_id": transcript.id, "segments": len(segments)}
            emit_job_event(db, job.id, "job.succeeded", {"transcript_id": transcript.id})
            db.commit()
            logger.info("transcription job %s succeeded: %d segments (%s)", job_id, len(segments), engine_id)
        except Exception as exc:  # noqa: BLE001 — worker thread must record, not die
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                say(job, "jobMsg_asrFailed")
                job.error = str(exc)[:800]
                emit_job_event(db, job.id, "job.failed", {})
                db.commit()
            logger.warning("transcription job %s failed: %s", job_id, exc)


__all__ = ["ASRError", "start_transcription", "resolve_transcription_runtime", "parse_transcript_segments", "transcribe_with_engine"]
