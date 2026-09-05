from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AgentVoiceOut, AgentVoiceUpdate, CapabilityModelOut, ProviderDefaultOut, ProviderDefaultUpdate
from app.db.models import ProviderModel
from app.domain import provider_models
from app.domain.provider_defaults import DEFAULTABLE_CAPABILITIES, set_default
from app.domain.providers import capability_ids_for_vendor

from .provider_profiles import _require_profile

router = APIRouter(tags=["settings"])

@router.get("/settings/provider-defaults", response_model=list[ProviderDefaultOut])
def list_provider_defaults(db: DbSession, user: CurrentUser) -> list[ProviderDefaultOut]:
    """**我**在每种能力下的默认供应商+模型。我没设过的就是空 —— 没有部署兜底那一档。"""
    from app.domain.provider_defaults import get_row

    out: list[ProviderDefaultOut] = []
    for capability in DEFAULTABLE_CAPABILITIES:
        row = get_row(db, capability, user.id)
        # 默认只存一处(指向模型行),连接与模型名从那一行推导出来给界面。
        model = db.get(ProviderModel, row.provider_model_id) if row and row.provider_model_id else None
        out.append(
            ProviderDefaultOut(
                capability=capability,
                provider_profile_id=model.provider_profile_id if model else None,
                model=model.model_id if model else "",
                # 恒真:能拿到行就说明是我自己设的(get_row 只查我这一条)。字段留着是因为
                # 前端还在读它,而且它现在表达的是"这一格有没有被我设过"。
                is_mine=row is not None,
            )
        )
    return out


@router.get("/settings/capability-models/{capability}", response_model=list[CapabilityModelOut])
def list_capability_models(
    capability: str,
    db: DbSession,
    user: CurrentUser,
    surface: Literal["all", "agent", "direct", "gateway", "automation"] = "all",
) -> list[CapabilityModelOut]:
    """某能力下所有可用模型,跨连接。**任何登录用户都读得到** —— 挡住它等于让人闭着眼睛
    选自己的默认模型(见 tests/test_who_owns_each_setting.py)。

    界面直接列它,而不是"先选供应商再选模型" —— 后者是模型还不是实体时的形状,逼着用户
    先知道"这个模型在哪条连接下",而那恰恰是他不关心的事。
    """
    if capability not in DEFAULTABLE_CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    return [
        CapabilityModelOut(
            provider_profile_id=model.provider_profile_id,
            provider_name=model.profile.name if model.profile is not None else "",
            model=model.model_id,
            display_name=model.display_name or "",
            # 思考能力跟着模型走:有的完全不思考,有的只能开/关,有的才分档。
            # 界面据此决定给几个选项 —— 给一个点了没用的开关,比没有这个开关更坏。
            reasoning=model.reasoning,
            reasoning_effort=model.reasoning_effort,
        )
        for model in provider_models.models_for_capability(db, capability, user.id, surface=surface)
    ]


@router.put("/settings/provider-defaults/{capability}", response_model=ProviderDefaultOut)
def set_provider_default(
    capability: str, body: ProviderDefaultUpdate, db: DbSession, user: CurrentUser
) -> ProviderDefaultOut:
    """设**我自己**在这项能力下的默认模型。**只有这一档。**

    不要求部署管理员:「我默认用哪个模型」是个人偏好,和钥匙一样(见 db.models.ProviderDefault)。
    曾经有过 `for_deployment` —— 写那一行 `owner_user_id=""` 当作"还没设过的人的起点" ——
    删掉了:替人做的选择必须是他自己做的(见 domain/provider_defaults.get_row)。
    """
    if capability not in DEFAULTABLE_CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    model = None
    model_id = body.model.strip()
    if body.provider_profile_id and model_id:
        profile = _require_profile(db, body.provider_profile_id, user)
        model = provider_models.get_model(db, body.provider_profile_id, model_id)
        # 能力校验放在建行之前:先建再拒会在库里留下一行没人要的模型。
        # 已有行按它自己的能力判,没有行按 vendor 预设判(新行正是这么回落的)。
        capabilities = (
            provider_models.effective_capabilities(model)
            if model is not None
            else capability_ids_for_vendor(profile.vendor)
        )
        if capability not in capabilities:
            raise HTTPException(status_code=422, detail=f"该模型不提供 {capability} 能力")
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




@router.get("/settings/agent-voice", response_model=AgentVoiceOut)
def get_agent_voice(db: DbSession, user: CurrentUser) -> AgentVoiceOut:
    """**我**在语音对话里用哪个音色。没设过就回一份空的(enabled=False)。

    和 /settings/provider-defaults 的 tts 那一格是两回事:配音要质量(本地克隆、首次加载
    十几分钟也认),对话要延迟。同一个默认服务两件事,必然在某一边是错的。
    """
    from app.domain.voices import agent_voice

    row = agent_voice.get_row(db, user.id)
    if row is None:
        return AgentVoiceOut()
    return AgentVoiceOut(
        engine=row.engine,
        engine_voice=row.engine_voice,
        engine_voice_resource=row.engine_voice_resource,
        engine_model=row.engine_model,
        provider_profile_id=row.provider_profile_id,
        voice_id=row.voice_id,
        speed=row.speed,
        enabled=row.enabled,
    )


@router.put("/settings/agent-voice", response_model=AgentVoiceOut)
def set_agent_voice(body: AgentVoiceUpdate, db: DbSession, user: CurrentUser) -> AgentVoiceOut:
    """设**我自己**的对话音色。只有这一档 —— 没有部署默认(同 provider-defaults)。"""
    from app.domain.voices import agent_voice

    row = agent_voice.upsert(
        db,
        user.id,
        engine=body.engine,
        engine_voice=body.engine_voice,
        engine_voice_resource=body.engine_voice_resource,
        engine_model=body.engine_model,
        provider_profile_id=body.provider_profile_id,
        voice_id=body.voice_id,
        speed=body.speed,
        enabled=body.enabled,
    )
    return AgentVoiceOut(
        engine=row.engine,
        engine_voice=row.engine_voice,
        engine_voice_resource=row.engine_voice_resource,
        engine_model=row.engine_model,
        provider_profile_id=row.provider_profile_id,
        voice_id=row.voice_id,
        speed=row.speed,
        enabled=row.enabled,
    )
