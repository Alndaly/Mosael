"""素材转写领域流程。

本 Module 负责抽取音轨、挑出这一次用哪一家转写、调用它,并把词级结果装配成 Transcript。
模型加载与依赖探测属于 ``ai.runtime``;这里不重复实现运行时判断。

转写是一项**宿主能力**(ADR 0032 第三步):本机的 FunASR / WhisperX 是内置提供方(`builtin:funasr` /
`builtin:whisperx`),认领 `transcription` 的插件连接和它们并列。挑哪一家走能力表那一份挑法(`capabilities.pick`):
素材库、剪辑页、工作流节点、听写点名的是提供方 id;不点名按这个人的默认,没定默认用第一个装好了运行环境的本机引擎。
此前引擎只能在部署配置 `asr_provider` 和节点里写死的 `auto / funasr / whisperx` 之间挑,插件插不进来。

**契约**(认领 `transcription` 的工具是一个普通工具,ADR 0033;智能体、工作流也能直接调它):

- 入:`file` 是一段声音(`format: asset`,`x-media` 含 audio 与 video,`x-audio: speech` —— 宿主先抽成 16k 单声道 wav
  再给),可选 `filename`(原素材名)、`language`(语言代码,空 = 自己判);
- 出:`{"language": "zh", "segments": [{"start": 秒, "end": 秒, "text": "…", "speaker": 可选,
  "words": 可选 [{"start", "end", "word"}]}]}`;
- 进度、取消和别的流式工具同一套。
"""
from __future__ import annotations

import logging
import threading
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.runtime import asr_daemon, asr_models
from app.core.config import settings
from app.core.i18n import LocalizedError, tr
from app.core.text import blame_line
from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.domain.jobs import ASR_SLOTS, blame, finish_job, run_job_guarded, say
from app.db.models import Asset, Job
from app.domain.jobs import create_job, dispatch_job, emit_job_event
from app.domain.transcripts.operations import SegmentIn, TokenIn, attach_transcript
from app.media.paths import resolve_key
from app.media.probe import probe_has_audio, probe_media
from app.core.child_process import run_logged
from app.domain import capabilities
from app.domain.capabilities import Builtin, Capability, CapabilityUnavailable, Provider
from app.domain.plugins.manifest import TRANSCRIPTION

logger = logging.getLogger(__name__)

ASR_TIMEOUT_SECONDS = 3600


class ASRError(LocalizedError, RuntimeError):
    """转写的领域错误。带文案 key(`asrErr_*`),按读的人的语言翻(见 core/i18n)。"""


BUILTIN_PREFIX = "builtin:"
#: 本机引擎,按不定默认时的先后排:FunASR(SenseVoice,多语种)在前。
LOCAL_ENGINES = {"funasr": "asrEngine_funasr", "whisperx": "asrEngine_whisperx"}


class TranscriptionProviderUnavailable(CapabilityUnavailable, ASRError):
    """挑不出能用的转写实现。仍是 ASRError —— 转写的调用方照样接得住。"""


def _runtime_ready(engine: str):
    """本机引擎缺的是**运行环境**(装了它的 Python),不是模型 —— 权重首次转写时自己下。探测只有一份实现,
    在 asr_models(此前这里自己又探了一遍,两份缓存两个答案:模型页说「已安装」,一转写就报没有运行环境)。
    **不会自己去装**几 GB 的依赖:缺了就说清楚去哪装。"""

    def missing(_db: Session, _owner: str | None) -> tuple[str, ...]:
        return () if asr_models.resolve_engine_python(engine) else (tr("asrHint_runtimeMissing", engine=engine),)

    return missing


CAPABILITY = Capability(
    name=TRANSCRIPTION,
    label_key="capability_transcription",
    description_key="capability_transcription_desc",
    error=TranscriptionProviderUnavailable,
    none_key="asrErr_noRuntime",
    unknown_key="asrErr_unsupportedEngine",
    incomplete_key="asrErr_providerNotReady",
    builtins=tuple(Builtin(id=f"{BUILTIN_PREFIX}{engine}", name_key=label_key, ready=_runtime_ready(engine))
                   for engine, label_key in LOCAL_ENGINES.items()),
    #: 声音交给插件(多半是云端)必须是他自己定过的,不替他挑。
    auto_single=False,
)


class LocalTranscriber:
    """本机引擎:常驻 worker 里跑 FunASR / WhisperX。

    ## 语言不决定**引擎**,只决定**模型**

    FunASR 不是中文引擎 —— 它的 SenseVoice 系列按官方说明支持 50+ 种语言。是我们此前只装了一套
    中文预设(paraformer-zh),于是"英文素材转出一堆错字"看起来像 FunASR 的毛病,其实是拿错了模型。
    所以挑引擎不看语言,语言交给 transcribe_with_engine 传给模型。
    """

    builtin = True

    def __init__(self, engine: str) -> None:
        self.engine_id = engine
        self.name = tr(LOCAL_ENGINES[engine])

    def transcribe(self, wav: Path, language: str = "") -> dict:
        python_executable = asr_models.resolve_engine_python(self.engine_id)
        if not python_executable:
            raise ASRError("asrErr_engineRuntimeMissing", engine=self.engine_id)
        return transcribe_with_engine(wav, python_executable, self.engine_id, language)


class PluginTranscriber:
    """认领 `transcription` 的插件连接。协议见模块说明;交回的分段在这里验过,形状不对当场说。"""

    builtin = False

    def __init__(self, provider: Provider) -> None:
        self.engine_id = provider.id
        self.name = provider.name
        self._provider = provider

    def transcribe(self, wav: Path, language: str = "") -> dict:
        from app.domain.plugins.errors import PluginDomainError
        from app.domain.plugins.runtime import PluginRuntimeError
        from app.domain.plugins.tools import invoke_host, quiet_hooks

        heard: dict[str, Any] = {}

        def collect(output: dict[str, Any], _scratch: Path) -> dict[str, Any]:
            segments = output.get("segments")
            try:
                if not isinstance(segments, list):
                    raise TypeError("segments")
                parse_transcript_segments(segments)
            except (KeyError, TypeError, ValueError) as exc:
                raise ASRError("asrErr_pluginBadOutput", plugin=self.name, detail=str(exc)[:200]) from exc
            heard.update(language=str(output.get("language") or language or ""), segments=segments)
            return {"language": heard["language"], "segments": len(segments)}

        try:
            with unit_of_work() as db:
                invoke_host(db, self._provider.id, TRANSCRIPTION, {"filename": wav.name, "language": language},
                            files={"file": wav}, collect=collect, hooks=quiet_hooks())
        except (PluginDomainError, PluginRuntimeError) as exc:
            raise ASRError("asrErr_pluginFailed", plugin=self.name, detail=str(exc)[:500]) from exc
        return heard


def transcriber(db: Session, owner_user_id: str | None, provider_id: str | None) -> LocalTranscriber | PluginTranscriber:
    """这一次用哪一家转写:点名的,或按这个人的默认挑。挑不出来抛一句说清下一步的话。"""
    provider = capabilities.pick(db, owner_user_id, CAPABILITY, provider_id or None)
    if provider.builtin:
        return LocalTranscriber(provider.id.removeprefix(BUILTIN_PREFIX))
    return PluginTranscriber(provider)


def register_uses() -> None:
    """宿主界面上用到转写的入口(ADR 0032 §4)。工作流节点由注册表现扫。"""
    from app.core.i18n import fragment
    from app.domain.capabilities import Use, register_use

    register_use(Use(TRANSCRIPTION, "app", fragment("capUse_assetTranscribe")))
    register_use(Use(TRANSCRIPTION, "app", fragment("capUse_dictation")))


def _extract_audio(source: Path, target: Path) -> None:
    result = run_logged(
        [settings.ffmpeg, "-y", "-v", "error", "-i", str(source), "-vn",
         "-ac", "1", "-ar", "16000", "-f", "wav", str(target)],
        capture_output=True,
        text=True,
        timeout=600, what="音频提取")
    if result.returncode != 0:
        # ffmpeg 的原文不翻;说不出原因时给一句翻得动的话。
        reason = blame_line(result.stderr) or LocalizedError("voiceErr_ffmpegNoReason")
        raise ASRError("asrErr_audioExtractFailed", detail=reason)


#: 一段听写最长多久。语音输入是"说一句话",不是"传一段素材" —— 上限存在的意义是让越界
#: 当场被拒,而不是让一段四十分钟的录音悄悄占住那个唯一的识别名额。
DICTATION_MAX_SECONDS = 120.0


class DictationTooLong(ASRError):
    """说得太长了。单独一个类型,因为它该变成 4xx 而不是 5xx —— 是输入的问题。"""


def transcribe_clip(source: Path, *, owner_user_id: str | None, language: str = "", engine: str = "") -> str:
    """把一小段录音转成一句话。**不入库、不建任务。**

    和「转写素材」是两件事,不该走同一条路:后者的产出是一份要留存、要能编辑、要投影回
    时间线的逐字稿,所以它建 job、产出素材、记进任务中心。听写要的只是"用户刚才说了什么",
    说完就用完了 —— 走那条路的话,输入框里每说一句,素材库就多一个 wav 和一条转写记录。

    识别本身仍然是同一份实现(同一份挑法、同一个 transcriber),只是**产物的归属不同**。
    """
    duration = float(probe_media(source).get("duration") or 0.0)
    if duration > DICTATION_MAX_SECONDS:
        raise DictationTooLong(
            "asrErr_dictationTooLong", seconds=f"{duration:.0f}", limit=f"{DICTATION_MAX_SECONDS:.0f}"
        )
    with SessionLocal() as db:
        chosen = transcriber(db, owner_user_id, engine)
    with tempfile.TemporaryDirectory(prefix="mosael-dictate-") as tmp:
        # 引擎要 16k 单声道 wav;浏览器给的是 webm/opus 之类,统一在这儿转。
        wav = Path(tmp) / "clip.wav"
        _extract_audio(source, wav)
        result = chosen.transcribe(wav, language)
    # 分段是给逐字稿用的结构;听写要的是一句话。**中间不补空格** —— 中文里那是错的,
    # 而引擎给的分段边界本来就落在停顿处,拼起来就是他说的那句。
    return "".join(str(one.get("text") or "").strip() for one in (result.get("segments") or [])).strip()


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
    """把一次识别交给常驻 worker。

    **常驻的理由是不要每次都重读一遍模型** —— 见 ai/runtime/asr_daemon。此前这里每次识别
    起一个新进程,权重跟着进程一起生一起灭:一段十秒的音频,绝大部分时间花在加载上。

    结果不再走临时文件。那个做法是为了绕开 stdout 上的进度条噪声,而哨兵前缀把同一个问题
    解得更直接(见 workers/asr_protocol);文件那条路也带不了进度,常驻之后更是每次请求都得
    另约一个路径。

    引擎按 `provider` 分池:一个进程只抱一套权重,funasr 和 whisperx 不会挤在一起。
    """
    engine_id = str(request.get("provider") or "funasr")
    try:
        event = asr_daemon.pool().request(
            engine_id,
            python_executable,
            request,
            timeout=ASR_TIMEOUT_SECONDS,
        )
    except RuntimeError as exc:
        # 常驻进程把失败**报回来**而不是退出,所以这里拿到的就是它自己的那句话;进程真死了
        # (加载时被 OOM 杀掉之类)由池子转成一句明确的错误,不会变成"一直没有回音"。
        raise ASRError("asrErr_engineFailed", engine=engine_id, detail=str(exc)) from exc
    return {"language": event.get("language", ""), "segments": event.get("segments") or []}


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

    stop = threading.Event()
    entry = asr_models.entry_for_transcribe(engine_id)
    if entry is None or asr_models.is_installed(entry):
        return stop  # nothing to download → leave the job at 0.25 during inference

    def _loop() -> None:
        while not stop.wait(2.0):
            fraction = asr_models.measure_fraction(entry)
            with unit_of_work() as db:
                job = db.get(Job, job_id)
                if job is None or job.status != "running":
                    return
                job.progress = round(0.25 + fraction * 0.6, 4)  # 0.25..0.85
                say(job, "jobMsg_asrDownloading", percent=int(fraction * 100))

    threading.Thread(target=_loop, daemon=True).start()
    return stop


def start_transcription(
    db: Session,
    asset_id: str,
    *,
    created_by: str | None,
    language: str = "",
    engine: str = "",
) -> Job:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ASRError("asrErr_assetNotFound")
    if asset.kind not in ("video", "audio"):
        raise ASRError("asrErr_notMedia")
    if not asset.file_key:
        raise ASRError("asrErr_assetNoFile")
    # **没有音轨就当场说** —— 屏幕录制、无声的生成视频本来就没有音频,这是正常输入不是异常。
    # 不挡的话它会一路走到 ffmpeg:提取命令带 `-vn`,源里又没有音频,于是输出一条流都没有,
    # 用户看到的是「Output file does not contain any stream … Invalid argument」。
    # 判据项目里早就有(渲染路径一直在用),只是这条路没用它。
    #
    # 挡在**建任务之前**:起一个注定失败的任务,等于把这句话藏进任务列表里让他自己去翻。
    source = resolve_key(asset.file_key)
    if source.exists() and not probe_has_audio(source):
        raise ASRError("asrErr_noAudioTrack", name=asset.name)
    #: 点名的那一家在建任务之前就认一遍:点了一个不存在的引擎,不该排进队列再失败。配没配好(运行环境、凭据)
    #: 留给任务去说 —— 那是任务的结果,记在任务上。
    if engine and not any(one.id == engine for one in capabilities.providers(db, created_by, CAPABILITY)):
        raise TranscriptionProviderUnavailable(CAPABILITY.unknown_key, name=engine)
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="transcribe",
        payload={
            "asset_id": asset_id,
            "language": (language or "").strip(),
            #: 提供方 id(`builtin:funasr`、插件连接 id);空 = 运行时按这个人的默认挑。
            "provider": (engine or "").strip(),
            "subject": asset.name,
        },
        created_by=created_by,
        message="jobMsg_asrQueued",
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run_transcription(job_id, asset_id))
    return job


def _run_transcription(job_id: str, asset_id: str) -> None:
    """Take an admission slot before touching the database — see run_job_guarded."""
    with ASR_SLOTS:
        run_job_guarded(job_id, lambda: _run_transcription_body(job_id, asset_id), what="转写")


def _run_transcription_body(job_id: str, asset_id: str) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            language = str((job.payload or {}).get("language") or "")
            chosen = transcriber(db, job.created_by, str((job.payload or {}).get("provider") or ""))
            engine_id = chosen.engine_id
            # 状态经 finish_job 写:排队时就被取消的不被写回 running,转完时不盖掉中途的取消
            # (工作流取消会级联到这里,而手里这份 Job 是开始时读的)。
            if not finish_job(db, job, status="running", progress=0.1):
                return
            say(job, "jobMsg_asrRunning", provider=chosen.name)
            emit_job_event(db, job.id, "job.running", {"provider": engine_id})
            # 「在转」先落库:转写要一阵,界面要马上看得到;也把 finish_job 拿的写锁放掉。
            db.commit()
            logger.info("transcription job %s: engine=%s asset=%s", job_id, engine_id, asset_id)

            asset = db.get(Asset, asset_id)
            source = resolve_key(asset.file_key)
            with tempfile.TemporaryDirectory(prefix="mosael-asr-") as tmp:
                wav = Path(tmp) / "audio.wav"
                _extract_audio(source, wav)
                job.progress = 0.25
                # 进度落库再去转:第一次转写要在库里下 2GB 模型,这一笔不落,界面就停在 10%。
                db.commit()
                # First transcribe on a machine downloads ~2GB of models inside the
                # library — surface that as job progress instead of a frozen 25%.
                stop = _mirror_model_download_progress(job_id, engine_id) if chosen.builtin else threading.Event()
                try:
                    output = chosen.transcribe(wav, language)
                finally:
                    stop.set()

            segments = parse_transcript_segments(output.get("segments") or [])
            if not segments:
                raise ASRError("asrErr_emptyResult")
            transcript = attach_transcript(
                db,
                asset_id=asset_id,
                #: 引擎没报语种:有请求指定的就用它,否则记空(认不出)—— 不回落成 "zh"(见 workers/asr 的说明)。
                language=str(output.get("language") or language or ""),
                segments=segments,
                source=f"asr:{engine_id}",
            )
            job = db.get(Job, job_id)
            result = {"transcript_id": transcript.id, "segments": len(segments)}
            if finish_job(db, job, status="succeeded", progress=1.0, result=result):
                say(job, "jobMsg_asrDone")
                emit_job_event(db, job.id, "job.succeeded", {"transcript_id": transcript.id})
            logger.info("transcription job %s succeeded: %d segments (%s)", job_id, len(segments), engine_id)
        except Exception as exc:  # noqa: BLE001 — worker thread must record, not die
            db.rollback()
            job = db.get(Job, job_id)
            #: 失败原因存 key + 参数,接口按读的人的语言翻(见 jobs.blame)。
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_asrFailed")
                emit_job_event(db, job.id, "job.failed", {})
            logger.warning("transcription job %s failed: %s", job_id, exc)


__all__ = [
    "ASRError",
    "BUILTIN_PREFIX",
    "CAPABILITY",
    "LocalTranscriber",
    "PluginTranscriber",
    "TranscriptionProviderUnavailable",
    "parse_transcript_segments",
    "register_uses",
    "start_transcription",
    "transcribe_with_engine",
    "transcriber",
]
