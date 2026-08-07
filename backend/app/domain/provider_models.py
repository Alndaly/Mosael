"""模型作为一等实体:解析、能力、以及发给运行时的那份参数。

这个模块是 `ProviderModel` 的拥有方(见 domain/ownership.py)。它回答三个问题:

  1. **这条连接下有哪些模型** —— 已配置的行,与供应商目录合并由上层做;
  2. **某个能力该用哪个模型** —— ProviderDefault 指向的那一行;
  3. **发给运行时的参数是什么** —— 上下文窗口、推理/视觉/兼容开关,取模型行上的显式设置,
     没设就留空由下游回落。

**能力在模型上而不是连接上**:同一个端点既可能有对话模型也可能有生图模型,挂在连接上就只能
二选一 —— 这正是此前用户被迫"拿模型名当档案名"建一堆档案的原因。模型行的 capability_ids
为空时回落 vendor 预设,让老数据和"没细分过"的连接仍然work。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderDefault, ProviderModel, ProviderProfile
from app.domain.providers import capability_ids_for_vendor, normalize_capability_ids

#: 模型行上可被用户覆盖的运行时参数。留空表示跟随目录/保守默认 —— 与 False 是两回事。
RUNTIME_FIELDS = ("context_window", "max_output_tokens", "reasoning", "vision", "reasoning_effort", "developer_role")


def effective_capabilities(model: ProviderModel) -> list[str]:
    """模型实际生效的能力。行上没写就回落 vendor 预设 —— 回填来的老数据、以及用户还没细分过
    的连接都走这条路,不至于因为"没填"就变成"什么都不能做"。"""
    own = normalize_capability_ids(model.capability_ids or [])
    if own:
        return own
    profile = model.profile
    return capability_ids_for_vendor(profile.vendor) if profile is not None else []


def list_models(db: Session, profile_id: str, *, enabled_only: bool = False) -> list[ProviderModel]:
    stmt = select(ProviderModel).where(ProviderModel.provider_profile_id == profile_id)
    if enabled_only:
        stmt = stmt.where(ProviderModel.enabled.is_(True))
    return list(db.scalars(stmt.order_by(ProviderModel.model_id)))


def get_model(db: Session, profile_id: str, model_id: str) -> ProviderModel | None:
    """这条连接下这个模型的配置行;没配置过就是 None(仍可使用,只是没有任何覆盖)。"""
    if not profile_id or not model_id:
        return None
    return db.scalars(
        select(ProviderModel).where(
            ProviderModel.provider_profile_id == profile_id, ProviderModel.model_id == model_id
        )
    ).first()


def models_for_capability(db: Session, capability: str) -> list[ProviderModel]:
    """所有启用且声明了该能力的模型(其连接也必须是启用的)。

    选择器据此列项 —— 此前列的是"档案",于是同一个端点的对话模型和生图模型没法分别出现。
    """
    rows = db.scalars(
        select(ProviderModel).join(ProviderProfile).where(
            ProviderModel.enabled.is_(True), ProviderProfile.enabled.is_(True)
        )
    ).all()
    return [model for model in rows if capability in effective_capabilities(model)]


def resolve_default(db: Session, capability: str, user_id: str | None = None) -> ProviderModel | None:
    """**这个人**在某能力下的默认模型行。

    顺序:**他自己设的 → 没有**。就这两档。

    两层兜底先后删掉了,理由是同一条。先是"该能力下第一个可用模型":它的失败方式跑出来过 ——
    界面显示 DeepSeek、回答却是「我是 Kimi」,那个"第一个"碰巧是订阅计划连接,而订阅走它自己的
    provider 定义(自带身份、自带思考)。后是"部署默认":温和得多,只在你没设过时生效,但造成
    的是同一种误解 —— 你没选过任何模型,回答却来自某个你不知道的模型,花你的额度、用你的钥匙。

    **任何"替他挑一个"都在没有答案时编一个,而编出来的那个看起来像答案。**

    `user_id` 给 None(后台里确实没有人的那些路径)时直接回 None:没有人,就没有他的默认。
    """
    from app.domain.provider_defaults import get_row

    row = get_row(db, capability, user_id)
    if row is not None and row.provider_model_id:
        model = db.get(ProviderModel, row.provider_model_id)
        if model is not None and model.enabled and model.profile is not None and model.profile.enabled:
            return model
    return None


def runtime_limits(model: ProviderModel | None) -> dict[str, Any]:
    """发给运行时的那份参数。**只带用户显式设过的键** —— 带上 None 会让下游分不清
    "没设过"和"显式设成了空",而这两者的默认行为完全不同。"""
    if model is None:
        return {}
    values: dict[str, Any] = {}
    for field in RUNTIME_FIELDS:
        value = getattr(model, field, None)
        if value is not None:
            values[field] = value
    return values


def upsert(
    db: Session,
    profile: ProviderProfile,
    model_id: str,
    *,
    source: str = "manual",
    capability_ids: list[str] | None = None,
    **fields: Any,
) -> ProviderModel:
    """新增或更新一行。这是**唯一**建 ProviderModel 的地方(数据归属棘轮会盯着)。"""
    model_id = (model_id or "").strip()
    if not model_id:
        raise ValueError("模型 id 不能为空")
    model = get_model(db, profile.id, model_id)
    if model is None:
        model = ProviderModel(
            provider_profile_id=profile.id,
            model_id=model_id,
            source=source,
            capability_ids=normalize_capability_ids(capability_ids or []) or [],
        )
        db.add(model)
    elif capability_ids is not None:
        model.capability_ids = normalize_capability_ids(capability_ids) or []
    for key, value in fields.items():
        if key in RUNTIME_FIELDS or key in ("enabled", "display_name"):
            setattr(model, key, value)
    db.flush()
    return model


def model_id_for(
    db: Session, profile: ProviderProfile | None, capability: str, user_id: str | None = None
) -> str:
    """这条连接在某能力下该用的模型 id。取不到返回空串。

    取代了此前散在二十来处的 `profile.default_model` —— 那个字段是"一档案一模型"时代的写法,
    同一条连接有多个模型时它给不出答案,而它给出的那一个还可能根本不提供所问的能力
    (对话档案的 default_model 被拿去当生图模型用过)。

    顺序:全局默认若正好指在这条连接上,用它;否则用这条连接下第一个提供该能力的启用模型。
    """
    if profile is None:
        return ""
    chosen = resolve_default(db, capability, user_id)
    if chosen is not None and chosen.provider_profile_id == profile.id:
        return chosen.model_id
    for model in list_models(db, profile.id, enabled_only=True):
        if capability in effective_capabilities(model):
            return model.model_id
    return ""


def profile_capabilities(db: Session, profile: ProviderProfile) -> list[str]:
    """这条连接对外提供的能力 = 它下面所有启用模型能力的并集。

    还没有任何模型行时回落 vendor 预设 —— 刚建好的连接应当能出现在对应的能力分区里,
    否则用户会看到"我建了个 Kimi 档案,但对话那栏找不到它"。
    """
    seen: list[str] = []
    for model in list_models(db, profile.id, enabled_only=True):
        for capability in effective_capabilities(model):
            if capability not in seen:
                seen.append(capability)
    return seen or capability_ids_for_vendor(profile.vendor)
