from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ProviderDefault, ProviderModel, ProviderProfile

"""每种能力的默认供应商解析(统一到 ProviderProfile)。
capability: chat / image / video / tts / podcast。"""

#: 能设默认模型的那几种能力。它曾经和 providers.ALL_CAPABILITY_IDS 差一项(embedding),
#: 而那一项在弹窗里没有格子、在模型行上却有标签 —— 有人照着错的那份抄过一次。知识库删掉之后
#: embedding 没有任何消费者,两份因此重新对齐;别再让它们分叉。
DEFAULTABLE_CAPABILITIES = ("chat", "image", "video", "tts", "podcast")


def get_row(db: Session, capability: str, user_id: str | None) -> ProviderDefault | None:
    """这个人在这项能力下的默认:**他自己那一条,没有就没有**。

    这里没有回退。曾经有过「部署默认」作为兜底 —— 一行 `owner_user_id=""`,给"还没设过的人"
    当起点 —— 删掉了。它看起来温和(只在你没设时才生效),但造成的正是这个应用里反复出现的
    那种误解:界面上你没选过任何模型,回答却来自某个你不知道的模型,花的是你的额度、用的是
    你的钥匙,而你从没同意过。

    和凭据解析同一个形状(见 domain/provider_credentials.pick),理由也同一条:替人做的选择
    必须是他自己做的。
    """
    if not user_id:
        return None
    return db.get(ProviderDefault, {"capability": capability, "owner_user_id": user_id})


def set_default(
    db: Session, capability: str, model: ProviderModel | None, *, owner_user_id: str
) -> None:
    """把**某个人**某项能力的默认指到一行模型上。`None` = 清除。

    只写他自己那一条。没有"替所有人写一条"这回事(见 get_row)。

    写在这里而不是 provider_models 里:ProviderDefault 归本模块所有(见 domain/ownership.py),
    跨域直接构造会绕过归属约束 —— 棘轮测试当场拦下过。

    """
    row = db.get(ProviderDefault, {"capability": capability, "owner_user_id": owner_user_id})
    if row is None:
        row = ProviderDefault(capability=capability, owner_user_id=owner_user_id)
        db.add(row)
    row.provider_model_id = model.id if model is not None else None
