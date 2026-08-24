"""Voice-clone domain: manage cloned voices (reference clip + transcript) and
synthesize new speech in a voice via the external TTS worker. Synthesized speech
is registered as a normal audio asset (with waveform), so it can be dragged onto
the timeline like any other clip.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import provider_models
from app.domain.usage import billable
from app.audio import tts_daemon, tts_models
from app.audio.tts_language import clone_supports, detect_script, edge_voice_language
from app.audio.tts_models import WORKER_PATH
from app.core.db import SessionLocal
from app.domain.jobs import TTS_SLOTS, run_job_guarded, say
from app.db.models import Asset, Job, Voice
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job, dispatch_job, emit_job_event
from app.media.paths import resolve_key, voice_dir, voice_key
from app.media.probe import probe_media
from app.core.child_process import run_logged
from app.core.text import blame_line, strip_ansi

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


def engines_needing_reference_text() -> set[str]:
    """哪些引擎必须有参考文本 —— **从引擎目录读**,不在这里另存一份。

    此前这里是一个 frozenset 字面量:一张"关于引擎的知识"流落在声明它的表之外。
    今天所有 bug 的共同根就是这个形状(同一件事两处各说各的),所以连这种小的也收回去。
    """
    return {engine.id for engine in tts_models.CATALOG if engine.needs_reference_text}

REFERENCE_TEXT_REQUIRED_HINT = (
    "这个音色没有填参考文本,而 {label} 不会自己识别 —— 它需要知道那段参考音频说的是什么,"
    "才能学到音色;没有的话合成出来会是一段听不懂的声音。"
    "在音色库里重建这个音色时把参考文本填上,或者改用 F5-TTS(它会自己转写参考音频)。"
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


#: 长得像「异常那一行」的:`ModuleNotFoundError: ...`、`OSError: ...`、`RuntimeError: ...`。


def explain_worker_failure(stderr: str) -> str:
    """把 worker 的 traceback 变成界面上那**一句**话。

    用户截图里那张卡片是四行文件路径 + 一排 `^^^^`(终端里指向出错列的记号,换到浏览器里
    只是噪声)+ 最后才是真正有用的 `ModuleNotFoundError: No module named 'natsort'`。
    traceback 的最后一行就是异常本身,前面那些是给读代码的人看的,不是给点了「生成配音」的人。

    完整 traceback 仍然进日志 —— 排查要它,界面不要。
    """
    unknown = "合成失败,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。"
    text = strip_ansi(stderr or "").strip()
    if not text:
        return unknown
    # **最后一行不一定是异常**(torchcodec 会以 `[end of ... traceback].` 这样的分隔线收尾)。
    # 判据搬到了 core/text.blame_line —— 同一个毛病在下载权重、装依赖那两条路上又各犯过一次。
    last = blame_line(text)
    if not last:
        return unknown  # 全是进度条 / 分隔线时,说不出原因就别硬编一个
    if "libtorchcodec" in text or "torchcodec" in last:
        # 这个错在 macOS 上有确定的成因:torchcodec 的 dylib 按 FFmpeg 大版本编译,而 0.16 起
        # 它们不带 rpath,dlopen 自己找不到 libavutil。应用会在启动 worker 时把可用的 FFmpeg
        # 库目录注进去(见 tts_models._ffmpeg_runtime_dir);走到这儿说明没找到能配对的那一份。
        return (
            "音频解码库(torchcodec)加载不了:它需要一份版本对得上的 FFmpeg。"
            "升级引擎依赖通常就能解决(设置 →「声音克隆」→ 下载);"
            "若仍然如此,装一个 Homebrew 的 ffmpeg 即可,系统那份不会被改动。"
        )
    if "ModuleNotFoundError" in last or "ImportError" in last:
        # 缺依赖是**能行动**的:光扔一个模块名,用户只能去搜。
        return (
            f"{last[:200]} —— 引擎的运行环境不完整。"
            "去设置的「声音克隆」那一页点「下载」,它会把缺的依赖补上。"
        )
    return last[:400]


#: 音色 id 的语言前缀 —— 火山的内置音色叫 `zh_female_cancan_…`,语言就写在名字里。
#: **白名单**,不是「任意两个字母 + 下划线」:后者会把 `my_custom_voice` 里的 `my_` 当成语言
#: 代码,于是用户自己起名的音色被无端挡下(测试抓到过)。拿不准时放行,是这道闸门的底线。
_VOICE_ID_LANGS = frozenset({"zh", "en", "ja", "ko", "es", "fr", "de", "ru", "pt", "it", "ar", "hi", "th", "vi", "id"})
_VOICE_ID_LANG = re.compile(r"^([a-z]{2})_")


def _refuse_if_unspeakable(text: str, engine: str, engine_voice: str, clone_engine: str) -> None:
    """这段文本,这个音色念得了吗 —— 念不了就**现在**说,别等它交出一段废音。

    引擎在语言不匹配时不会报错:它按自己认识的发音规则硬念一遍,产出一段听起来像中文又不像
    中文的东西。用户等几十秒拿到废音,而且没有任何线索指向原因(这条 bug 就是这么报上来的:
    「明明是日文,配出来是中文和听不懂的声音」)。

    只在**能确证**时拦(见 tts_language:假名、谚文是硬证据),而且只拦确知的不匹配 ——
    音色语言未知(账号自定义音色、OpenAI 那种多语言引擎)一律放行。宁可漏拦不可错拦:
    错拦挡住的是一次本来能成的合成。
    """
    script = detect_script(text)
    if not script:
        return
    label = {"ja": "日文", "ko": "韩文"}[script]
    if engine == "clone":
        if not clone_supports(script):
            from app.audio import f5_models

            missing = f5_models.missing_for_language(script)
            if missing is not None:
                # **能下就说下什么** —— 这不是引擎的固有限制,是这台机器上还缺一份权重。
                size = round(missing.expected_bytes / 1_000_000_000, 1)
                raise VoiceError(
                    f"这段文本是{label},而本地克隆现在装的权重念不了它。"
                    f"去设置的「声音克隆」下载{label}模型(约 {size} GB)后就能用你自己的音色念;"
                    f"不想等的话,改用 Edge TTS 的{label}音色或 OpenAI TTS。"
                )
            raise VoiceError(
                f"这段文本是{label},而本地音色克隆没有能念它的模型 —— 它不会报错,只会念出一段"
                f"听不懂的声音。改用 Edge TTS 的{label}音色,或 OpenAI TTS。"
            )
        return
    if engine == "edge":
        voice_lang = edge_voice_language(engine_voice)
        if voice_lang and voice_lang != script:
            raise VoiceError(f"这段文本是{label},而选中的 Edge 音色是 {voice_lang} 的 —— 请换一个 {script}- 开头的音色。")
        return
    # 别的引擎按音色 id 的语言前缀判(火山:zh_female_…)。前缀不认识就放行。
    prefix = _VOICE_ID_LANG.match(engine_voice or "")
    if prefix and prefix.group(1) in _VOICE_ID_LANGS and prefix.group(1) != script:
        raise VoiceError(
            f"这段文本是{label},而选中的音色是 {prefix.group(1)} 的 —— 它念出来会是一段听不懂的声音,"
            f"请换一个能念{label}的音色。"
        )


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
        raise VoiceError(f"参考音频处理失败:{blame_line(result.stderr, fallback='ffmpeg 没有说明原因')}")


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
        raise VoiceError(f"提取说话人音频失败:{blame_line(result.stderr, fallback='ffmpeg 没有说明原因')}")

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


def recognize_reference_text(db: Session, voice: Voice) -> Voice:
    """让应用自己听一遍参考音频,把参考文本填上。

    Fish Speech 要求参考文本,而用户手里是一段自己录的音频 —— 让他打一遍自己说过的话,
    是把一件应用能做的事推给了人。而 F5 的"自动识别"要先下 1.6 GB 的 Whisper,更是绕远:
    **这个应用里已经装着转写引擎**,它就是干这个的。

    转不了就明说(转写引擎没装),而不是留个空文本让合成出去丢人。
    """
    from app.audio import service

    reference = reference_path(voice)
    if not reference.is_file():
        raise VoiceError("这条音色的参考音频不在了,没法识别")
    python, provider = service.resolve_asr_runtime()  # 没装转写引擎时它自己会说清楚
    output = service.run_asr(reference, python, provider)
    text = "".join(str(segment.get("text") or "") for segment in (output.get("segments") or [])).strip()
    if not text:
        raise VoiceError("没听出内容 —— 参考音频可能太轻或没有人声,换一段再试")
    voice.reference_text = text
    db.commit()
    db.refresh(voice)
    return voice


def update_voice(db: Session, voice: Voice, *, name: str | None, reference_text: str | None) -> Voice:
    """补填/更正音色的说明性字段。

    为什么必须有这个:参考文本刚变成 Fish Speech 的必填项(它不带 ASR,空文本会让输出
    听不懂),而此前音色只有 upload / delete —— 于是一条已经录好的音色只因为当初没填文本
    就得删了重录。**一个新加的必填项,如果没有补填入口,就是在逼用户重做已经做过的事。**
    """
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise VoiceError("音色名称不能为空")
        voice.name = cleaned
    if reference_text is not None:
        voice.reference_text = reference_text.strip()
    db.commit()
    db.refresh(voice)
    return voice


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
    clone_model: str = "",
) -> Job:
    """Queue a synthesis job.

    The clone engine needs a Voice row — it works from that reference clip. A remote engine does
    not: it speaks in a stock voice, so it needs a workspace to own the result and an engine
    voice id, and requiring a Voice there would mean inventing rows for voices we do not host.
    """
    if not text.strip():
        raise VoiceError("合成文本不能为空")
    # 语言对不上就现在拦 —— 建了任务再失败,用户已经等了几十秒;而它根本不会"失败",
    # 只会安静地交出一段念不对的音频。
    _refuse_if_unspeakable(text, engine, engine_voice, clone_engine)
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
        # 先把引擎定下来:下面几条判据都跟引擎走,而请求不带引擎时它是空串 ——
        # 在解析之前判,等于对"用默认引擎"的那一半请求什么都没判。
        clone_engine = resolve_clone_engine(clone_engine)
        # 「留空则自动识别」这句话只有 F5 兑现。Fish Speech 拿到空文本就是空文本 ——
        # 在建任务之前说,而不是等一次十分钟的合成之后交一段听不懂的东西。
        if clone_engine in engines_needing_reference_text() and not (voice.reference_text or "").strip():
            raise VoiceError(REFERENCE_TEXT_REQUIRED_HINT.format(label=clone_engine))
        # 本地克隆跑不跑得起来,**建任务之前**就知道:探一次解释器、看一眼权重目录而已。
        # 不挡的话它会一路跑到 worker:导不进引擎就写一段正弦音(用户说的「根本克隆不了」),
        # 权重缺席就顺手下 2GB(用户说的「不该自动开启下载」)。
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
            "subject": text[:80],
            "voice_id": voice_id,
            "project_id": project_id,
            "text": text[:200],
            "engine": engine,
            "clone_engine": clone_engine if engine == "clone" else "",
            "clone_model": clone_model,
            "engine_voice": engine_voice,
            "provider_profile_id": provider_profile_id,
            "engine_model": engine_model,
        },
        message="jobMsg_ttsRunning", message_params={"voice": label},
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
            clone_model,
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
    clone_model: str = "",
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
        clone_model,
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
            say(job, message)
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
    clone_model: str = "",
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
            say(job, "jobMsg_ttsRunning", voice=voice.name if voice else (engine_voice or engine))
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
            # 把**这次要跑的解释器**交出去:torchcodec 的 FFmpeg 库路径按那个 venv 里装的版本定,
            # 而不同引擎的 venv 装的 torchcodec 可以不是一个版本。
            worker_env = tts_models._worker_env(python)
            with tempfile.TemporaryDirectory(prefix="open-studio-tts-") as tmp:
                out_wav = Path(tmp) / "speech.wav"
                request = {
                    "action": "synthesize",
                    "engine": engine,
                    "reference_wav": str(ref),
                    "reference_text": voice.reference_text,
                    "text": text,
                }
                # 按这段文本该用哪份权重 —— 无条件问一句,**这里不需要知道哪个引擎有多份**。
                # 有多份的引擎自己回答(tts_models.weights_for),没有的返回空,原样跑。
                request.update(tts_models.weights_for(engine, text, clone_model))
                request["output_path"] = str(out_wav)
                # 语速按引擎传:fish 的请求结构里没有这一项,塞进去只会被忽略,
                # 而"传了却没用"正是今天反复出现的那种谎。
                if tts_models._BY_ID[engine].supports_speed:
                    request["speed"] = speed

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
            say(job, "jobMsg_ttsDone")
            job.result = {"asset_id": asset.id, "engine": used}
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                say(job, "jobMsg_ttsFailed")
                job.error = str(exc)[:600]
                emit_job_event(db, job.id, "job.failed", {})
                db.commit()
            # 失败落进任务行是给用户看的;日志是给排查的人看的。此前只有前者,于是一次
            # 失败在日志里一个字都没有 —— 而这一整天的排查全靠日志。
            logger.warning("配音任务 %s 失败(%s):%s", job_id, engine, str(exc)[:400])


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
    from app.audio.tts import SpeechRequest, build_remote_provider
    from app.domain.providers import resolve_profile

    # The profile carries base_url too. Reading only the key would send a proxy user's request
    # to api.openai.com with a key that is not valid there — a 401 with no hint as to why.
    # 这次配音替谁干,job 上记着 —— 后台线程手里只有它(见 Job.created_by)。
    # 引擎 id 通常就是 vendor id,百炼是唯一的例外:qwen-tts 与 CosyVoice 是两个引擎、
    # 一条连接、一把 Key(见 audio.tts.vendor_for_engine)。
    from app.audio.tts import REMOTE_ENGINES, vendor_for_engine

    profile = resolve_profile(db, vendor_for_engine(engine), provider_profile_id, user_id=job.created_by)
    api_key = (profile.api_key if profile else None) or ""
    # **模型要按引擎那一族筛**。同一条连接下可以同时挂着 qwen-tts 和 cosyvoice-v2,
    # 不筛的话切到 CosyVoice 引擎会把 qwen 的模型名发去 CosyVoice 的端点(得到 `url error`)。
    engine_cls = REMOTE_ENGINES.get(engine)
    prefixes = getattr(engine_cls, "MODEL_PREFIXES", ())
    resolved = (
        provider_models.model_id_for_family(db, profile, "tts", prefixes)
        or getattr(engine_cls, "DEFAULT_MODEL", "")
        if prefixes
        else provider_models.model_id_for(db, profile, "tts")
    )
    model = model_override or voice_resource or resolved
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
    say(job, "jobMsg_ttsDone")
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
        message="jobMsg_podcastRunning",
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
        say(job, "jobMsg_podcastDone")
        # The dialogue text is returned without timings, and inventing them from character
        # counts would produce subtitles that drift audibly. Callers that need a timed
        # transcript can run the normal 转写 over the generated audio, which measures them.
        job.result = {"asset_id": asset.id, "texts": result.texts}
        emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
        db.commit()
