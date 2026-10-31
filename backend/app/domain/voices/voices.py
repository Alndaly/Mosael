"""Voice-clone domain: manage cloned voices (reference clip + transcript) and
synthesize new speech in a voice via the external TTS worker. Synthesized speech
is registered as a normal audio asset (with waveform), so it can be dragged onto
the timeline like any other clip.
"""
from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.billing.usage import billable, once
from app.ai.runtime import f5_models, tts_daemon, tts_models, config as tts_config, qwen_models
from app.ai.runtime.f5_models import clone_supports
from app.ai.runtime.tts_language import detect_script
from app.core.unit_of_work import after_commit, unit_of_work
from app.domain.jobs import (
    TTS_SLOTS,
    JobCancelled,
    blame,
    ensure_wanted,
    finish_job,
    say,
    start_job,
    create_job,
    dispatch_job,
    emit_job_event,
)
from app.db.models import Asset, Job, Voice, PluginInstance, Transcript, new_id
from app.db.model_base import now
from app.domain.assets.importer import register_file_asset
from app.domain.assets.media_info import patch_media_info
from app.media.paths import resolve_key, voice_dir, voice_key
from app.media.probe import probe_media
from app.core.child_process import run_logged
from app.core.i18n import LocalizedError, tr
from app.core.text import blame_line, strip_ansi
from app.core.config import settings
from app.domain.consent import CONSENT_KINDS
from app.domain.voices.errors import VoiceError
from app.domain.voices.speakable import speakable_text
from app.domain.voices.speech import (
    CLONE_ENGINE,
    EDGE_ENGINE,
    LOCAL_SPEECH_ENGINES,
    QWEN_ENGINE,
    adapter_id,
    is_plugin,
    require_engine,
)
from mosael_formats.plugin_manifest import SPEECH
from app.domain.voices.target import speech_target
from app.ai import providers
from app.ai.providers import (
    PodcastAction,
    SpeechSynthesisError,
    SpeechSynthesisRequest,
    connection_vendor_for_speech_engine,
)
from app.domain.plugins import tools as plugins_tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.runtime import PluginRuntimeError
from app.domain.plugins.tools import staged_artifact
from app.domain.providers import selection as providers_selection
from app.domain.voices import remote, transcription
from app.domain.voices.voice_labels import builtin_voice_label
from app.domain.voices.voice_ref import VoiceRef

if TYPE_CHECKING:
    from app.domain.voices.remote import DeleteFailure

logger = logging.getLogger(__name__)

REFERENCE_MAX_SECONDS = 15

#: 产出登记成素材之后、任务落「成功」之前,调用方要接着做的那一步(同一个事务):`(db, 素材 id)`。
#: 创作页的记录靠它挂上产出(generation.voiced,ADR 0055 §5);配音这一族不知道有生成记录。
OnAsset = Callable[[Session, str], None]

#: 素材名里文本开头取几个字(ADR 0055 §7)。西文一个词好几个字母,同样的长度只够半句,多给一些。
NAME_HEAD_CHARS = 16
NAME_HEAD_CHARS_LATIN = 28


def _text_head(text: str) -> str:
    flat = " ".join(text.split())
    limit = NAME_HEAD_CHARS_LATIN if flat.isascii() else NAME_HEAD_CHARS
    return flat if len(flat) <= limit else f"{flat[:limit].rstrip()}…"


def _short_voice_name(label: str) -> str:
    """「晓晓(女·温暖)」→「晓晓」:括号里是给挑音色的人看的说明,素材名里只要名字。"""
    return re.split(r"[((]", label, maxsplit=1)[0].strip() or label.strip()


def speech_asset_name(voice_label: str, text: str) -> str:
    """念出来的那一段叫「音色名 · 文本开头」(ADR 0055 §7)。此前是 `zh-CN-XiaoxiaoNeural · 配音`:
    露的是音色 id,而且每一段都一样,素材库里认不出哪段念的是什么。"""
    name = _short_voice_name(voice_label)
    head = _text_head(text)
    return f"{name} · {head}" if head else name


def podcast_asset_name(subject: str) -> str:
    """播客叫「主题或材料开头 · 播客」(按发起时的语言,ADR 0055 §7)。此前一律是「播客对话」。"""
    return tr("podcastAssetName", subject=_text_head(subject) or tr("podcastAssetUntitled"))


def _voice_label(engine_voice: str, given: str = "") -> str:
    """远端引擎的音色叫什么:调用方给的(界面上那份目录 —— 火山按账号现拉的音色只有它知道名字)→ 内置音色表 → 音色 id。"""

    return given.strip() or builtin_voice_label(engine_voice) or engine_voice
#: 零样本克隆靠这几秒把音色条件化。给不够就条件化不起来,模型会一路漫游到 token 上限,
#: 出来是几十秒的胡话 —— 用户实测:2.6 秒的参考,换来四十多秒听不懂的东西。
#: 这个下限本来就写在界面提示里(「5–15 秒」),只是从来没有人执行它。
REFERENCE_MIN_SECONDS = 5.0


def engines_needing_reference_text() -> set[str]:
    """哪些引擎必须有参考文本 —— **从引擎目录读**,不在这里另存一份。

    此前这里是一个 frozenset 字面量:一张"关于引擎的知识"流落在声明它的表之外。
    今天所有 bug 的共同根就是这个形状(同一件事两处各说各的),所以连这种小的也收回去。
    """
    return {engine.id for engine in tts_models.CATALOG if engine.needs_reference_text}


def check_reference_duration(seconds: float) -> None:
    """够不够长。**在建音色之前问** —— 一条注定合成不出东西的音色会出现在音色库里,
    像个能用的选项;而它的代价要等到一次十分钟的合成之后才显现。

    拒绝要**能行动**:说清楚他给了多长、要多长,而不是只说"太短"。"""
    if seconds < REFERENCE_MIN_SECONDS:
        raise VoiceError(
            "voiceErr_referenceTooShort",
            actual=f"{seconds:.1f}",
            min=f"{REFERENCE_MIN_SECONDS:.0f}",
            max=str(REFERENCE_MAX_SECONDS),
        )
TTS_TIMEOUT_SECONDS = 1200


def _ffmpeg_reason(stderr: str) -> object:
    """ffmpeg 失败时那一句原因:原文不翻,说不出原因时给一句翻得动的话。"""
    return blame_line(stderr) or LocalizedError("voiceErr_ffmpegNoReason")


#: 本机克隆在 `VoiceRef.model` 里写「哪个本机引擎 / 哪一份权重」时用的分隔符:`f5-tts`、`f5-tts/fr`、`fish-speech`。
CLONE_MODEL_SEPARATOR = "/"


def clone_runtime_of(model: str = "") -> tuple[str, str]:
    """本机克隆这一次用哪个本地引擎、哪一份权重:`VoiceRef.model` → `(引擎, 权重)`(ADR 0087 §3)。

    设置页那个引擎是**默认**,不是唯一 —— 配音面板每次生成都可能想换一个(F5 快、Fish 支持情感标签)。
    空 = 部署默认的引擎、按文字自动挑权重;只写引擎 = 自动挑权重;`引擎/权重` = 人明说的那一份(法语、德语都写拉丁字母,
    自动挑永远挑不中,见 f5_models.weights_for)。认不出就拒,不悄悄退回默认。
    """

    engine, _, weights = (model or "").strip().partition(CLONE_MODEL_SEPARATOR)
    engine = engine.strip() or tts_config.get().engine
    if engine not in {item.id for item in tts_models.CATALOG if item.clones_voices}:
        raise VoiceError("voiceErr_unknownCloneModel", model=model)
    if weights and (engine != f5_models.ENGINE_ID or f5_models.get(weights) is None):
        raise VoiceError("voiceErr_unknownCloneModel", model=model)
    return engine, weights.strip()


#: 长得像「异常那一行」的:`ModuleNotFoundError: ...`、`OSError: ...`、`RuntimeError: ...`。


def worker_failure(stderr: str) -> VoiceError:
    """把 worker 的 traceback 变成界面上那**一句**话(一个带 key 的 VoiceError)。

    用户截图里那张卡片是四行文件路径 + 一排 `^^^^`(终端里指向出错列的记号,换到浏览器里
    只是噪声)+ 最后才是真正有用的 `ModuleNotFoundError: No module named 'natsort'`。
    traceback 的最后一行就是异常本身,前面那些是给读代码的人看的,不是给点了「生成配音」的人。

    完整 traceback 仍然进日志 —— 排查要它,界面不要。异常那一行是上游原文,不翻,作为
    `detail` 放进翻好的句子里。
    """
    text = strip_ansi(stderr or "").strip()
    if not text:
        return VoiceError("voiceErr_synthNoReason")
    # **最后一行不一定是异常**(torchcodec 会以 `[end of ... traceback].` 这样的分隔线收尾)。
    # 判据搬到了 core/text.blame_line —— 同一个毛病在下载权重、装依赖那两条路上又各犯过一次。
    last = blame_line(text)
    if not last:
        return VoiceError("voiceErr_synthNoReason")  # 全是进度条 / 分隔线时,说不出原因就别硬编一个
    if "libtorchcodec" in text:
        # **装了、加载不起来**:torchcodec 的 dylib 按 FFmpeg 大版本编译,而 0.16 起它们不带 rpath,
        # dlopen 自己找不到 libavutil。应用会在启动 worker 时把可用的 FFmpeg 库目录注进去
        # (见 tts_models._ffmpeg_runtime_dir);走到这儿说明没找到能配对的那一份。
        # 只认这条加载失败的 traceback(它带着 `libtorchcodec`)。**没装**是另一回事 —— torchaudio 2.9+
        # 报的是 `ImportError: TorchCodec is required for load_with_torchcodec`,那是缺依赖,
        # 落到下面那条:此前按「最后一行提到 torchcodec」判,把缺包说成 FFmpeg 版本对不上,指错了方向。
        return VoiceError("voiceErr_synthTorchcodec")
    if "ModuleNotFoundError" in last or "ImportError" in last:
        # 缺依赖是**能行动**的:光扔一个模块名,用户只能去搜。
        return VoiceError("voiceErr_synthMissingModule", detail=last[:200])
    return VoiceError("voiceErr_synthFailed", detail=last[:400])


#: 音色 id 的语言前缀 —— 火山的内置音色叫 `zh_female_cancan_…`,语言就写在名字里。
#: **白名单**,不是「任意两个字母 + 下划线」:后者会把 `my_custom_voice` 里的 `my_` 当成语言
#: 代码,于是用户自己起名的音色被无端挡下(测试抓到过)。拿不准时放行,是这道闸门的底线。


def _refuse_if_unspeakable(text: str, voice: VoiceRef) -> None:
    """这段文本,这个音色念得了吗 —— 念不了就**现在**说,别等它交出一段废音。

    引擎在语言不匹配时不会报错:它按自己认识的发音规则硬念一遍,产出一段听起来像中文又不像
    中文的东西。用户等几十秒拿到废音,而且没有任何线索指向原因(这条 bug 就是这么报上来的:
    「明明是日文,配出来是中文和听不懂的声音」)。

    只在**能确证**时拦(见 tts_language:假名、谚文是硬证据),而且只拦确知的不匹配 ——
    音色语言未知(账号自定义音色、OpenAI 那种多语言引擎)一律放行。宁可漏拦不可错拦:
    错拦挡住的是一次本来能成的合成。

    **音色的语言只认音色目录上的声明**(ADR 0087):Edge 的 locale、火山的 id 约定都由各家 Adapter 翻成
    `VoiceOption.languages`,这里不再自己解析 id。只查内置目录 —— 每次合成都走这里,不能为它签名现拉账号清单;
    账号音色的语言由界面在提交前按它拿到的那份目录提示。
    """
    script = detect_script(text)
    if not script:
        return
    engine = voice.engine
    if engine == QWEN_ENGINE:
        # Qwen3-TTS 支持 10 种语言(含日韩俄),但**没有**阿拉伯文/天城文。念不了就现在说,
        # 别让它按自己的发音规则硬念一遍交出一段废音。日/韩/俄放行 —— 不要照抄克隆那条
        # 「日文要下权重」的判据(那是模型权重的限制,这里不是)。

        if script not in qwen_models.MODEL.languages:
            raise VoiceError("voiceErr_qwenUnsupportedLanguage")
        return
    #: 「这段文本是日文」的语言名每种界面语言各说各的,所以按文种各一条文案,而不是把一个
    #: 中文语言名当参数塞进英文句子里。detect_script 只认得出这两种。
    keys = _SCRIPT_REFUSALS[script]
    if engine == CLONE_ENGINE:
        if not clone_supports(script):
            missing = f5_models.missing_for_language(script)
            if missing is not None:
                # **能下就说下什么** —— 这不是引擎的固有限制,是这台机器上还缺一份权重。
                size = round(missing.expected_bytes / 1_000_000_000, 1)
                raise VoiceError(keys["needs_weights"], size=str(size))
            raise VoiceError(keys["clone_unsupported"])
        return
    listed = providers.builtin_voice(adapter_id(engine), voice.voice) if voice.voice else None
    #: 目录上写的是 BCP 47(`ja-JP`),文种判据只认主语言(`ja`)。
    spoken = sorted({language.split("-")[0] for language in listed.languages}) if listed is not None else []
    if spoken and script not in spoken:
        raise VoiceError(keys["edge_mismatch" if engine == EDGE_ENGINE else "voice_mismatch"], voice_lang=spoken[0])


_SCRIPT_REFUSALS = {
    "ja": {
        "needs_weights": "voiceErr_jaCloneNeedsWeights",
        "clone_unsupported": "voiceErr_jaCloneUnsupported",
        "edge_mismatch": "voiceErr_jaEdgeVoiceMismatch",
        "voice_mismatch": "voiceErr_jaVoiceMismatch",
    },
    "ko": {
        "needs_weights": "voiceErr_koCloneNeedsWeights",
        "clone_unsupported": "voiceErr_koCloneUnsupported",
        "edge_mismatch": "voiceErr_koEdgeVoiceMismatch",
        "voice_mismatch": "voiceErr_koVoiceMismatch",
    },
}


def _require_local_engine(engine: str) -> None:
    """跑得了**而且**出得了声,才让建任务。

    两件事:解释器能不能 import 这个引擎,以及权重在不在盘上。此前只挡前者 —— 于是权重缺席时
    任务照建,worker 在首次合成里顺手下 2GB:界面上是一个看不出在干嘛、卡几十分钟的任务。
    下载是用户在设置页按「下载」时明确要做的事,不该由一次"生成配音"顺带触发。
    """
    label = next((item.label for item in tts_models.CATALOG if item.id == engine), engine)
    if tts_models.resolve_engine_python(engine) is None:
        raise VoiceError("voiceErr_noRuntime", label=label)
    if not tts_models.is_installed(engine):
        raise VoiceError("voiceErr_noWeights", label=label)


def _transcode_reference(source: Path, target: Path) -> None:
    """Normalize any uploaded audio/video to 24k mono WAV, capped at 15s."""
    result = run_logged(
        [settings.ffmpeg, "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "24000",
         "-t", str(REFERENCE_MAX_SECONDS), str(target)],
        capture_output=True, text=True, timeout=300, what="参考音频转码")
    if result.returncode != 0 or not target.exists():
        raise VoiceError("voiceErr_referenceTranscodeFailed", detail=_ffmpeg_reason(result.stderr))




def _declared(kind: str) -> str:
    """建音色、补声明时收的那一项:只能是 consent.CONSENT_KINDS 里的一种,不收「未声明」。"""
    cleaned = (kind or "").strip()
    if cleaned not in CONSENT_KINDS:
        raise VoiceError("voiceErr_consentKind", kinds=" / ".join(CONSENT_KINDS))
    return cleaned


def create_from_upload(db: Session, *, workspace_id: str, source: Path, name: str, reference_text: str,
                       consent_kind: str, actor_id: str | None) -> Voice:

    consent_kind = _declared(consent_kind)

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
        consent_kind=consent_kind,
        consent_by=actor_id,
        consent_at=now(),
    )
    db.add(voice)
    db.flush()
    db.refresh(voice)
    return voice


def create_from_speaker(db: Session, *, workspace_id: str, asset_id: str, speaker: str | None, name: str,
                        consent_kind: str, actor_id: str | None) -> Voice:
    """Clone a voice from a transcribed asset: pull up to ~8s of the given
    speaker's own audio (their transcript segments) as the reference clip, and
    their transcript text as the reference text."""

    consent_kind = _declared(consent_kind)

    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise VoiceError("voiceErr_assetNotFound")
    if not asset.file_key:
        raise VoiceError("voiceErr_assetNoFile")
    transcript = db.scalar(select(Transcript).where(Transcript.asset_id == asset_id))
    if transcript is None:
        raise VoiceError("voiceErr_noTranscript")

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
        raise VoiceError("voiceErr_noSpeakerSegments")

    reference_text = " ".join(seg.text.strip() for seg in picked if seg.text.strip())[:2000]
    voice_id = new_id()
    target_dir = voice_dir(workspace_id, voice_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ref = target_dir / "reference.wav"
    # Select just this speaker's ranges in one pass and re-stamp timestamps.
    expr = "+".join(f"between(t,{seg.start_time:.3f},{seg.end_time:.3f})" for seg in picked)
    result = run_logged(
        [settings.ffmpeg, "-y", "-v", "error", "-i", str(resolve_key(asset.file_key)), "-vn",
         "-af", f"aselect='{expr}',asetpts=N/SR/TB", "-ac", "1", "-ar", "24000", str(ref)],
        capture_output=True, text=True, timeout=300, what="说话人片段提取")
    if result.returncode != 0 or not ref.exists():
        raise VoiceError("voiceErr_speakerExtractFailed", detail=_ffmpeg_reason(result.stderr))

    voice = Voice(
        id=voice_id,
        workspace_id=workspace_id,
        name=name.strip() or (speaker or "说话人音色"),
        reference_text=reference_text,
        reference_key=voice_key(workspace_id, voice_id, "reference.wav"),
        source="speaker",
        source_asset_id=asset_id,
        source_speaker=speaker,
        consent_kind=consent_kind,
        consent_by=actor_id,
        consent_at=now(),
    )
    db.add(voice)
    db.flush()
    db.refresh(voice)
    return voice


def list_voices(db: Session, workspace_id: str) -> list[Voice]:
    return list(
        db.scalars(select(Voice).where(Voice.workspace_id == workspace_id).order_by(Voice.created_at.desc()))
    )


def get_voice(db: Session, voice_id: str) -> Voice | None:
    return db.get(Voice, voice_id)


def recognize_reference_text(db: Session, voice: Voice, *, actor_id: str | None) -> Voice:
    """让应用自己听一遍参考音频,把参考文本填上。

    Fish Speech 要求参考文本,而用户手里是一段自己录的音频 —— 让他打一遍自己说过的话,
    是把一件应用能做的事推给了人。而 F5 的"自动识别"要先下 1.6 GB 的 Whisper,更是绕远:
    **这个应用里已经装着转写引擎**,它就是干这个的。

    转不了就明说(转写引擎没装),而不是留个空文本让合成出去丢人。
    """

    reference = reference_path(voice)
    if not reference.is_file():
        raise VoiceError("voiceErr_referenceGoneForRecognition")
    #: 用点这个按钮的人的转写默认(他定了哪家就用哪家,没定用装好的本机引擎)。
    output = transcription.transcriber(db, actor_id, None).transcribe(reference)
    text = "".join(str(segment.get("text") or "") for segment in (output.get("segments") or [])).strip()
    if not text:
        raise VoiceError("voiceErr_nothingHeard")
    voice.reference_text = text
    db.flush()
    db.refresh(voice)
    return voice


def update_voice(db: Session, voice: Voice, *, name: str | None, reference_text: str | None,
                 consent_kind: str | None = None, actor_id: str | None = None) -> Voice:
    """补填/更正音色的说明性字段。

    为什么必须有这个:参考文本刚变成 Fish Speech 的必填项(它不带 ASR,空文本会让输出
    听不懂),而此前音色只有 upload / delete —— 于是一条已经录好的音色只因为当初没填文本
    就得删了重录。**一个新加的必填项,如果没有补填入口,就是在逼用户重做已经做过的事。**
    """
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise VoiceError("voiceErr_nameEmpty")
        voice.name = cleaned
    if reference_text is not None:
        voice.reference_text = reference_text.strip()
    if consent_kind is not None:
        #: 补声明 / 改声明:谁、何时由这里记,不收客户端给的。
        voice.consent_kind = _declared(consent_kind)
        voice.consent_by = actor_id
        voice.consent_at = now()
    db.flush()
    db.refresh(voice)
    return voice


def delete_voice(db: Session, voice: Voice) -> list[DeleteFailure]:
    """删一把嗓子。**先删它在远端的副本**(ADR 0037):删不掉的(钥匙失效、网络)交回去告诉用户去控制台看,
    本机这一行照删 —— 留着它不会让远端那份消失,只会让人以为删不掉。"""

    failures = remote.delete_copies(db, voice)
    ref_dir = resolve_key(voice.reference_key).parent if voice.reference_key else None
    db.delete(voice)
    if ref_dir is not None:
        # 参考音频等行真删掉了再删:回滚了的删除不该把文件带走。
        after_commit(db, lambda: _remove_dir(ref_dir))
    return failures


def _remove_dir(path: Path) -> None:
    if path.is_dir():
        import shutil

        shutil.rmtree(path, ignore_errors=True)


def reference_path(voice: Voice) -> Path:
    return resolve_key(voice.reference_key)


def start_synthesis(
    db: Session,
    *,
    text: str,
    voice: VoiceRef,
    project_id: str | None,
    created_by: str | None,
    workspace_id: str = "",
    speed: float = 1.0,
    intermediate: str = "",
    voice_label: str = "",
    usage_source: tuple[str, str] | None = None,
    on_asset: OnAsset | None = None,
) -> Job:
    """Queue a synthesis job in the chosen voice (`VoiceRef`, ADR 0087).

    The clone engine needs a Voice row — it works from that reference clip (`voice.cloned_voice`). A remote engine does
    not: it speaks in a stock voice (`voice.voice`), so it needs a workspace to own the result; an engine that can clone
    remotely (CosyVoice) may also be handed a library voice, which it speaks through its remote copy (ADR 0037).

    `intermediate`: the caller is making a part, not a result — each line of a subtitle dub is one
    (see domain/assets/intermediates). The produced asset is registered as that kind, so the library
    leaves it out; whoever makes the part says so here, the synthesis itself does not guess.

    `voice_label`:远端引擎的音色叫什么(界面那份目录里的名字),只用来给产出起名(`speech_asset_name`);没给就查内置音色表。
    `usage_source`:这次合成的用量记在谁名下,默认是这个任务(`("job", 任务 id)`);创作页的记录传它自己(ADR 0055 §5)。
    `on_asset`:产出登记之后、任务落「成功」之前在同一个事务里调(见 `OnAsset`)。
    """
    #: **到引擎的第一扇门。** 屏幕上的 markdown 不是念出来的话:`**粗体**` 会被念成「星号 粗体 星号」,
    #: 表格竖线、标题井号、URL 逐字符 —— 用户报的「所有地方都念符号」就是这一段。洗一遍再往下走,
    #: 任务回执上的 `subject`、素材名、`_refuse_if_unspeakable` 的语言判断也都对着同一份干净文字。
    text = speakable_text(text)
    if not text.strip():
        raise VoiceError("voiceErr_textEmpty")
    # 语言对不上就现在拦 —— 建了任务再失败,用户已经等了几十秒;而它根本不会"失败",
    # 只会安静地交出一段念不对的音频。
    _refuse_if_unspeakable(text, voice)
    require_engine(db, voice.engine, user_id=created_by)
    cloned = db.get(Voice, voice.cloned_voice) if voice.cloned_voice else None
    if voice.cloned_voice and cloned is None:
        raise VoiceError("voiceErr_voiceNotFound")
    if voice.engine == CLONE_ENGINE:
        if cloned is None:
            raise VoiceError("voiceErr_voiceNotFound")
        # 参考音频够不够长,先查 —— 这是**用户自己的输入**,和这台机器装没装引擎无关,
        # 所以排在引擎检查前面。库里已经有的短音色(下限是后加的)也要挡在这儿,否则它会
        # 安安静静换来一次十分钟的合成和一段听不懂的声音。
        reference = reference_path(cloned)
        if reference.is_file():
            check_reference_duration(float(probe_media(reference).get("duration") or 0.0))
        # 先把引擎定下来:下面几条判据都跟引擎走,而选择里不写模型时它取部署默认 ——
        # 在解析之前判,等于对"用默认引擎"的那一半请求什么都没判。
        runtime, _weights = clone_runtime_of(voice.model)
        # 「留空则自动识别」这句话只有 F5 兑现。Fish Speech 拿到空文本就是空文本 ——
        # 在建任务之前说,而不是等一次十分钟的合成之后交一段听不懂的东西。
        if runtime in engines_needing_reference_text() and not (cloned.reference_text or "").strip():
            raise VoiceError("voiceErr_referenceTextRequired", label=runtime)
        # 本地克隆跑不跑得起来,**建任务之前**就知道:探一次解释器、看一眼权重目录而已。
        # 不挡的话它会一路跑到 worker:导不进引擎就写一段正弦音(用户说的「根本克隆不了」),
        # 权重缺席就顺手下 2GB(用户说的「不该自动开启下载」)。
        _require_local_engine(runtime)
        #: 用**建任务时**定下的那个引擎:中途有人去设置页改了默认,这一单不该跟着漂。
        voice = replace(voice, model=CLONE_MODEL_SEPARATOR.join(filter(None, (runtime, _weights))))
        workspace_id = cloned.workspace_id
        label = cloned.name
    else:
        if not workspace_id:
            raise VoiceError("voiceErr_workspaceRequired")
        label = _voice_label(voice.voice, voice_label) or voice.engine
        if voice.engine in LOCAL_SPEECH_ENGINES:
            # 本机念字引擎:音色是模型自带的预置发音人,名字由目录认(不在目录里就是调用方的错)。
            if voice.voice and qwen_models.speaker(voice.voice) is None:
                raise VoiceError("voiceErr_qwenUnknownVoice", voice=voice.voice)
            voice = replace(voice, voice=qwen_models.speaker_id(voice.voice) or qwen_models.DEFAULT_SPEAKER)
            label = _voice_label(voice.voice) or voice.engine
            # 和克隆那条同一个判据:解释器 + 权重都在才建任务,而不是排上队再失败/顺手下一份权重。
            _require_local_engine(LOCAL_SPEECH_ENGINES[voice.engine])
        elif cloned is not None:
            # 配音库里的一把嗓子,用远端引擎念(ADR 0037):嗓子在这个工作区、声明过是谁的、这个账号同意过上传 ——
            # 建任务之前问,没同意就回 409 让界面弹确认框,而不是排上队再失败。
            if not remote.clones_remotely(voice.engine):
                raise VoiceError("voiceErr_remoteCloneUnsupported", engine=voice.engine)
            label = remote.check_voice(db, voice, workspace_id=workspace_id, user_id=created_by).name
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="tts",
        created_by=created_by,
        payload={
            #: 完整文本:回执卡/任务卡用 `Truncate` 收窄,源头不再静默切 80 字(切了就拿不回原文)。
            "subject": text,
            "project_id": project_id,
            "text": text[:200],
            "voice": voice.to_json(),
            "speed": float(speed or 1.0),
            #: 产出登记成哪种中间产物(见 domain/assets/intermediates);空串 = 进素材库。
            "intermediate": intermediate,
        },
        message="jobMsg_ttsRunning", message_params={"voice": label},
    )
    job_id = job.id
    run = partial(
        _run_synthesis_body, job_id, voice, text, float(speed or 1.0),
        workspace_id=workspace_id, project_id=project_id,
        asset_name=speech_asset_name(label, text), voice_label=label, usage_source=usage_source, on_asset=on_asset,
    )
    dispatch_job(db, job, lambda: _run_synthesis(voice, run))
    return job


def _run_synthesis(voice: VoiceRef, run: Callable[[], None]) -> None:
    """Take an admission slot before touching the database — see run_job_guarded(派发处已经替它套上了兜底).

    **本机引擎都取这个名额**(克隆、Qwen3-TTS):它们把几 GB 权重读进内存、在 CPU 上解码,
    两个一起跑只会互相抢内存和核。远端引擎是一次 HTTP 请求,不占内存,不该排在它后面。
    """
    if voice.engine == CLONE_ENGINE or voice.engine in LOCAL_SPEECH_ENGINES:
        with TTS_SLOTS:
            run()
    else:
        run()


def _intermediate_of(job: Job) -> str:
    """排这次合成的人说产出是哪种中间产物(见 start_synthesis 的 `intermediate`);没说就是进素材库的一段。"""
    return str((job.payload or {}).get("intermediate") or "")


def _update_progress(job_id: str, event: dict) -> None:
    """把 worker 报的阶段落到任务上。

    **只报它真的知道的**:阶段名 + 一个粗粒度比例。不拿"当前 token / 上限"编细进度 ——
    解码通常远早于上限就停,那条进度会永远走不到头,又是一个答非所问的数字。
    """
    fraction = event.get("fraction")
    message = event.get("message") or ""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return
        if isinstance(fraction, (int, float)):
            job.progress = max(job.progress or 0.0, min(0.95, float(fraction)))
        if message:
            say(job, message)


def _run_synthesis_body(
    job_id: str,
    voice: VoiceRef,
    text: str,
    speed: float,
    *,
    workspace_id: str,
    project_id: str | None,
    asset_name: str = "",
    voice_label: str = "",
    usage_source: tuple[str, str] | None = None,
    on_asset: OnAsset | None = None,
) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            #: 克隆引擎念的是这把嗓子;远端引擎点了配音库里的嗓子时也是它(念的是它的远端副本,ADR 0037)。
            cloned = db.get(Voice, voice.cloned_voice) if voice.cloned_voice else None
            if voice.cloned_voice and cloned is None:
                raise VoiceError("voiceErr_voiceNotFound")
            # 状态经总线写:排队时(等本机合成名额、派发器名额)被取消的,不在这里被写回「在跑」、照样去念。
            if not start_job(db, job, progress=0.2):
                return
            #: 任务上说「合成《晓晓》配音中」,不说音色 id(建任务时那一句同样用的是名字)
            say(job, "jobMsg_ttsRunning", voice=voice_label or (cloned.name if cloned else _voice_label(voice.voice) or voice.engine))
            emit_job_event(db, job.id, "job.running", {})
            # 「在念」先落库:合成要一阵(本机克隆十几分钟),界面要马上看得到。
            db.commit()

            if voice.engine != CLONE_ENGINE:
                _synthesize_remote(
                    db, job, voice, text, speed,
                    workspace_id=workspace_id or job.workspace_id, project_id=project_id,
                    cloned=cloned, asset_name=asset_name, usage_source=usage_source, on_asset=on_asset,
                )
                return

            ref = reference_path(cloned)
            if not ref.is_file():
                raise VoiceError("voiceErr_referenceMissing")
            engine, weights = clone_runtime_of(voice.model)
            python = tts_models.resolve_engine_python(engine)
            if python is None:  # 建任务时还在,跑起来时被卸了
                raise VoiceError("voiceErr_noRuntime", label=engine)
            # env 也只有一份:此前这里手拼 `{**os.environ, "HF_ENDPOINT": …}`,漏了 fish-speech
            # 要的检出目录和权重目录 —— 于是装好了 fish 的机器也照样导不进引擎、照样出占位音。
            # 把**这次要跑的解释器**交出去:torchcodec 的 FFmpeg 库路径按那个 venv 里装的版本定,
            # 而不同引擎的 venv 装的 torchcodec 可以不是一个版本。
            worker_env = tts_models._worker_env(python)
            with tempfile.TemporaryDirectory(prefix="mosael-tts-") as tmp:
                out_wav = Path(tmp) / "speech.wav"
                request = {
                    "action": "synthesize",
                    "engine": engine,
                    "reference_wav": str(ref),
                    "reference_text": cloned.reference_text,
                    "text": text,
                }
                # 按这段文本该用哪份权重 —— 无条件问一句,**这里不需要知道哪个引擎有多份**。
                # 有多份的引擎自己回答(f5_models.weights_for),没有的返回空,原样跑。
                request.update(f5_models.weights_for(engine, text, weights))
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
                    raise worker_failure(str(exc)) from exc
                if not out_wav.exists():
                    raise VoiceError("voiceErr_synthNoAudio")
                used = result.get("engine", engine)
                job = db.get(Job, job_id)
                job.progress = 0.95
                # 念完了,先把进度落库再登记素材(拷贝、探测、画波形还要一会儿)。
                db.commit()
                ensure_wanted()  # 念的时候被取消了:产出不进素材库
                asset = register_file_asset(
                    db,
                    workspace_id=cloned.workspace_id,
                    project_id=project_id,
                    source_path=out_wav,
                    name=asset_name or speech_asset_name(cloned.name, text),
                    source="tts",
                    #: 合成人声(克隆的嗓子也是):成片里有它就要加 AI 标识(《深度合成管理规定》第十七条)。
                    ai_generated=True,
                    intermediate=_intermediate_of(job),
                )
                #: 记下是哪把克隆嗓子配的:这段音频拿去做数字人时,生成漏斗照它查音色的授权声明
                #: (generation.operations.check_digital_human_rights)。引擎自带的嗓子不是谁的克隆,不记。
                patch_media_info(db, asset.id, {"voice_id": cloned.id})
                if on_asset is not None:
                    on_asset(db, asset.id)
            job = db.get(Job, job_id)
            result = {"asset_id": asset.id, "engine": used}
            if finish_job(db, job, status="succeeded", progress=1.0, result=result):
                say(job, "jobMsg_ttsDone")
                emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
        except JobCancelled:
            raise  # 不是「合成失败」:派发处的兜底认得它
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Job, job_id)
            #: 失败原因存 key + 参数,接口按读的人的语言翻(见 jobs.blame)。取消落在中途的,不改写它。
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_ttsFailed")
                emit_job_event(db, job.id, "job.failed", {})
            # 失败落进任务行是给用户看的;日志是给排查的人看的。此前只有前者,于是一次
            # 失败在日志里一个字都没有 —— 而这一整天的排查全靠日志。
            logger.warning("配音任务 %s 失败(%s):%s", job_id, voice.engine, str(exc)[:400])


__all__ = [
    "create_from_upload",
    "create_from_speaker",
    "list_voices",
    "get_voice",
    "delete_voice",
    "reference_path",
    "start_synthesis",
]


def _speak_locally(
    engine: str,
    *,
    text: str,
    engine_voice: str,
    out_dir: Path,
    job_id: str | None,
    on_progress: Callable[[dict], None] | None,
) -> Path:
    """本机念字引擎合成一段话:交给常驻 worker,写进 `out_dir/speech.wav`。

    走的是和克隆那条同一个 worker(同一个 TTS 解释器、同一条行协议、同一个常驻进程池)——
    **不另起 sidecar**。差别只在请求:这条带预置发音人,不带参考音频。

    本机引擎不花第三方的钱,所以没有计费那一笔(和克隆相同);它也不产出"是谁的克隆"这种
    授权信息 —— 音色是模型自带的,不是谁的嗓子。
    """

    runtime = LOCAL_SPEECH_ENGINES[engine]
    _require_local_engine(runtime)
    python = tts_models.resolve_engine_python(runtime)
    if python is None:  # 建任务时还在、跑起来时被卸了
        raise VoiceError("voiceErr_noRuntime", label=runtime)
    out = out_dir / "speech.wav"
    request: dict[str, object] = {
        "action": "synthesize",
        "engine": runtime,
        "text": text,
        "output_path": str(out),
    }
    if runtime == qwen_models.ENGINE_ID:
        # 音色是模型自带的 9 个之一;认不出就退回第一个(界面/智能体给了别的 id 时至少能出声)。
        request["speaker"] = qwen_models.speaker_id(engine_voice) or qwen_models.DEFAULT_SPEAKER
        # 有硬证据的语言说清楚,拿不准交 Auto —— 语言支持由模型决定,不在界面上假装更多。
        request["language"] = qwen_models.language_for(detect_script(text))
    tts_daemon.pool().request(
        runtime,
        python,
        request,
        on_progress=on_progress,
        timeout=TTS_TIMEOUT_SECONDS,
        env=tts_models._worker_env(python),
    )
    if not out.is_file() or out.stat().st_size == 0:
        raise VoiceError("voiceErr_synthNoAudio")
    return out


def speak_to_file(
    db,
    *,
    text: str,
    voice: VoiceRef,
    speed: float,
    workspace_id: str,
    user_id: str | None,
    out_dir: Path,
    source_type: str,
    source_id: str,
    job_id: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> Path:
    """用选定的那把嗓子(`VoiceRef`)合成一段语音,落到 `out_dir` 里,**不管产物归谁**。

    本机念字引擎(Qwen3-TTS)和远端引擎在这一个入口后面分叉:前者交给常驻 worker(权重已经在
    它自己的解释器里),后者是一次 HTTP 请求。**入口以上的调用方不区分这两条** —— 试听、对话
    朗读、配音任务都走这里,新增一家只需要在这里多一条路,而不是每个入口各加一遍。

    产出型(配音:登记成素材、挂在任务上)和临时型(对话里念一句、说完就扔)只在最后那一步
    不同 —— 解析连接、按引擎那一族筛模型、建适配器、记账,两条路必须逐字一样。抄第二份的话,
    "百炼一条连接两个引擎"这类坑只会在其中一条上被填。

    记账的来源由调用方给:配音挂在 job 上,临时合成挂在别的东西上 —— 但**两边都要记**,
    各家 TTS 按字符计费,念一句也是钱。

    `voice.cloned_voice`:念的是配音库里的一把克隆嗓子(ADR 0037)。它在这里被解析成「这个人的连接 + 这次的模型」下的
    远端副本,还没有就建(配音任务的进度写「正在百炼上复刻这把嗓子」);每个入口都经过这里,入口不用各自认识复刻。
    `voice.extra` 原样交给那一家 Adapter(火山的资源族),这里不读。
    """

    #: **到引擎的第二扇门。** 对话朗读、免提、试听、笔记朗读都直接走这里;任务那条路(配音、画板音、
    #: 工作流、字幕逐句配音)在建任务时已经洗过一遍,这里再走一次是**幂等**的无操作 —— 两扇门都洗,
    #: 是为了「谁也别想绕过它」,而不是两套规则(规则只有 `speakable_text` 这一个函数)。
    text = speakable_text(text)
    if not text.strip():
        raise VoiceError("voiceErr_textEmpty")
    if is_plugin(voice.engine):
        return _speak_with_plugin(db, voice.engine, text=text, voice=voice.voice, speed=speed, out_dir=out_dir)
    if voice.engine in LOCAL_SPEECH_ENGINES:
        return _speak_locally(
            voice.engine, text=text, engine_voice=voice.voice, out_dir=out_dir,
            job_id=job_id, on_progress=on_progress,
        )
    #: 能力表里是 `builtin:edge`,`ai` 层的适配器认裸名 `edge`。
    engine = adapter_id(voice.engine)
    profile, model = speech_target(db, voice, user_id=user_id)
    api_key = (profile.api_key if profile else None) or ""
    base_url = (profile.base_url if profile else "") or ""
    # 火山与 Edge 产出 mp3;其余(OpenAI 家族)按请求要的 wav 落盘。
    out = out_dir / ("speech.mp3" if engine in {"volcano", "edge"} else "speech.wav")

    def speak(session, spoken: str) -> None:
        adapter = providers.build_speech_adapter(engine, api_key=api_key, voice=spoken, model=model, base_url=base_url)
        # 各家 TTS 普遍按**字符**计费,所以计量是字符数而不是 token —— 计量因供应商而异,
        # 正是 billable 留给调用方的那一半。
        with billable(
            session,
            user_id=user_id,
            capability="tts",
            operation="synthesize_speech",
            idempotency_key=once("synthesize_speech"),
            workspace_id=workspace_id,
            # 记**连接的厂商**,不是引擎 id:价目规则(「预填价格」填的、手写的)按厂商配,百炼一条连接下的
            # qwen-tts 和 CosyVoice 两个引擎都该对上 `alibaba` 那几条价。此前记的是引擎 id,
            # CosyVoice 的账永远是「未定价」。
            provider=connection_vendor_for_speech_engine(engine),
            model=model,
            provider_profile_id=profile.id if profile else None,
            source_type=source_type,
            source_id=source_id,
            job_id=job_id,
        ) as call:
            call.meter(characters=len(text), requests=1)
            if adapter.free_of_charge:
                call.mark_free()
            adapter.synthesize(SpeechSynthesisRequest(text=text, voice=spoken, speed=speed, extra=voice.extra), out)

    if not voice.cloned_voice:
        speak(db, voice.voice)
        return out
    _speak_through_copy(
        speak, voice_id=voice.cloned_voice, engine=engine, profile=profile, user_id=user_id, model=model, job_id=job_id,
    )
    return out


def preview_podcast_to_file(
    db,
    *,
    text: str,
    voice: str,
    workspace_id: str,
    user_id: str | None,
    out_dir: Path,
) -> Path:
    """用播客协议试听一位播客发音人,不建任务、不登记素材。

    播客音色只存在于 PodcastTTS WebSocket,不能交给普通 TTS 的引擎目录。试听用一轮
    ``READ`` 稿件,因此和正式「照稿念」经过同一个协议适配器；连接解析和计费也在这里
    收口,路由只负责把临时音频交回浏览器。
    """

    spoken = text.strip()
    if not spoken:
        raise VoiceError("providerErr_podcastReadNeedsText")
    engine = providers.podcast_engine()
    profile = providers_selection.resolve_connection(db, engine.engine_id, user_id=user_id)
    out = out_dir / "podcast-preview.mp3"
    with billable(
        db,
        user_id=user_id,
        capability="podcast",
        operation="preview_podcast_voice",
        idempotency_key=once("preview_podcast_voice"),
        workspace_id=workspace_id,
        provider=engine.engine_id,
        provider_profile_id=profile.id if profile else None,
        source_type="voice_preview",
        source_id=user_id or "",
    ) as call:
        call.meter(characters=len(spoken), speakers=1, requests=1)
        engine.synthesize(
            profile,
            action=PodcastAction.READ,
            input_text=spoken,
            turns=[{"speaker": voice, "text": spoken}],
            speakers=[voice],
            out_path=out,
        )
    return out


def _speak_through_copy(speak, *, voice_id: str, engine: str, profile, user_id: str | None, model: str,
                        job_id: str | None) -> None:
    """用一把嗓子的远端副本念(ADR 0037):找(或建)副本 → 念 → 念不出来、而副本在远端已经没了 → 标 missing、
    重建**一次**、再念;再失败才报错。念成了记下 `last_used_at`。

    这条路上的账记在**自己的事务**里:复刻、标 missing 都要写那一行副本,而调用方的会话一旦记了账就攥着写锁,
    另开的事务会在它手里等到超时。
    """

    if not remote.clones_remotely(engine):
        raise VoiceError("voiceErr_remoteCloneUnsupported", engine=engine)
    if profile is None or not user_id or not profile.api_key:
        raise VoiceError("voiceErr_remoteNoConnection")
    account = remote.Account.of(engine, profile, user_id)
    enrolled: list[str] = []

    def on_enroll(name: str) -> None:
        enrolled.append(name)
        if job_id:
            _say_on_job(job_id, "jobMsg_remoteVoiceEnrolling", voice=name)

    def resolve() -> remote.Copy:
        copy = remote.ensure_copy(voice_id, account, model=model, on_enroll=on_enroll)
        if enrolled and job_id:
            _say_on_job(job_id, "jobMsg_ttsRunning", voice=enrolled[-1])
        return copy

    copy = resolve()
    try:
        with unit_of_work() as session:
            speak(session, copy.remote_voice_id)
    except SpeechSynthesisError:
        if not remote.vanished(voice_id, account, copy):
            raise
        logger.info("远端副本 %s 不在了,重建一次再念", copy.remote_voice_id)
        remote.mark_missing(copy)
        copy = resolve()
        with unit_of_work() as session:
            speak(session, copy.remote_voice_id)
    remote.touch(copy)


def _say_on_job(job_id: str, key: str, **params: object) -> None:
    """合成途中给任务换一句进度(另开事务:调用方的会话还在用)。任务已经不在跑了就不动它。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and job.status == "running":
            say(job, key, **params)


def _speak_with_plugin(db, engine: str, *, text: str, voice: str, speed: float, out_dir: Path) -> Path:
    """认领 `speech` 的插件连接念一句(`op: speak`),交回的音频拷进 `out_dir`。协议见 voices.speech。
    用量归插件自己的账,宿主不替它记字符。"""
    import shutil


    instance = db.get(PluginInstance, engine)
    name = instance.name if instance is not None else engine
    made: list[Path] = []

    def collect(output: dict, scratch: Path) -> dict:
        produced = staged_artifact(scratch, output.get("artifact"))
        if produced is None:
            raise VoiceError("voiceErr_pluginBadOutput", plugin=name, detail=str(output.get("artifact"))[:200])
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"speech{produced.suffix.lower() or '.wav'}"
        shutil.copyfile(produced, target)
        made.append(target)
        return {"artifact": produced.name}

    #: 可用性(启用、配置、凭据、授权)由 invoke_host 判,不在这里再判一遍。
    try:
        plugins_tools.invoke_host(db, engine, SPEECH, {"op": "speak", "text": text, "voice": voice, "speed": speed}, collect=collect, record=True)
    except (PluginDomainError, PluginRuntimeError) as exc:
        raise VoiceError("voiceErr_pluginFailed", plugin=name, detail=str(exc)[:500]) from exc
    return made[0]


def _synthesize_remote(
    db,
    job,
    voice: VoiceRef,
    text: str,
    speed: float,
    *,
    workspace_id: str,
    project_id: str | None,
    cloned: Voice | None = None,
    asset_name: str = "",
    usage_source: tuple[str, str] | None = None,
    on_asset: OnAsset | None = None,
) -> None:
    """Synthesise through a remote engine and register the result, mirroring the clone path.

    No reference clip and no local model, so none of the worker-subprocess machinery applies —
    but the outcome has to look identical to the caller: an audio asset on the job's result.

    `cloned`: the library voice `voice.cloned_voice` names, spoken through its remote copy (ADR 0037).
    `asset_name` / `usage_source` / `on_asset`: see start_synthesis.
    """
    source_type, source_id = usage_source or ("job", job.id)
    with tempfile.TemporaryDirectory(prefix="mosael-tts-") as tmp:
        out = speak_to_file(
            db,
            text=text,
            voice=voice,
            speed=speed,
            workspace_id=workspace_id,
            user_id=job.created_by,
            out_dir=Path(tmp),
            source_type=source_type,
            source_id=source_id,
            job_id=job.id,
            # 本机引擎(加载权重、解码)会报阶段;远端引擎不发,回调只是不被调用。
            on_progress=lambda event: _update_progress(job.id, event),
        )
        job.progress = 0.85
        # 付过费的那次合成已经回来了:进度(和这次的用量)先落库,再登记素材。
        db.commit()
        # 等远端回话的时候被取消了:账照记(上面那一笔已经落了),产出不进素材库。
        ensure_wanted()
        asset = register_file_asset(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            source_path=out,
            name=asset_name or speech_asset_name(cloned.name if cloned is not None else _voice_label(voice.voice) or voice.engine, text),
            source="tts",
            ai_generated=True,
            intermediate=_intermediate_of(job),
        )
        if cloned is not None:
            # 和本机克隆那条同一个记法:这段音频是这把嗓子的克隆,拿去做数字人时照它查授权声明。
            patch_media_info(db, asset.id, {"voice_id": cloned.id})
        if on_asset is not None:
            on_asset(db, asset.id)
    job = db.get(Job, job.id)
    if finish_job(db, job, status="succeeded", progress=1.0, result={"asset_id": asset.id, "engine": voice.engine}):
        say(job, "jobMsg_ttsDone")
        emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})


def podcast_speakers(speakers: list[str] | None) -> list[str]:
    """播客的发音人:给了用给的,没给用目录里的前两位 —— 发音人不花钱,不是替人挑一个要付费的东西(ADR 0055 §6)。"""

    return [voice for voice in (speakers or []) if voice] or [speaker.id for speaker in providers.podcast_engine().speakers[:2]]


def start_podcast(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    created_by: str | None,
    text: str = "",
    topic: str = "",
    mode: str = "summarize",
    turns: list[dict] | None = None,
    speakers: list[str] | None = None,
    speed: float = 1.0,
    provider_profile_id: str | None = None,
    usage_source: tuple[str, str] | None = None,
    on_asset: OnAsset | None = None,
) -> Job:
    """Queue a 火山 podcast job: two voices reading or discussing the given material.

    Separate from start_synthesis because it is a different product with a different
    credential and a different shape of request — one call produces a whole dialogue, not one
    utterance in a chosen voice.

    三档(ADR 0055 §6):`summarize` 把 `text` 改写成对谈,`research` 联网查 `topic` 再讨论,`read` 照 `turns` 念 ——
    `[{"speaker": 0|1, "text": ...}]`,`speaker` 是 `speakers` 里的第几位,一段一轮,原样交出去。发音人没给就用目录里的前两位
    (发音人不花钱)。这几条规矩在**建任务之前**判:建了任务再失败,用户已经等了一阵、记录上多一张失败卡。

    `usage_source` / `on_asset`:同 start_synthesis。
    """

    actions = {"summarize": PodcastAction.SUMMARIZE, "read": PodcastAction.READ, "research": PodcastAction.RESEARCH}
    if mode not in actions:
        raise VoiceError("voiceErr_unknownPodcastMode", mode=mode)
    if not workspace_id:
        raise VoiceError("voiceErr_podcastWorkspaceRequired")
    chosen = podcast_speakers(speakers)
    script: list[dict] = []
    if mode == "read":
        for turn in turns or []:
            line = str(turn.get("text") or "").strip()
            if not line:
                continue
            index = turn.get("speaker")
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(chosen):
                raise VoiceError("voiceErr_podcastTurnSpeaker")
            if len(line) > providers.podcast_engine().max_round_chars:
                raise VoiceError("providerErr_podcastTurnTooLong", limit=providers.podcast_engine().max_round_chars)
            script.append({"speaker": chosen[index], "text": line})
        if not script:
            raise VoiceError("providerErr_podcastReadNeedsText")
        if len(script) > providers.podcast_engine().max_rounds:
            raise VoiceError("providerErr_podcastTooManyTurns", limit=providers.podcast_engine().max_rounds)
    else:
        if len(chosen) != 2 or chosen[0] == chosen[1]:
            raise VoiceError("providerErr_podcastNeedsTwoSpeakers")
        if mode == "summarize" and not text.strip():
            raise VoiceError("providerErr_podcastNeedsInputText")
        if mode == "research" and not topic.strip():
            raise VoiceError("providerErr_podcastNeedsTopic")
    subject = topic if mode == "research" else script[0]["text"] if script else text

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="podcast",
        created_by=created_by,
        payload={
            #: 完整材料:显示层用 `Truncate`(此前源头切 80 字,切掉的正文永远拿不回来)。
            "subject": subject,
            "project_id": project_id,
            "mode": mode,
            "speakers": chosen,
            "text": text[:500],
            "topic": topic,
            "turns": len(script),
            "provider_profile_id": provider_profile_id,
        },
        message="jobMsg_podcastRunning",
    )
    job_id = job.id
    action = actions[mode]
    asset_name = podcast_asset_name(subject)
    dispatch_job(
        db,
        job,
        lambda: _run_podcast_body(
            job_id,
            workspace_id,
            project_id,
            text,
            topic,
            action,
            chosen,
            speed,
            provider_profile_id,
            turns=script,
            asset_name=asset_name,
            usage_source=usage_source,
            on_asset=on_asset,
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
    *,
    turns: list[dict] | None = None,
    asset_name: str = "",
    usage_source: tuple[str, str] | None = None,
    on_asset: OnAsset | None = None,
) -> None:

    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        # 排队时被取消的不再去合成(那是一次付费调用)。
        if not start_job(db, job, progress=0.2):
            return
        emit_job_event(db, job.id, "job.running", {})
        # 「在做」先落库:一次播客合成要几分钟,界面要马上看得到。
        db.commit()

        engine = providers.podcast_engine()
        #: 凭据怎么从连接里取(火山:appid 在附加字段、token 在钥匙)是那一家自己的事,这里只把连接整个交过去。
        profile = providers_selection.resolve_connection(db, engine.engine_id, provider_profile_id, user_id=job.created_by)
        source_type, source_id = usage_source or ("job", job_id)
        #: 按交出去的字数计:改写是材料、讨论是主题、照稿念是每一段加起来。
        characters = sum(len(turn["text"]) for turn in turns) if turns else len(text or topic or "")

        with tempfile.TemporaryDirectory(prefix="mosael-podcast-") as tmp:
            out = Path(tmp) / "podcast.mp3"
            with billable(
                db,
                user_id=job.created_by,
                capability="podcast",
                operation="synthesize_podcast",
                workspace_id=workspace_id,
                provider=engine.engine_id,
                provider_profile_id=profile.id if profile else None,
                source_type=source_type,
                source_id=source_id,
                job_id=job_id,
                # 一个播客任务只合成一次,任务 id 就是那个稳定的工作单元 —— 崩了重跑不会重复计费。
                idempotency_key=f"podcast:{job_id}",
            ) as call:
                # 播客按输入文本量计费,和 TTS 同一类;说话人数会影响时长,一并记下来。
                call.meter(characters=characters, speakers=len(speakers or []), requests=1)
                result = engine.synthesize(
                    profile,
                    action=action,
                    input_text=text,
                    prompt_text=topic,
                    turns=turns,
                    speakers=speakers,
                    speed=speed,
                    out_path=out,
                )
            job = db.get(Job, job_id)
            job.progress = 0.85
            # 付过费的那次合成已经回来了:进度(和这次的用量)先落库,再登记素材。
            db.commit()
            ensure_wanted()  # 合成途中被取消:账照记,产出不进素材库
            asset = register_file_asset(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                source_path=out,
                name=asset_name or podcast_asset_name(topic or text),
                source="podcast",
                ai_generated=True,
            )
            #: 对谈稿跟着这段音频走(ADR 0055 §6):任务会被清掉,素材不会;「改稿再念」、以后转字幕都从这里读。
            patch_media_info(db, asset.id, {
                "dialogue": [{"speaker": str(one.get("speaker") or ""), "text": str(one.get("text") or "")}
                             for one in result.texts],
                "speakers": [{"value": voice, "label": builtin_voice_label(voice) or voice} for voice in speakers],
            })
            if on_asset is not None:
                on_asset(db, asset.id)

        job = db.get(Job, job_id)
        # The dialogue text is returned without timings, and inventing them from character
        # counts would produce subtitles that drift audibly. Callers that need a timed
        # transcript can run the normal 转写 over the generated audio, which measures them.
        if finish_job(db, job, status="succeeded", progress=1.0, result={"asset_id": asset.id, "texts": result.texts}):
            say(job, "jobMsg_podcastDone")
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
