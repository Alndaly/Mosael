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

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderModel, ProviderProfile
from app.domain.providers import capability_ids_for_vendor, normalize_capability_ids

#: 模型行上可被用户覆盖的运行时参数。留空表示跟随目录/保守默认 —— 与 False 是两回事。
RUNTIME_FIELDS = ("context_window", "max_output_tokens", "reasoning", "vision", "reasoning_effort", "developer_role")


#: 从模型名推能力的线索,按 vendor 给。**只写有把握的**:推错比不推更糟。
#: 顺序有意义 —— 先匹配到的赢(`wan2.7-i2v` 要判成视频,不能被 `image` 那条抢走)。
_CAPABILITY_HINTS: dict[str, tuple[tuple[tuple[str, ...], str], ...]] = {
    "alibaba": (
        (("-i2v", "-t2v", "i2v-", "t2v-"), "video"),
        (("cosyvoice", "-tts", "tts-"), "tts"),
        (("-image", "image-", "wanx"), "image"),
    ),
}


def infer_capabilities(vendor: str, model_id: str) -> list[str]:
    """从模型名推它提供哪种能力;推不出来回空。

    存在的理由:`effective_capabilities` 原本在行上没写能力时回落**整个 vendor 的能力集**。
    那在一家只有一两种能力时无害,而百炼有四种(对话/图像/视频/语音)—— 于是从目录里加一个
    qwen-tts 模型会被声明成"也能做视频",它随即出现在视频生成的下拉里,选了必然失败。
    界面替供应商撒谎,而用户只会以为是自己配错了。

    先查内置目录(那是**验证过的事实**:哪个模型属于哪种生成能力),再按名字线索,都不中就回空。
    """
    name = (model_id or "").strip().lower()
    if not name:
        return []
    from app.domain.generation import builtin_models_for

    for kind in ("image", "video"):
        if any(name == known.lower() for known in builtin_models_for(vendor, kind)):
            return [kind]
    for needles, capability in _CAPABILITY_HINTS.get(vendor, ()):
        if any(needle in name for needle in needles):
            return [capability]
    return []


def effective_capabilities(model: ProviderModel) -> list[str]:
    """模型实际生效的能力。

    顺序:行上写了的 → 从模型名推出来的 → vendor 预设。最后那条是兜底,不至于因为"没填"
    就变成"什么都不能做";但它给的是**整个 vendor 的能力集**,所以能推出来的时候不要用它
    (见 infer_capabilities 里那段说明)。
    """
    own = normalize_capability_ids(model.capability_ids or [])
    if own:
        return own
    profile = model.profile
    if profile is None:
        return []
    inferred = infer_capabilities(profile.vendor, model.model_id)
    return inferred or capability_ids_for_vendor(profile.vendor)


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


ExecutionSurface = Literal["all", "agent", "direct", "gateway", "automation"]


def models_for_capability(
    db: Session,
    capability: str,
    user_id: str | None = None,
    *,
    surface: ExecutionSurface = "all",
) -> list[ProviderModel]:
    """**他自己的**连接下,启用且声明了该能力的模型。

    选择器据此列项 —— 此前列的是"档案",于是同一个端点的对话模型和生图模型没法分别出现。

    `user_id` 是必要的:连接归人(见 db.models.ProviderProfile),不过滤的话选择器会列出别人
    连接下的模型 —— 选中一个之后调用必然失败,因为那条连接他根本看不到、也没有钥匙。
    """
    stmt = select(ProviderModel).join(ProviderProfile).where(
        ProviderModel.enabled.is_(True), ProviderProfile.enabled.is_(True)
    )
    if user_id is not None:
        stmt = stmt.where(ProviderProfile.owner_user_id == user_id)
    rows = db.scalars(stmt).all()
    if surface in {"direct", "gateway", "automation"}:
        # OAuth 订阅由 pi Adapter 持有端点和凭据；后端直连 Adapter 没有 base_url/api_key 可用。
        # 能力同为 chat 只说明模型会对话，不代表两条执行通道可以互换。
        from app.domain import provider_credentials

        def direct(model: ProviderModel) -> bool:
            return (
                model.profile is not None
                and model.profile.auth_type != "oauth"
                and bool((model.profile.base_url or "").strip())
            )

        def gateway(model: ProviderModel) -> bool:
            return (
                user_id is not None
                and model.profile is not None
                and model.profile.auth_type == "oauth"
                and provider_credentials.resolve_connection(db, model.profile, user_id) is not None
            )
        if surface == "direct":
            rows = [model for model in rows if direct(model)]
        elif surface == "gateway":
            rows = [model for model in rows if gateway(model)]
        else:
            rows = [model for model in rows if direct(model) or gateway(model)]
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


def model_id_for_family(
    db: Session, profile: ProviderProfile | None, capability: str, prefixes: tuple[str, ...],
    user_id: str | None = None,
) -> str:
    """同 model_id_for,但**只认某一族**的模型。

    一条连接下可以挂好几个同能力的模型,而有些引擎只吃其中一族:百炼的语音就是两套 API
    (qwen-tts 家族 / CosyVoice),共用一把 Key、共用一条连接,却各自只认自己那一族。
    不筛的话,配了 qwen-tts 的人切到 CosyVoice 引擎会把 qwen 的模型名发去 CosyVoice 的端点,
    得到一句看不懂的 `url error`。
    """
    if profile is None:
        return ""
    def matches(model_id: str) -> bool:
        return model_id.strip().lower().startswith(prefixes)

    chosen = resolve_default(db, capability, user_id)
    if chosen is not None and chosen.provider_profile_id == profile.id and matches(chosen.model_id):
        return chosen.model_id
    for model in list_models(db, profile.id, enabled_only=True):
        if capability in effective_capabilities(model) and matches(model.model_id):
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
