"""给一条连接一键补齐计价规则:端点目录的报价优先,官方价目表补缺。

两个价源的先后是刻意的:

- **目录(catalog)在前。**它是这个端点**自己**说的价 —— 中转站、OpenRouter 报的就是它们实际
  收的钱,比原厂挂牌价更贴近账单。
- **价目表(reference)补缺。**多数官方端点(DeepSeek、百炼、方舟、Kimi、MiniMax)的目录只列 id,
  这时才去 `domain/price_reference` 查原厂挂牌价;生图、生视频、语音这几种非 token 计价的能力,
  也只有价目表给得出来。

**按模型整体取一边,不逐格拼。**目录给了一个模型的进出价,就不再从价目表给它补缓存价:两边的数
可能来自两家(中转的实收价 vs 原厂挂牌价),拼在一张账上谁也解释不了。

模型从哪来:目录里列的 ∪ 这条连接上配置过的模型行。后者是生图/生视频连接唯一的来源 ——
方舟、百炼的生成模型不在 `/models` 里。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale, tr
from app.db.models import ProviderPricingRule, ProviderProfile
from app.domain import price_reference
from app.domain.price_reference import ListPrice
from app.domain.provider_models import effective_capabilities, list_models
from app.domain.provider_presets import provider_definition
from app.domain.providers import capability_ids_for_vendor
from app.domain.usage import CATALOG_PRICE_UNITS, PriceQuote, prefill_model_pricing

#: 目录报价的币种。OpenRouter 一类端点与 pi 的 ModelCost 都按美元报。
CATALOG_CURRENCY = "USD"


@dataclass(frozen=True)
class PrefillOutcome:
    created_from_catalog: int = 0
    created_from_reference: int = 0
    #: 新建的规则里带分时段价格的条数(它们同时计在上面两项里)。
    created_with_time_prices: int = 0
    #: 这条连接上的模型总数(目录 ∪ 已配置的模型行)。
    models_seen: int = 0
    #: 其中找得到价(目录报了,或价目表里有)的模型数。
    models_with_price: int = 0
    #: 预填之后仍然没有任何一条规则能给它计价的模型。界面照此告诉用户还剩哪些要手填。
    unpriced_models: list[str] = field(default_factory=list)

    @property
    def created(self) -> int:
        return self.created_from_catalog + self.created_from_reference


def prefill_profile_pricing(
    db: Session,
    profile: ProviderProfile,
    *,
    base_url: str,
    catalog: list[tuple[str, dict[str, float | None]]],
) -> PrefillOutcome:
    """按「目录 → 价目表」给这条连接的每个模型补缺失的规则。只补不改(见 usage.prefill_model_pricing)。

    `catalog` 由调用方取好传进来(那是一次网络请求,不在领域层里发);`base_url` 用来判断这条
    连接是不是中转、落在哪个地区的价目上。
    """
    rows = {row.model_id: row for row in list_models(db, profile.id)}
    catalog_rates: dict[str, dict[str, float | None]] = {}
    for model_id, rates in catalog:
        catalog_rates.setdefault(model_id, rates)
    model_ids = list(dict.fromkeys([*catalog_rates, *rows]))

    relay = price_reference.is_relay(profile.vendor, base_url)
    region = price_reference.region_for(profile.vendor, base_url)
    vendor_capabilities = capability_ids_for_vendor(profile.vendor)

    from_catalog = from_reference = timed = priced = 0
    for model_id in model_ids:
        quotes = _catalog_quotes(catalog_rates.get(model_id) or {})
        if not quotes:
            listed = (
                price_reference.lookup_for_relay(model_id)
                if relay
                else price_reference.lookup(profile.vendor, model_id, region=region)
            )
            row = rows.get(model_id)
            # 只补这个模型**在这条连接上**真会用到的能力:中转挂着一个视频模型 id,而这条连接
            # 根本做不了视频,那条规则永远匹配不上,只是往表里塞行。
            allowed = effective_capabilities(row) if row is not None else vendor_capabilities
            quotes = [_reference_quote(entry, relay=relay) for entry in listed if entry.capability in allowed]
        if quotes:
            priced += 1
        for quote in prefill_model_pricing(
            db,
            provider_profile_id=profile.id,
            provider=profile.vendor,
            model=model_id,
            quotes=quotes,
        ):
            if quote.source == "catalog":
                from_catalog += 1
            else:
                from_reference += 1
            if quote.time_prices:
                timed += 1

    return PrefillOutcome(
        created_from_catalog=from_catalog,
        created_from_reference=from_reference,
        created_with_time_prices=timed,
        models_seen=len(model_ids),
        models_with_price=priced,
        unpriced_models=[model_id for model_id in model_ids if not _has_rule(db, profile, model_id)],
    )


def _catalog_quotes(rates: dict[str, float | None]) -> list[PriceQuote]:
    quotes = []
    for key, unit in CATALOG_PRICE_UNITS.items():
        amount = rates.get(key)
        if not amount or amount <= 0:
            continue
        quotes.append(
            PriceQuote(
                capability="chat",
                billing_unit=unit,
                unit_amount_micros=int(round(amount * 1_000_000)),
                currency=CATALOG_CURRENCY,
                source="catalog",
                notes=tr("pricingNote_catalog"),
            )
        )
    return quotes


def _reference_quote(entry: ListPrice, *, relay: bool) -> PriceQuote:
    remark = entry.remark_for(get_current_locale())
    params = {
        "region": tr(f"pricingRegion_{entry.region}") if entry.region != "global" else "",
        "remark": f" · {remark}" if remark else "",
        "source": entry.source,
        "checked": entry.checked,
    }
    if relay:
        definition = provider_definition(entry.vendor)
        notes = tr("pricingNote_referenceRelay", vendor=definition.label if definition else entry.vendor, **params)
    else:
        notes = tr("pricingNote_reference", **params)
    return PriceQuote(
        capability=entry.capability,
        billing_unit=entry.billing_unit,
        unit_amount_micros=entry.unit_amount_micros,
        currency=entry.currency,
        source="reference",
        notes=notes,
        time_prices=entry.time_prices_micros,
        time_zone=entry.time_zone,
    )


def _has_rule(db: Session, profile: ProviderProfile, model_id: str) -> bool:
    """有没有哪条规则能给这个模型计价 —— 与 usage._best_price_rules 同样的放宽规则(空 = 通配)。"""
    return (
        db.scalar(
            select(ProviderPricingRule.id)
            .where(
                or_(ProviderPricingRule.provider_profile_id.is_(None), ProviderPricingRule.provider_profile_id == profile.id),
                or_(ProviderPricingRule.provider == "", ProviderPricingRule.provider == profile.vendor),
                or_(ProviderPricingRule.model == "", ProviderPricingRule.model == model_id),
            )
            .limit(1)
        )
        is not None
    )
