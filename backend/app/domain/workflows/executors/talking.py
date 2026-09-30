"""数字人(ADR 0028 §4):让一张脸说一段话、给一段片子对口型。

三个节点共用一条路 —— **配音 → 说话照片 / 改口型**,两步都不自己实现:配音走 `synthesize_speech`(引擎 + 音色,
和配音库同一份解析),生成走 `create_generation_job`(模型、素材角色、时长跟着音频的校验都在生成漏斗里)。

- `entity_speak`:人物资产「让它说话」。脸是它的正面图,嗓子是它自己的音色;**真人要有本人或已获同意的声明**
  (`usable_for_digital_human`),起任务之前就拒。
- `image_speak`:图片格「让它说话」。脸由那一格给,嗓子在面板上挑。
- `video_lipsync`:视频格「对口型」。片子由那一格给;音频接上游的音频格,没接就用稿子当场配。

后两个没有资产上的授权声明可查,所以面板上有一格**必须选「已取得授权」**的确认(《互联网信息服务深度合成管理规定》
第十四条要求的单独同意),不选就不跑。

产出:说话的视频(`asset_id`),以及当场配出来的那段音频(`audio_asset_id`,画板上一起落在右边 —— 不满意时可以只换
一版配音);用的是上游现成的音频时不交回它,免得画板上多出一格重复的。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai.providers.contracts.generation import DRIVING_AUDIO, FIRST_FRAME, SOURCE_VIDEO
from app.domain.jobs import current_actor
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.common import wait_for_job

SPEECH_TO_VIDEO = "speech-to-video"
VIDEO_LIPSYNC = "video-lipsync"
#: 授权确认那一格要选的值(选项只有这一个,必填)。
CONSENT_GIVEN = "yes"


def _text(value: Any) -> str:
    return str(value or "").strip()


def talking_models(db: Session, mode: str, actor_id: str | None) -> list[dict[str, Any]]:
    """这个人能用的、声明了这种模式(说话照片 / 改口型)的视频模型。模式是描述符说了算(ADR 0013 的正面证据)。"""
    from app.domain.generation.resolution import generation_options

    return [
        one for one in generation_options(db, "video", user_id=actor_id)
        if one.get("adapter_available") and mode in ((one.get("capabilities") or {}).get("modes") or ())
    ]


def _pick_model(db: Session, choice: str, mode: str) -> dict[str, Any]:
    options = talking_models(db, mode, current_actor(db))
    if choice:
        picked = next((one for one in options if one["id"] == choice), None)
        if picked is None:
            raise WorkflowDomainError("wfErr_talkingModelMissing")
        return picked
    #: 没点名:他设的默认视频模型正好会这一种就用它,否则用第一个会的。一个都没有就说该去接哪一种。
    picked = next((one for one in options if one.get("is_default")), None) or (options[0] if options else None)
    if picked is None:
        raise WorkflowDomainError("wfErr_talkingNoModel" if mode == SPEECH_TO_VIDEO else "wfErr_lipsyncNoModel")
    return picked


def _require_voice_consent(db: Session, engine: str, voice: str) -> None:
    """克隆音色要有授权声明才能用于数字人(ADR 0028 §5)。引擎自带的嗓子(Edge、各家云端)不是谁的克隆,不问。
    在花钱之前问 —— 配完音才拒,那段配音就白付了。"""
    from app.db.models import Voice
    from app.domain.voices.speech import CLONE_ENGINE
    from app.domain.voices.consent import usable_for_digital_human

    if (engine or CLONE_ENGINE) != CLONE_ENGINE or not voice:
        return
    row = db.get(Voice, voice)
    if row is not None and not usable_for_digital_human(row):
        raise WorkflowDomainError("wfErr_voiceConsentMissing", params={"name": row.name})


def _speak(db: Session, scope: RunScope, text: str, engine: str, voice: str) -> str:
    """稿子配成一段音频(和「配音」节点同一个执行器)。"""
    from app.domain.workflows.executors.subjobs import synthesize_speech

    if not text:
        raise WorkflowDomainError("wfErr_talkingNeedsText")
    if not voice:
        raise WorkflowDomainError("wfErr_talkingNeedsVoice")
    _require_voice_consent(db, engine, voice)
    return synthesize_speech(db, scope, {"text": text, "engine": engine, "voice": voice})["asset_id"]


def _resolution(model: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """节点上挑的分辨率 → 这次生成的参数。只收这个模型描述符里列的档(`resolutions`);空着用模型的默认档。
    此前节点不给这一项、一律 `parameters={}`:百炼说话照片永远是 480P,想要 720P 只能去 AI 工作台。"""
    chosen = _text(config.get("resolution"))
    if not chosen:
        return {}
    offered = [str(one) for one in ((model.get("capabilities") or {}).get("resolutions") or [])]
    if chosen not in offered:
        raise WorkflowDomainError("wfErr_talkingResolution", params={
            "value": chosen, "model": str(model.get("label") or model.get("model") or ""),
            "options": " / ".join(offered) or "—",
        })
    return {"resolution": chosen}


def _generate(db: Session, scope: RunScope, model: dict[str, Any], sources: list[dict[str, str]],
              parameters: dict[str, Any] | None = None, *, project_id: str | None = None) -> list[str]:
    """一次视频生成,交回出的视频。不收提示词的模型(说话照片、改口型)提示词就空着 —— 描述符说了算。

    **等生成的时候 `db` 会被交还**(wait_for_job 的 release:commit + close):调用方在这之前取到的 ORM 对象,
    之后都是脱离会话的,要用就按 id 重新取。`project_id`:产出挂在哪个项目下(译配对口型挂在译配项目里)。"""
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.runner import start_generation_thread

    try:
        generation, child = create_generation_job(
            db,
            workspace_id=scope.workspace_id,
            session_id=None,
            project_id=project_id,
            created_by=current_actor(db),
            provider=model["provider"],
            provider_profile_id=model["provider_profile_id"],
            model=model["model"],
            kind="video",
            prompt="",
            negative_prompt="",
            parameters=dict(parameters or {}),
            source_assets=sources,
            #: 授权在这一层查过了:人物资产的声明(check_entity_speak)或面板上的确认(_require_consent)。
            digital_human_consent=True,
        )
    except GenerationDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.commit()
    generation_id, child_id = generation.id, child.id
    start_generation_thread(generation_id)
    final = wait_for_job(child_id, release=db)
    return [str(one) for one in ((final.result or {}).get("asset_ids") or []) if one]


def _require_consent(config: dict[str, Any]) -> None:
    if _text(config.get("consent")) != CONSENT_GIVEN:
        raise WorkflowDomainError("wfErr_talkingNeedsConsent")


def _portrait(db: Session, entity: Any) -> str:
    """人物说话用哪张脸:正面 > 全身 > 挑图先后的第一张(变体没有自己的图时用母体的)。"""
    from app.domain.entities import generation_profile, references_of

    _name, _descriptor, images = generation_profile(db, entity)
    if not images:
        raise WorkflowDomainError("wfErr_entityNeedsImage", params={"name": entity.name})
    roles = {ref.asset_id: ref.role for ref, _asset in references_of(db, entity.id)}
    for wanted in ("front", "full_body"):
        hit = next((one for one in images if roles.get(one) == wanted), None)
        if hit:
            return hit
    return images[0]


def check_entity_speak(db: Session, workspace_id: str, config: dict[str, Any], actor_id: str | None) -> dict[str, Any]:
    """人物说话之前的全部检查,**不花钱、不写东西**:是人物、真人有授权声明、有音色、有图、有会说话照片的模型、有稿子。
    节点跑的时候先过它;资产详情页点「让它说话」时也先过它(domain/entities/drawing),说不通的当场说。"""
    from app.domain.entities import EntityDomainError, get_entity
    from app.domain.entities.catalog import usable_for_digital_human

    entity_id = _text(config.get("entity_id"))
    if not entity_id:
        raise WorkflowDomainError("wfErr_entityNeedsTarget")
    try:
        entity = get_entity(db, workspace_id, entity_id)
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if entity.kind != "character":
        raise WorkflowDomainError("wfErr_entitySpeakCharacterOnly", params={"name": entity.name})
    attributes = dict(entity.attributes or {})
    if not usable_for_digital_human(attributes):
        raise WorkflowDomainError("wfErr_entitySpeakNoConsent", params={"name": entity.name})
    voice = _text(attributes.get("voice_id"))
    if not voice:
        raise WorkflowDomainError("wfErr_entitySpeakNoVoice", params={"name": entity.name})
    _require_voice_consent(db, _text(attributes.get("voice_engine")), voice)
    if not _text(config.get("text")):
        raise WorkflowDomainError("wfErr_talkingNeedsText")
    options = talking_models(db, SPEECH_TO_VIDEO, actor_id)
    choice = _text(config.get("model"))
    model = (next((one for one in options if one["id"] == choice), None) if choice
             else next((one for one in options if one.get("is_default")), None) or (options[0] if options else None))
    if model is None:
        raise WorkflowDomainError("wfErr_talkingModelMissing" if choice else "wfErr_talkingNoModel")
    return {"face": _portrait(db, entity), "engine": _text(attributes.get("voice_engine")), "voice": voice, "model": model,
            "parameters": _resolution(model, config)}


@register("entity_speak")
def entity_speak(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """人物资产说一段话:它自己的音色配音 → 它的正面图 + 这段配音做说话照片。"""
    plan = check_entity_speak(db, scope.workspace_id, config, current_actor(db))
    audio = _speak(db, scope, _text(config.get("text")), plan["engine"], plan["voice"])
    videos = _generate(db, scope, plan["model"], [{"asset_id": plan["face"], "role": FIRST_FRAME},
                                                   {"asset_id": audio, "role": DRIVING_AUDIO}], plan["parameters"])
    return {"asset_id": videos[0] if videos else "", "asset_ids": videos, "audio_asset_id": audio}


@register("image_speak")
def image_speak(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一张人像说一段话:音频接上游的(比如长稿分段配好的一段),没接就用稿子和挑的嗓子当场配 → 这张图 + 这段音频做说话照片。"""
    from app.domain.workflows.executors.subjobs import _asset_in

    _require_consent(config)
    face = _text(config.get("asset_id"))
    if not face:
        raise WorkflowDomainError("wfErr_talkingNeedsFace")
    #: 收进本工作区:别处的 id 不能借这一步被拿去生成。
    face = _asset_in(db, scope, face).id
    model = _pick_model(db, _text(config.get("model")), SPEECH_TO_VIDEO)
    parameters = _resolution(model, config)
    given = _text(config.get("audio_asset_id"))
    if given:
        given = _asset_in(db, scope, given).id
    audio = given or _speak(db, scope, _text(config.get("text")), _text(config.get("engine")), _text(config.get("voice")))
    videos = _generate(db, scope, model, [{"asset_id": face, "role": FIRST_FRAME}, {"asset_id": audio, "role": DRIVING_AUDIO}],
                       parameters)
    #: 用的是上游现成的音频时不交回它(和对口型同一条)。
    return {"asset_id": videos[0] if videos else "", "asset_ids": videos, "audio_asset_id": "" if given else audio}


@register("video_lipsync")
def video_lipsync(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一段片子对上新的话:音频接上游的,没接就用稿子当场配 → 改口型。"""
    from app.domain.workflows.executors.subjobs import _asset_in

    _require_consent(config)
    video = _text(config.get("asset_id"))
    if not video:
        raise WorkflowDomainError("wfErr_talkingNeedsVideo")
    video = _asset_in(db, scope, video).id
    model = _pick_model(db, _text(config.get("model")), VIDEO_LIPSYNC)
    given = _text(config.get("audio_asset_id"))
    if given:
        given = _asset_in(db, scope, given).id
    audio = given or _speak(db, scope, _text(config.get("text")), _text(config.get("engine")), _text(config.get("voice")))
    videos = _generate(db, scope, model, [{"asset_id": video, "role": SOURCE_VIDEO}, {"asset_id": audio, "role": DRIVING_AUDIO}])
    #: 用的是上游现成的音频时不交回它 —— 画板上不多出一格重复的音频。
    return {"asset_id": videos[0] if videos else "", "asset_ids": videos, "audio_asset_id": "" if given else audio}


#: 一句话在哪儿断:句末标点(中英文)和换行。标点留在句子里,字幕照原样显示。
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;…])|(?<=\.)\s+|\n+")
#: 一句太长(念出来超过一段的上限)时再按逗号、顿号断一次。
_CLAUSE_END = re.compile(r"(?<=[，,、：:])")
#: 估一句念多久:中文每秒约 4 个字。只用来决定要不要预先按逗号断开 —— 分组看的是配出来的实际时长。
_CHARS_PER_SECOND = 4.0


def split_script(text: str, max_seconds: float) -> list[str]:
    """把稿子切成一句一句(长稿分段的第一步,ADR 0028 阶段 3)。估着念出来超过一段上限的长句,再按逗号断开。"""
    sentences: list[str] = []
    for piece in _SENTENCE_END.split(text or ""):
        piece = (piece or "").strip()
        if not piece:
            continue
        if len(piece) / _CHARS_PER_SECOND <= max_seconds:
            sentences.append(piece)
            continue
        clause = ""
        for part in _CLAUSE_END.split(piece):
            if clause and len(clause + part) / _CHARS_PER_SECOND > max_seconds:
                sentences.append(clause.strip())
                clause = ""
            clause += part
        if clause.strip():
            sentences.append(clause.strip())
    return sentences


def _duration(asset: Any) -> float:
    """这段音频多长(秒):素材库登记时量过;没量到就现量一次。"""
    from app.media.paths import resolve_key
    from app.media.probe import probe_media

    seconds = (asset.media_info or {}).get("duration")
    if seconds is None and asset.file_key:
        seconds = probe_media(resolve_key(asset.file_key)).get("duration")
    return float(seconds or 0.0)


def _concat_audio(db: Session, scope: RunScope, assets: list[Any], name: str) -> str:
    """几段配音首尾相接成一段(一组句子交给说话照片的那一段),登记进素材库。"""
    import tempfile

    from app.core.child_process import run_logged
    from app.domain.assets.importer import register_file_asset
    from app.media.paths import resolve_key

    sources = [resolve_key(str(asset.file_key)) for asset in assets]
    with tempfile.TemporaryDirectory(prefix="mosael-talking-") as folder:
        target = Path(folder) / "segment.wav"
        inputs = [part for path in sources for part in ("-i", str(path))]
        chain = "".join(f"[{index}:a]" for index in range(len(sources))) + f"concat=n={len(sources)}:v=0:a=1[out]"
        result = run_logged([settings.ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", chain, "-map", "[out]",
                             "-ac", "1", "-ar", "24000", str(target)],
                            capture_output=True, text=True, timeout=300, what="口播分段拼接")
        if result.returncode != 0 or not target.exists():
            raise WorkflowDomainError("wfErr_talkingConcatFailed")
        joined = register_file_asset(db, workspace_id=scope.workspace_id, project_id=None, source_path=target,
                                     name=name, source="tts")
    #: 几句是同一把克隆嗓子配的:拼好的这段也记着它 —— 拿去别处做数字人时,漏斗照它查授权声明
    #: (generation.operations.check_digital_human_rights)。
    voices = {str((asset.media_info or {}).get("voice_id") or "") for asset in assets}
    if len(voices) == 1 and "" not in voices:
        joined.media_info = {**(joined.media_info or {}), "voice_id": voices.pop()}
    return joined.id


def _pad_audio(db: Session, scope: RunScope, asset: Any, seconds: float, name: str) -> str:
    """一段配音末尾补静音到 `seconds`,登记成新的一段(原来那段不动)。克隆嗓子的出处照带(见 _concat_audio)。"""
    import tempfile

    from app.core.child_process import run_logged
    from app.domain.assets.importer import register_file_asset
    from app.media.paths import resolve_key

    with tempfile.TemporaryDirectory(prefix="mosael-talking-") as folder:
        target = Path(folder) / "segment.wav"
        result = run_logged([settings.ffmpeg, "-y", "-v", "error", "-i", str(resolve_key(str(asset.file_key))),
                             "-af", f"apad=whole_dur={seconds:g}", "-ac", "1", "-ar", "24000", str(target)],
                            capture_output=True, text=True, timeout=300, what="口播分段补静音")
        if result.returncode != 0 or not target.exists():
            raise WorkflowDomainError("wfErr_talkingConcatFailed")
        padded = register_file_asset(db, workspace_id=scope.workspace_id, project_id=None, source_path=target,
                                     name=name, source="tts")
    voice = str((asset.media_info or {}).get("voice_id") or "")
    if voice:
        padded.media_info = {**(padded.media_info or {}), "voice_id": voice}
    return padded.id


@register("talking_segments")
def talking_segments(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """长稿分段配音(ADR 0028 阶段 3「稿子 → 数字人口播」):一段稿子 → 一组组**说话照片接得住**的音频 + 字幕时间。

    说话照片的驱动音频有上限(wan2.2-s2v 20 秒,描述符的 `source_duration_seconds.driving_audio`),长稿要切。
    **按句切、按实测时长分组**:逐句配音(配音本来就逐句合成),把相邻的句子凑成一组、每组配出来的总长不超过上限,
    一组的几句拼成一段音频交给一次说话照片。句子不从中间断开,接缝落在句子之间。字幕直接用稿子加这些实测时长,
    不再转写一遍。上限来自所选模型的描述符,不写死;`max_seconds` 只能往小里调。
    """
    from app.domain.workflows.executors.subjobs import _asset_in, synthesize_speech

    text = _text(config.get("text"))
    if not text:
        raise WorkflowDomainError("wfErr_talkingNeedsText")
    engine, voice = _text(config.get("engine")), _text(config.get("voice"))
    if not voice:
        raise WorkflowDomainError("wfErr_talkingNeedsVoice")
    #: 这些段都是要交给数字人的:克隆音色要有授权声明,在配第一句之前就问。
    _require_voice_consent(db, engine, voice)
    model = _pick_model(db, _text(config.get("model")), SPEECH_TO_VIDEO)
    limits = ((model.get("capabilities") or {}).get("source_duration_seconds") or {}).get(DRIVING_AUDIO) or [1, 20]
    floor, ceiling = float(limits[0]), float(limits[1])
    try:
        wanted = float(config.get("max_seconds") or 0)
    except (TypeError, ValueError):
        wanted = 0.0
    if 0 < wanted < ceiling:
        ceiling = wanted

    voiced: list[tuple[str, Any, float]] = []
    for sentence in split_script(text, ceiling):
        asset = _asset_in(db, scope, synthesize_speech(db, scope, {"text": sentence, "engine": engine, "voice": voice})["asset_id"])
        seconds = _duration(asset)
        if seconds > ceiling:
            raise WorkflowDomainError("wfErr_talkingSentenceTooLong",
                                      params={"sentence": sentence[:40], "seconds": f"{seconds:.1f}", "limit": f"{ceiling:g}"})
        voiced.append((sentence, asset, seconds))
    if not voiced:
        raise WorkflowDomainError("wfErr_talkingNeedsText")

    groups: list[list[tuple[str, Any, float]]] = [[]]
    for one in voiced:
        if groups[-1] and sum(item[2] for item in groups[-1]) + one[2] > ceiling:
            groups.append([])
        groups[-1].append(one)

    segments: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    for index, group in enumerate(groups, start=1):
        name = f"{scope.name} · 口播第 {index} 段"
        audio = str(group[0][1].id) if len(group) == 1 else _concat_audio(db, scope, [item[1] for item in group], name)
        start = cursor
        for sentence, _asset, seconds in group:
            cues.append({"start": round(cursor, 3), "end": round(cursor + seconds, 3), "text": sentence})
            cursor += seconds
        spoken = cursor - start
        if spoken < floor:
            #: 不够模型的下限(可灵数字人 2 秒起):末尾补静音补到下限。此前分组只看上限,一句「好的。」单独成段,
            #: 到提交时才被拒。并进邻居是做不到的 —— 分组是贪心的,一组收尾正是因为下一句放不进去。说话照片在
            #: 静音处闭着嘴,比被拒强;时间线上这一段按补过的长度排,后面几段接着往后。
            audio = _pad_audio(db, scope, _asset_in(db, scope, audio), floor, name)
            cursor = start + floor
        segments.append({"index": index, "audio_asset_id": audio, "start": round(start, 3),
                         "duration": round(cursor - start, 3), "text": "".join(item[0] for item in group)})
    return {"segments": segments, "cues": cues, "count": len(segments), "duration": round(cursor, 3)}
