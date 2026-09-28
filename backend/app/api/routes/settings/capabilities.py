"""宿主能力用哪一家 —— 「设置 → 能力提供方」(ADR 0031 §5)。

素材外链(本地素材传到哪一家对象存储换直链)、文档解析(本地解析还是 MinerU……)都是**个人的、跨插件的
选择**,和默认模型同类,所以放在设置里、一页列全:放在插件页每一家的连接上,是几个互相牵制的开关 ——
打开一家会悄悄关掉另一家,想知道现在用的是哪家还得挨个点开看。候选和挑法见 domain/capabilities。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import CapabilityChoicesOut, CapabilityDefaultUpdate
from app.domain import capabilities
from app.domain.plugins.errors import PluginDomainError

router = APIRouter(tags=["settings"])


@router.get("/settings/capabilities", response_model=list[CapabilityChoicesOut])
def list_capability_choices(db: DbSession, user: CurrentUser) -> list[dict]:
    return [capabilities.choices(db, user.id, one) for one in capabilities.registered()]


@router.put("/settings/capabilities/{name}", response_model=CapabilityChoicesOut)
def set_capability_default(name: str, body: CapabilityDefaultUpdate, db: DbSession, user: CurrentUser) -> dict:
    capability = capabilities.get(name)
    if capability is None:
        raise HTTPException(status_code=404, detail=name)
    try:
        capabilities.set_default(db, user.id, capability, body.provider_id)
    except PluginDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return capabilities.choices(db, user.id, capability)
