from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import AgentVoiceOut, AgentVoiceUpdate, CapabilityModelOut, ProviderDefaultOut, ProviderDefaultUpdate, VoiceRefBody
from app.domain.providers import choices, models as provider_models
from app.domain.providers.defaults import DEFAULTABLE_CAPABILITIES, set_default

from app.domain.permissions import require_own_profile
from app.domain.voices import agent_voice, use_cases as voice_uc
from app.domain.voices.defaults import UnknownVoiceEngine, VoiceNotInEngine
from app.domain.voices.errors import VoiceError

router = APIRouter(tags=["settings"])

@router.get("/settings/provider-defaults", response_model=list[ProviderDefaultOut])
def list_provider_defaults(db: DbSession, user: CurrentUser) -> list[dict]:
    """**我**在每种能力下的默认供应商 + 模型(见 domain/providers/choices)。"""
    return choices.defaults_of(db, user)


@router.get("/settings/capability-models/{capability}", response_model=list[CapabilityModelOut])
def list_capability_models(
    capability: str,
    db: DbSession,
    user: CurrentUser,
    surface: Literal["all", "agent", "direct", "gateway", "automation"] = "all",
) -> list[dict]:
    """某能力下所有可用模型,跨连接。界面直接列它,而不是「先选供应商再选模型」—— 后者是模型还不是
    实体时的形状,逼着用户先知道「这个模型在哪条连接下」,而那恰恰是他不关心的事。"""
    return choices.capability_models(db, user, capability, surface)


@router.put("/settings/provider-defaults/{capability}", response_model=ProviderDefaultOut)
def set_provider_default(
    capability: str, body: ProviderDefaultUpdate, db: DbSession, user: CurrentUser
) -> ProviderDefaultOut:
    """设**我自己**在这项能力下的默认模型。**只有这一档。**

    不要求部署管理员:「我默认用哪个模型」是个人偏好,和钥匙一样(见 db.models.ProviderDefault)。
    曾经有过 `for_deployment` —— 写那一行 `owner_user_id=""` 当作"还没设过的人的起点" ——
    删掉了:替人做的选择必须是他自己做的(见 domain/providers/defaults.get_row)。
    """
    if capability not in DEFAULTABLE_CAPABILITIES:
        raise HTTPException(status_code=404, detail=tr("routeErr_unknownCapability"))
    model = None
    model_id = body.model.strip()
    if body.provider_profile_id and model_id:
        profile = require_own_profile(db, user, body.provider_profile_id)
        model = provider_models.get_model(db, body.provider_profile_id, model_id)
        # 能力校验放在建行之前:先建再拒会在库里留下一行没人要的模型。
        # 已有行按它自己的能力判,没有行按同一条证据规则判(新行正是这么认的)。
        capabilities = (
            provider_models.effective_capabilities(model)
            if model is not None
            else provider_models.evidenced_capabilities(profile.vendor, model_id)
        )
        if capability not in capabilities:
            raise HTTPException(status_code=422, detail=tr("routeErr_modelLacksCapability", capability=capability))
        if model is None:
            # 设默认时顺手把这一行加上 —— 用户知道模型名但还没加过它是个正常流程,
            # 逼他先去列表里加一遍纯属多一步。
            model = provider_models.upsert(db, profile, model_id, source="manual")
    # 指向模型行(旧的两列由 set_default 同步写,生成侧还在读)。
    set_default(db, capability, model, owner_user_id=user.id)
    db.commit()
    return ProviderDefaultOut(
        capability=capability,
        provider_profile_id=model.provider_profile_id if model is not None else None,
        model=model.model_id if model is not None else "",
        is_mine=True,
    )




def _agent_voice_out(row) -> AgentVoiceOut:
    return AgentVoiceOut(
        voice=VoiceRefBody.of(agent_voice.voice_of(row)),
        speed=row.speed,
        enabled=row.enabled,
        asr_engine=row.asr_engine,
        speak_early=row.speak_early,
    )


@router.get("/settings/agent-voice", response_model=AgentVoiceOut)
def get_agent_voice(db: DbSession, user: CurrentUser) -> AgentVoiceOut:
    """**我**在语音对话里用哪个音色、说话输入用哪一家。没设过就回一份空的(enabled=False)。

    和配音的默认是两回事:配音要质量(本地克隆、首次加载十几分钟也认),对话要延迟。同一个默认服务两件事,
    必然在某一边是错的。
    """

    row = agent_voice.get_row(db, user.id)
    return _agent_voice_out(row) if row is not None else AgentVoiceOut()


@router.put("/settings/agent-voice", response_model=AgentVoiceOut)
def set_agent_voice(body: AgentVoiceUpdate, db: Tx, user: CurrentUser) -> AgentVoiceOut:
    """设**我自己**的对话音色,以及说话输入用哪一家。只有这一档 —— 没有部署默认(同 provider-defaults)。

    存之前照音色目录校验并补齐(音色属于引擎、模型对得上,火山的资源族由目录带上);远端引擎念配音库里的嗓子
    (`cloned_voice`,ADR 0037)时,这个账号还没同意上传就回 409(`remote_voice_consent_required`)。"""

    try:
        row = voice_uc.choose_agent_voice(
            db,
            user,
            voice=body.voice.ref() if body.voice is not None else None,
            speed=body.speed,
            enabled=body.enabled,
            asr_engine=body.asr_engine,
            speak_early=body.speak_early,
        )
    except UnknownVoiceEngine as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (VoiceError, VoiceNotInEngine) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _agent_voice_out(row)
