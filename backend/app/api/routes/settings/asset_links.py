"""素材外链用哪一家存储 —— 「设置 → 素材外链」。

生成模型的某些输入只收链接(方舟 Seedance 的参考视频、视频编辑的源视频……不止视频一种),本地素材要先传到对象存储换一条直链
(见 domain/generation/public_links)。配了几家存储时,用哪一家是**个人的选择**,和默认模型
一样放在设置里,而且**自己一页** —— 不挂在「AI 视频」下面(只收链接的不止视频),也不放在插件页每一家的连接上:那样是几个互相牵制的开关,打开一家会悄悄
关掉另一家,想知道现在用的是哪家还得挨个点开看。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AssetLinkStorageOut, AssetLinkStorageUpdate
from app.domain.generation.public_links import PUBLIC_URL, storage_choices
from app.domain.plugins import capability_defaults
from app.domain.plugins.errors import PluginDomainError

router = APIRouter(tags=["settings"])


@router.get("/settings/asset-link-storage", response_model=AssetLinkStorageOut)
def get_asset_link_storage(db: DbSession, user: CurrentUser) -> dict:
    return storage_choices(db, user.id)


@router.put("/settings/asset-link-storage", response_model=AssetLinkStorageOut)
def set_asset_link_storage(body: AssetLinkStorageUpdate, db: DbSession, user: CurrentUser) -> dict:
    try:
        capability_defaults.set_default(db, user.id, PUBLIC_URL, body.instance_id)
    except PluginDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return storage_choices(db, user.id)
