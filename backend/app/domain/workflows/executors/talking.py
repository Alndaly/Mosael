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

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers.contracts.generation import DRIVING_AUDIO, FIRST_FRAME, SOURCE_VIDEO
from app.domain.jobs import current_actor
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import RunScope, register
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


def _speak(db: Session, scope: RunScope, text: str, engine: str, voice: str) -> str:
    """稿子配成一段音频(和「配音」节点同一个执行器)。"""
    from app.domain.workflows.executors.subjobs import synthesize_speech

    if not text:
        raise WorkflowDomainError("wfErr_talkingNeedsText")
    if not voice:
        raise WorkflowDomainError("wfErr_talkingNeedsVoice")
    return synthesize_speech(db, scope, {"text": text, "engine": engine, "voice": voice})["asset_id"]


def _generate(db: Session, scope: RunScope, model: dict[str, Any], sources: list[dict[str, str]]) -> list[str]:
    """一次视频生成,交回出的视频。不收提示词的模型(说话照片、改口型)提示词就空着 —— 描述符说了算。"""
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.runner import start_generation_thread

    try:
        generation, child = create_generation_job(
            db,
            workspace_id=scope.workspace_id,
            session_id=None,
            project_id=None,
            created_by=current_actor(db),
            provider=model["provider"],
            provider_profile_id=model["provider_profile_id"],
            model=model["model"],
            kind="video",
            prompt="",
            negative_prompt="",
            parameters={},
            source_assets=sources,
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
    if not _text(config.get("text")):
        raise WorkflowDomainError("wfErr_talkingNeedsText")
    options = talking_models(db, SPEECH_TO_VIDEO, actor_id)
    choice = _text(config.get("model"))
    model = (next((one for one in options if one["id"] == choice), None) if choice
             else next((one for one in options if one.get("is_default")), None) or (options[0] if options else None))
    if model is None:
        raise WorkflowDomainError("wfErr_talkingModelMissing" if choice else "wfErr_talkingNoModel")
    return {"face": _portrait(db, entity), "engine": _text(attributes.get("voice_engine")), "voice": voice, "model": model}


@register("entity_speak")
def entity_speak(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """人物资产说一段话:它自己的音色配音 → 它的正面图 + 这段配音做说话照片。"""
    plan = check_entity_speak(db, scope.workspace_id, config, current_actor(db))
    audio = _speak(db, scope, _text(config.get("text")), plan["engine"], plan["voice"])
    videos = _generate(db, scope, plan["model"], [{"asset_id": plan["face"], "role": FIRST_FRAME},
                                                   {"asset_id": audio, "role": DRIVING_AUDIO}])
    return {"asset_id": videos[0] if videos else "", "asset_ids": videos, "audio_asset_id": audio}


@register("image_speak")
def image_speak(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一张人像说一段话:稿子用挑的嗓子配音 → 这张图 + 这段配音做说话照片。"""
    from app.domain.workflows.executors.subjobs import _asset_in

    _require_consent(config)
    face = _text(config.get("asset_id"))
    if not face:
        raise WorkflowDomainError("wfErr_talkingNeedsFace")
    #: 收进本工作区:别处的 id 不能借这一步被拿去生成。
    face = _asset_in(db, scope, face).id
    model = _pick_model(db, _text(config.get("model")), SPEECH_TO_VIDEO)
    audio = _speak(db, scope, _text(config.get("text")), _text(config.get("engine")), _text(config.get("voice")))
    videos = _generate(db, scope, model, [{"asset_id": face, "role": FIRST_FRAME}, {"asset_id": audio, "role": DRIVING_AUDIO}])
    return {"asset_id": videos[0] if videos else "", "asset_ids": videos, "audio_asset_id": audio}


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
