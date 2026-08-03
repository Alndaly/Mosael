from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ProviderDefault, ProviderModel, ProviderProfile

"""每种能力的默认供应商解析(统一到 ProviderProfile)。
capability: chat / image / video / tts / podcast(embedding 走 KbEmbeddingConfig)。"""

#: **能设默认模型的**那几种能力 —— 不是"系统里有哪些能力"(那是 providers.ALL_CAPABILITY_IDS,
#: 六项,多一个 embedding)。名字叫得像同一件事的三份拷贝,已经让人照着错的那份抄过一次:
#: 模型设置弹窗按这份列了五个格子,而模型行认六个,embedding 于是在行上有标签、在弹窗里没格子。
DEFAULTABLE_CAPABILITIES = ("chat", "image", "video", "tts", "podcast")


def get_row(db: Session, capability: str, user_id: str | None) -> ProviderDefault | None:
    """这个人在这项能力下的默认:**自己的 → 部署的 → 没有**。

    和凭据解析同一个形状(见 domain/provider_credentials.pick)—— 因为它们是同一类东西:
    个人偏好,加上一份"还没设过的人用这个"的部署起点。
    """
    if user_id:
        mine = db.get(ProviderDefault, {"capability": capability, "owner_user_id": user_id})
        if mine is not None:
            return mine
    return db.get(ProviderDefault, {"capability": capability, "owner_user_id": ""})


def set_default(
    db: Session, capability: str, model: ProviderModel | None, *, owner_user_id: str
) -> None:
    """把**某个人**某项能力的默认指到一行模型上。`None` = 清除。

    `owner_user_id=""` 写的是部署默认 —— 授权由路由层把关(只有部署管理员能写那一行)。

    写在这里而不是 provider_models 里:ProviderDefault 归本模块所有(见 domain/ownership.py),
    跨域直接构造会绕过归属约束 —— 棘轮测试当场拦下过。

    """
    row = db.get(ProviderDefault, {"capability": capability, "owner_user_id": owner_user_id})
    if row is None:
        row = ProviderDefault(capability=capability, owner_user_id=owner_user_id)
        db.add(row)
    row.provider_model_id = model.id if model is not None else None
