"""「Mosael Cloud」这条连接:建出来、把网关的目录和积分单价对齐进来(ADR 0088)。

官方中转对桌面端就是一条 OpenAI 兼容连接(端点 `…/gateway/v1`,钥匙是云端登录换来的设备令牌,见
`providers/credentials` 的那一支)。直连对话、智能体、画板、工作流因此不用为它另写一套;这里只做两件事:

1. **模型清单**:网关目录就是答案(`replace_declared_catalog`)—— 网关下架的模型在这里也消失,选中它不会去撞一个 404;
2. **积分单价**:目录里每个模型的价(积分 / 百万 token)对齐成这条连接的计价规则(`align_listed_pricing`)。用量账本
   于是和别的连接一样按规则计价,只是币种是积分 —— 不和人民币、美元相加。每次调用实扣多少由 MosaelCloud 结算为准
   (网关按次向上取整),这里记的是同一份单价算出来的数。

什么时候对齐:登录 MosaelCloud 之后,以及界面上点「刷新」时。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.model_catalog import CatalogModel, parse_openai_catalog
from app.core.i18n import tr
from app.db.model_base import now
from app.db.models import ProviderProfile
from app.domain import cloud_binding
from app.domain.billing.usage import CATALOG_PRICE_UNITS, PriceQuote, align_listed_pricing
from app.domain.providers import cloud_vendor, models as provider_models, selection


@dataclass(frozen=True)
class Synced:
    profile: ProviderProfile
    models: int


def sync(db: Session, user_id: str) -> Synced:
    """问网关要目录,对齐进这个人的「Mosael Cloud」连接(没有就建)。没登录、令牌被吊销抛 `CloudBindingError` / 交回 401。

    网络出错(连不上、超时)由调用方决定怎么说 —— 登录那一刻对齐失败不该让登录失败(见 api/routes/cloud)。
    """
    login = cloud_binding.load_login(db, user_id)
    if login is None:
        raise cloud_binding.CloudBindingError(401, "not_authenticated", tr("routeErr_cloudSignInRequired"))
    reply = cloud_binding.request_json("GET", "/gateway/v1/models", device_token=cloud_binding.device_token_of(login))
    if reply.status == 401:
        cloud_binding.drop_login(db, user_id)
        raise cloud_binding.CloudBindingError(401, "not_authenticated", tr("routeErr_cloudSignInRequired"))
    if reply.status != 200 or not isinstance(reply.body, dict):
        raise cloud_binding.CloudUnavailable(f"gateway catalog answered {reply.status}")
    catalog = parse_openai_catalog(reply.body.get("data"))
    profile = selection.adopt_mosael_cloud_connection(db, owner_user_id=user_id)
    provider_models.replace_declared_catalog(
        db,
        profile,
        [provider_models.DeclaredModel(model_id=one.id, display_name=one.name, capability_ids=["chat"]) for one in catalog],
        source=cloud_vendor.VENDOR,
    )
    align_listed_pricing(
        db,
        provider_profile_id=profile.id,
        provider=cloud_vendor.VENDOR,
        source=cloud_vendor.VENDOR,
        listed={one.id: _quotes(one) for one in catalog},
        at=now(),
    )
    return Synced(profile=profile, models=len(catalog))


def _quotes(model: CatalogModel) -> list[PriceQuote]:
    """目录里的价(每百万 token,币种照目录说的)→ 规则。0 也写:积分单价为 0 就是不扣积分,不是「没标价」。"""
    rates = {"input": model.input_cost, "output": model.output_cost,
             "cache_read": model.cache_read_cost, "cache_write": model.cache_write_cost}
    return [
        PriceQuote(
            capability="chat",
            billing_unit=unit,
            unit_amount_micros=int(round(amount * 1_000_000)),
            currency=model.currency,
            source=cloud_vendor.VENDOR,
            notes=tr("pricingNote_mosaelCloud"),
        )
        for key, unit in CATALOG_PRICE_UNITS.items()
        if (amount := rates[key]) is not None
    ]
