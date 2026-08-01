from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ProviderDefault, ProviderModel, ProviderProfile

"""每种能力的默认供应商解析(统一到 ProviderProfile)。
capability: chat / image / video / tts / podcast(embedding 走 KbEmbeddingConfig)。"""

#: **能设默认模型的**那几种能力 —— 不是"系统里有哪些能力"(那是 providers.ALL_CAPABILITY_IDS,
#: 六项,多一个 embedding)。名字叫得像同一件事的三份拷贝,已经让人照着错的那份抄过一次:
#: 模型设置弹窗按这份列了五个格子,而模型行认六个,embedding 于是在行上有标签、在弹窗里没格子。
DEFAULTABLE_CAPABILITIES = ("chat", "image", "video", "tts", "podcast")


def resolve_default(db: Session, capability: str) -> tuple[ProviderProfile | None, str]:
    """返回该能力默认的 (启用的 profile, model);未配置或供应商已停用返回 (None, model)。"""
    row = db.get(ProviderDefault, capability)
    if row is None:
        return None, ""
    profile = None
    if row.provider_profile_id:
        profile = db.get(ProviderProfile, row.provider_profile_id)
        if profile is not None and not profile.enabled:
            profile = None
    return profile, row.model


def set_default(db: Session, capability: str, model: ProviderModel | None) -> None:
    """把某能力的默认指到一行模型上。`None` = 清除。

    写在这里而不是 provider_models 里:ProviderDefault 归本模块所有(见 domain/ownership.py),
    跨域直接构造会绕过归属约束 —— 棘轮测试当场拦下过。

    旧的 (provider_profile_id, model) 两列仍然同步写:生成侧还有一批读取点在用它们,
    留下两份会漂移的真相比多写两个字段危险得多。
    """
    row = db.get(ProviderDefault, capability)
    if row is None:
        row = ProviderDefault(capability=capability)
        db.add(row)
    row.provider_model_id = model.id if model is not None else None
    row.provider_profile_id = model.provider_profile_id if model is not None else None
    row.model = model.model_id if model is not None else ""
