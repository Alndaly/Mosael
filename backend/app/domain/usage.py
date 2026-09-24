from __future__ import annotations


from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from uuid import uuid4
import time
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.usage_scope import current_workspace
from app.db.models import ProviderPricingRule, ProviderUsageEvent, now
from app.domain.jobs import emit_job_event

logger = logging.getLogger(__name__)

"""
Provider usage ledger.

This Module owns durable metering rows. Provider profiles say how to call an Adapter; this
Module says what happened, which metered units were consumed, and how confidently Mosael can
price them. The small Interface is intentional: callers should not learn pricing rules.
"""


@dataclass(frozen=True)
class CostAmount:
    """一个币种下的一笔钱。

    **不同币种的钱永远不相加。**计价规则带币种 —— 国内厂商按人民币、海外厂商按美元(内置价目表
    domain/price_reference 保留厂商原币种)—— 而此前每一处汇总都是把 `cost_micros` 直接加起来,
    再贴上「最近一条计过价的事件」的币种:¥12 + $4.5 显示成 16.5 USD。那个数既不是人民币也不是
    美元,而且换一条最近事件,单位就跟着变。

    所以金额的汇总形状是 `list[CostAmount]`:每个币种一笔,各算各的。也**不做汇率换算** ——
    汇率随日子变,换算出来的数没人能对账;厂商的账单本来就是按原币种开的。
    """

    currency: str
    micros: int


def costs_by_currency(
    db: Session,
    *where: Any,
    group_by: Iterable[Any] = (),
    join: Iterable[tuple[Any, Any]] = (),
) -> dict[tuple[Any, ...], list[CostAmount]]:
    """按币种汇总计过价的用量事件 —— **全仓唯一一处把 cost_micros 加起来的地方。**

    `where` 是筛选条件,`group_by` 是除币种之外还要分的组(哪一天、哪家供应商、哪个人),
    `join` 是 `(表, on 条件)`,给那些要顺着别的表才分得了组的汇总(按人要经过 jobs)。
    返回 `{分组键: [CostAmount, …]}`;不分组时键是 `()`。

    SQL 里 `GROUP BY 币种`:加法只发生在同一个币种之内,调用方想加错都没有机会。

    每组里的顺序固定为**计过价的次数多的币种在前**,次数相同按币种代码 —— 「主要用哪种钱」
    排第一,界面的默认币种、管理页的排序都以它为准。不按金额排:¥7 和 $1 的 micros 谁大
    说明不了任何事。
    """
    keys = list(group_by)
    stmt = select(
        *keys,
        ProviderUsageEvent.currency,
        func.sum(ProviderUsageEvent.cost_micros),
        func.count(),
    ).select_from(ProviderUsageEvent)
    for target, onclause in join:
        stmt = stmt.join(target, onclause)
    stmt = stmt.where(ProviderUsageEvent.cost_micros.is_not(None), *where).group_by(*keys, ProviderUsageEvent.currency)
    counted: dict[tuple[Any, ...], list[tuple[int, CostAmount]]] = {}
    for row in db.execute(stmt).all():
        key = tuple(row[: len(keys)])
        currency, micros, events = row[len(keys) :]
        counted.setdefault(key, []).append((int(events or 0), CostAmount(str(currency or "USD"), int(micros or 0))))
    return {
        key: [amount for _, amount in sorted(items, key=lambda item: (-item[0], item[1].currency))]
        for key, items in counted.items()
    }


@dataclass(frozen=True)
class UsageSummary:
    #: 这段时间的花费,每个币种一笔(见 CostAmount)。
    costs: list[CostAmount]
    event_count: int
    unknown_cost_events: int
    #: 缓存命中率(cacheRead / 提示词总量)。
    #:
    #: 这里曾经还有四个**总量**:duration_seconds / token_count / cache_read_tokens /
    #: cache_write_tokens。它们随首页那八个没人读的字段一起从接口上删掉之后,只剩测试在读 ——
    #: 那是"没人要的东西留在原地"低一层的样子,一起清掉。逐日那两串(daily / token_daily)
    #: 还在,图表读的就是它们;命中率留着,因为它是**算出来的结论**,不是又一个可以自己加总的数。
    cache_hit_ratio: float
    #: 逐日:每天的 `costs`(每币种一笔)、事件数、未定价数。
    daily: list[dict[str, Any]]
    token_daily: list[dict[str, Any]]
    #: 供应商 → 这家的花费(每币种一笔)。只列计过价的供应商。
    #:
    #: 按能力分的那一份(by_capability)随这次改形状删了:它从来没有界面读过(前端只在一句
    #: 注释里提到它的名字),改成多币种形状只是给一个没人要的东西换件衣服。
    by_provider: dict[str, list[CostAmount]]
    #: 哪几个「供应商 + 模型 + 能力」的用量没能定价,各多少次。
    #: **有它才说得出人话**:此前界面只知道"有 N 次没价",于是写成「暂无价格规则」——
    #: 而用户明明配了九条,只是没有一条对上他实际在用的那个模型。笼统的否定让人以为功能坏了。
    unpriced: list[dict[str, Any]]


#: 计价单位。带 `million_` 前缀的由 _quantity_for_unit 自动换算,不必单列。
#:
#: 缓存读/写是**独立的桶**,不能并进 input_token —— 供应商侧 prompt_tokens 是含缓存的总量,
#: 而 pi 上报前已经减掉了(input = prompt_tokens - cacheRead - cacheWrite),四者不相交。
#: 它们的单价也完全不同(缓存读约为输入价一成,缓存写约 1.25 倍),所以必须能各自配规则:
#: 在此之前这两项无单位可匹配,被静默丢弃 —— 长上下文重复对话会显著少算。
PRICING_BILLING_UNITS = frozenset(
    {
        "request",
        "image",
        #: 按条计的视频(海螺一类按「每条 6 秒 768P」报价)。和 video_second 并存:
        #: 两种报价方式各家都有,硬折成秒会把「按条」的价摊错。
        "video",
        "video_second",
        "audio_second",
        "character",
        "token",
        "input_token",
        "output_token",
        "cache_read_token",
        "cache_write_token",
        "million_token",
        "million_input_token",
        "million_output_token",
        "million_cache_read_token",
        "million_cache_write_token",
    }
)




def create_pricing_rule(
    db: Session,
    *,
    workspace_id: str | None = None,
    provider_profile_id: str | None = None,
    provider: str = "",
    capability: str,
    model: str = "",
    billing_unit: str,
    unit_amount_micros: int,
    currency: str = "USD",
    source: str = "manual",
    notes: str = "",
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> ProviderPricingRule:
    fields = _normalize_pricing_fields(
        {
            "workspace_id": workspace_id,
            "provider_profile_id": provider_profile_id,
            "provider": provider,
            "capability": capability,
            "model": model,
            "billing_unit": billing_unit,
            "unit_amount_micros": unit_amount_micros,
            "currency": currency,
            "source": source,
            "notes": notes,
            "effective_from": effective_from,
            "effective_to": effective_to,
        }
    )
    rule = ProviderPricingRule(**fields)
    db.add(rule)
    db.flush()
    return rule


#: 目录报价 → 计价单位。都是「每百万 token」,和 CatalogModel / pi 的 ModelCost 同口径。
CATALOG_PRICE_UNITS = {
    "input": "million_input_token",
    "output": "million_output_token",
    "cache_read": "million_cache_read_token",
    "cache_write": "million_cache_write_token",
}


@dataclass(frozen=True)
class PriceQuote:
    """一条待预填的单价:哪个能力、按什么单位、多少钱、从哪来。

    `source` 是 `catalog`(端点自己的目录报的)或 `reference`(官方价目表,见
    domain/price_reference)—— 写进规则的 source 列,界面和用户都分得清哪条是哪来的。
    """

    capability: str
    billing_unit: str
    unit_amount_micros: int
    currency: str
    source: str
    notes: str


def prefill_model_pricing(
    db: Session,
    *,
    provider_profile_id: str,
    provider: str,
    model: str,
    quotes: list[PriceQuote],
) -> list[PriceQuote]:
    """把这个模型缺的计价规则按报价补上,返回真正新建的那几条。

    四条刻意的取舍:

    **只补不改。**已有规则一律不动 —— 用户填过的数字是他自己核对过的账,目录和价目表都只是
    厂商的挂牌价(还可能因折扣、企业协议、订阅额度而不同)。自动覆盖等于悄悄改账。

    **0 不写。**目录里的 0 意思是「未标价」或「订阅内含」,不是「免费」。写成 0 会让这一项在
    报表里变成确定的零成本,比留空更误导 —— 留空至少还能看出「没配」。

    **不和已有规则混币种。**同一个模型、同一个能力下已经有一条人民币规则时,不再补一条美元的:
    `record_usage` 遇到币种不一致的规则会把整条调用记成未定价(不同币种的钱不能相加),补一条
    反而把原本算得出的账弄没了。

    **规则始终是唯一的计费来源。**pi 自己也会算 cost,但那份不进账:一处算钱,才能解释每一笔。
    """
    created: list[PriceQuote] = []
    for quote in quotes:
        if quote.unit_amount_micros <= 0:
            continue
        existing = list(
            db.scalars(
                select(ProviderPricingRule).where(
                    ProviderPricingRule.provider_profile_id == provider_profile_id,
                    ProviderPricingRule.model == model,
                    ProviderPricingRule.capability == quote.capability,
                )
            )
        )
        if any(rule.billing_unit == quote.billing_unit for rule in existing):
            continue
        if any(rule.currency != quote.currency for rule in existing):
            continue
        create_pricing_rule(
            db,
            provider_profile_id=provider_profile_id,
            provider=provider,
            capability=quote.capability,
            model=model,
            billing_unit=quote.billing_unit,
            unit_amount_micros=quote.unit_amount_micros,
            currency=quote.currency,
            source=quote.source,
            notes=quote.notes,
        )
        created.append(quote)
    return created


def update_pricing_rule(db: Session, rule: ProviderPricingRule, **patch: Any) -> ProviderPricingRule:
    fields = _normalize_pricing_fields(patch, partial=True)
    for key, value in fields.items():
        setattr(rule, key, value)
    db.flush()
    return rule


def delete_pricing_rule(db: Session, rule: ProviderPricingRule) -> None:
    db.delete(rule)
    db.flush()


def record_usage(
    db: Session,
    *,
    workspace_id: str,
    provider_profile_id: str | None = None,
    provider: str = "",
    model: str = "",
    capability: str,
    operation: str,
    source_type: str = "",
    source_id: str = "",
    idempotency_key: str,
    status: str = "succeeded",
    duration_seconds: float | None = None,
    units: dict[str, Any] | None = None,
    raw_usage: dict[str, Any] | None = None,
    job_id: str | None = None,
    agent_message_id: str | None = None,
    cost_micros: int | None = None,
    currency: str = "USD",
    cost_confidence: str = "unknown",
) -> ProviderUsageEvent:
    """Record one billable interaction.

    The idempotency key is part of the Interface: source modules can safely call this after a
    retry or crash recovery without double-booking the same provider interaction.
    """
    existing = db.scalar(select(ProviderUsageEvent).where(ProviderUsageEvent.idempotency_key == idempotency_key))
    if existing is not None:
        return existing

    normalized_units = dict(units or {})
    applied_rules: list[ProviderPricingRule] = []
    unpriced_reason: str | None = None
    if cost_micros is None:
        rules = _best_price_rules(
            db,
            workspace_id=workspace_id,
            provider_profile_id=provider_profile_id,
            provider=provider,
            capability=capability,
            model=model,
        )
        metered = [
            (rule, quantity)
            for rule in rules
            if (quantity := _quantity_for_unit(normalized_units, rule.billing_unit)) is not None
        ]
        if len({rule.currency for rule, _ in metered}) > 1:
            # **币种不一致就不定价,不挑一种算一半。**此前这里取第一条规则的币种、把其余币种的
            # 规则静默跳过 —— 输入按人民币、输出按美元的话,账上只剩输入那一半,而且哪一半
            # 留下取决于查询返回的顺序。少算的钱看不出是少算的,比「未定价」更坏。
            #
            # 也**不**退一步去找另一币种里不那么具体的规则凑成一种:规则的具体程度是用户的
            # 意图(给这条连接单配的价压过通用价),为了凑币种悄悄换掉它等于替用户改账。
            # 记成未定价、写明原因,界面据此告诉他去把规则改成同一种币。
            unpriced_reason = "mixed_currency"
        elif metered:
            applied_rules = [rule for rule, _ in metered]
            cost_micros = sum(round(quantity * rule.unit_amount_micros) for rule, quantity in metered)
            currency = applied_rules[0].currency
            cost_confidence = "estimated"

    event = ProviderUsageEvent(
        workspace_id=workspace_id,
        provider_profile_id=provider_profile_id,
        provider=provider,
        model=model,
        capability=capability,
        operation=operation,
        source_type=source_type,
        source_id=source_id,
        job_id=job_id,
        agent_message_id=agent_message_id,
        status=status,
        duration_seconds=duration_seconds,
        units=normalized_units,
        raw_usage=dict(raw_usage or {}),
        cost_micros=cost_micros,
        currency=currency,
        cost_confidence=cost_confidence,
        unpriced_reason=unpriced_reason,
        pricing_rule_id=applied_rules[0].id if len(applied_rules) == 1 and cost_confidence == "estimated" else None,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()

    if job_id:
        emit_job_event(
            db,
            job_id,
            "usage.recorded",
            {
                "usage_event_id": event.id,
                "capability": capability,
                "provider": provider,
                "model": model,
                "cost_micros": cost_micros,
                "currency": currency,
                "cost_confidence": cost_confidence,
                "duration_seconds": duration_seconds,
            },
        )
    return event


def _normalize_pricing_fields(fields: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    normalized = dict(fields)
    for key in ("workspace_id", "provider_profile_id"):
        if key in normalized:
            normalized[key] = str(normalized[key]).strip() if normalized[key] else None
    for key in ("provider", "capability", "model", "billing_unit", "currency", "source", "notes"):
        if key in normalized and normalized[key] is not None:
            normalized[key] = str(normalized[key]).strip()
    if not partial or "capability" in normalized:
        if not normalized.get("capability"):
            raise ValueError("capability is required")
    if not partial or "billing_unit" in normalized:
        if normalized.get("billing_unit") not in PRICING_BILLING_UNITS:
            raise ValueError("unsupported billing unit")
    if not partial or "unit_amount_micros" in normalized:
        amount = int(normalized.get("unit_amount_micros") or 0)
        if amount < 0:
            raise ValueError("unit amount must be non-negative")
        normalized["unit_amount_micros"] = amount
    if "currency" in normalized:
        normalized["currency"] = (normalized.get("currency") or "USD").upper()[:8]
    if "source" in normalized:
        normalized["source"] = normalized.get("source") or "manual"
    return normalized


def summarize_usage(db: Session, *, workspace_id: str, days: int = 14) -> UsageSummary:
    start_date = (now() - timedelta(days=days - 1)).date()
    start_dt = datetime.combine(start_date, datetime.min.time())
    window = (ProviderUsageEvent.workspace_id == workspace_id, ProviderUsageEvent.created_at >= start_dt)
    rows = list(db.scalars(select(ProviderUsageEvent).where(*window).order_by(ProviderUsageEvent.created_at.asc())))
    daily_index = {
        str(start_date + timedelta(days=offset)): {
            "date": str(start_date + timedelta(days=offset)),
            "costs": [],
            "events": 0,
            "unknown": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
        }
        for offset in range(days)
    }
    unpriced_index: dict[tuple[str, str, str, str], int] = {}
    unknown = 0
    #: 命中率的**分子**。另外三个累加器(总时长、总 token、缓存写入总量)随它们在
    #: `UsageSummary` 上的字段一起删了 —— 那些字段没人读之后,这里每条用量事件都要加一遍的
    #: 计算就是白做的。逐日那几列还在(图表读的是它们),不受影响。
    cache_read_total = 0
    #: 命中率的分母是**提示词总量** = input + cacheRead + cacheWrite(三者不相交),
    #: 不是 total_tokens —— 把补全 token 算进去会让这个比例随回答长短漂移。
    prompt_total = 0
    for event in rows:
        tokens = _token_usage(event.units or {})
        cache_read_total += tokens["cache_read_tokens"]
        prompt_total += tokens["input_tokens"] + tokens["cache_read_tokens"] + tokens["cache_write_tokens"]
        if event.cost_micros is None:
            unknown += 1
            key = (event.provider or "", event.model or "", event.capability or "", event.unpriced_reason or "")
            unpriced_index[key] = unpriced_index.get(key, 0) + 1
        day = str(event.created_at.date())
        if day in daily_index:
            daily_index[day]["events"] += 1
            if event.cost_micros is None:
                daily_index[day]["unknown"] += 1
            daily_index[day]["input_tokens"] += tokens["input_tokens"]
            daily_index[day]["output_tokens"] += tokens["output_tokens"]
            daily_index[day]["cache_read_tokens"] += tokens["cache_read_tokens"]
            daily_index[day]["cache_write_tokens"] += tokens["cache_write_tokens"]
            daily_index[day]["total_tokens"] += tokens["total_tokens"]
    # 钱一律走 costs_by_currency:上面那趟逐条循环只数 token 和次数,**不碰金额** ——
    # 此前金额也在那里一条条加,于是加法落在币种之外。
    for (day,), costs in costs_by_currency(
        db, *window, group_by=(func.date(ProviderUsageEvent.created_at),)
    ).items():
        if str(day) in daily_index:
            daily_index[str(day)]["costs"] = costs
    provider_key = func.coalesce(func.nullif(ProviderUsageEvent.provider, ""), "unknown")
    by_provider = {
        str(provider): costs
        for (provider,), costs in costs_by_currency(db, *window, group_by=(provider_key,)).items()
    }
    daily = list(daily_index.values())
    return UsageSummary(
        costs=costs_by_currency(db, *window).get((), []),
        event_count=len(rows),
        unknown_cost_events=unknown,
        cache_hit_ratio=round(cache_read_total / prompt_total, 4) if prompt_total > 0 else 0.0,
        daily=daily,
        token_daily=[
            {
                "date": day["date"],
                "input_tokens": day["input_tokens"],
                "output_tokens": day["output_tokens"],
                "cache_read_tokens": day["cache_read_tokens"],
                "cache_write_tokens": day["cache_write_tokens"],
                "total_tokens": day["total_tokens"],
            }
            for day in daily
        ],
        by_provider=by_provider,
        # 次数多的排前面:要补价的话,先补这几个最划算。`reason` 说得出为什么没价的时候
        # (规则币种不一致),界面就不再只说「缺价」—— 那种情况下规则明明是配了的。
        unpriced=[
            {"provider": provider, "model": model, "capability": capability, "reason": reason, "events": count}
            for (provider, model, capability, reason), count in sorted(
                unpriced_index.items(), key=lambda item: item[1], reverse=True
            )
        ],
    )


def _best_price_rule(
    db: Session,
    *,
    workspace_id: str,
    provider_profile_id: str | None,
    provider: str,
    capability: str,
    model: str,
) -> ProviderPricingRule | None:
    rules = _best_price_rules(
        db,
        workspace_id=workspace_id,
        provider_profile_id=provider_profile_id,
        provider=provider,
        capability=capability,
        model=model,
    )
    return rules[0] if rules else None


def _best_price_rules(
    db: Session,
    *,
    workspace_id: str,
    provider_profile_id: str | None,
    provider: str,
    capability: str,
    model: str,
) -> list[ProviderPricingRule]:
    moment = now()
    candidates = list(
        db.scalars(
            select(ProviderPricingRule).where(
                ProviderPricingRule.capability == capability,
                or_(ProviderPricingRule.workspace_id.is_(None), ProviderPricingRule.workspace_id == workspace_id),
                or_(
                    ProviderPricingRule.provider_profile_id.is_(None),
                    ProviderPricingRule.provider_profile_id == provider_profile_id,
                ),
                or_(ProviderPricingRule.provider == "", ProviderPricingRule.provider == provider),
                or_(ProviderPricingRule.model == "", ProviderPricingRule.model == model),
                or_(ProviderPricingRule.effective_from.is_(None), ProviderPricingRule.effective_from <= moment),
                or_(ProviderPricingRule.effective_to.is_(None), ProviderPricingRule.effective_to > moment),
            )
        )
    )
    if not candidates:
        return []

    def score(rule: ProviderPricingRule) -> tuple[int, datetime]:
        specificity = 0
        specificity += 8 if rule.provider_profile_id else 0
        specificity += 4 if rule.workspace_id else 0
        specificity += 2 if rule.provider else 0
        specificity += 1 if rule.model else 0
        return specificity, rule.effective_from or datetime.min

    by_unit: dict[str, ProviderPricingRule] = {}
    for rule in candidates:
        current = by_unit.get(rule.billing_unit)
        if current is None or score(rule) > score(current):
            by_unit[rule.billing_unit] = rule
    return list(by_unit.values())


def _quantity_for_unit(units: dict[str, Any], billing_unit: str) -> float | None:
    if billing_unit.startswith("million_"):
        base = billing_unit.removeprefix("million_")
        quantity = _quantity_for_unit(units, base)
        return quantity / 1_000_000 if quantity is not None else None

    aliases = {
        "request": ("request", "requests", "request_count"),
        "image": ("image", "images", "image_count", "num_images"),
        "video": ("video", "videos", "video_count"),
        "video_second": ("video_second", "video_seconds", "duration_seconds"),
        "audio_second": ("audio_second", "audio_seconds", "duration_seconds"),
        "character": ("character", "characters", "input_characters"),
        "token": ("token", "tokens", "total_token", "total_tokens"),
        # 注意 prompt_tokens 只作为 input_token 的**兜底**别名:适配器直接给 input_tokens 时
        # 用它(已扣除缓存);只有那些自己不拆分的来源才会落到 prompt_tokens 上。
        "input_token": ("input_token", "input_tokens", "prompt_tokens"),
        "output_token": ("output_token", "output_tokens", "completion_tokens"),
        "cache_read_token": ("cache_read_token", "cache_read_tokens", "cached_tokens"),
        "cache_write_token": ("cache_write_token", "cache_write_tokens"),
    }
    for key in (billing_unit, *aliases.get(billing_unit, ())):
        value = units.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    if billing_unit == "input_token":
        value = _numeric_unit(units.get("input_characters"))
        if value is not None:
            return value
    if billing_unit == "output_token":
        value = _numeric_unit(units.get("output_characters"))
        if value is not None:
            return value
    if billing_unit == "token":
        input_tokens = _quantity_for_unit(units, "input_token")
        output_tokens = _quantity_for_unit(units, "output_token")
        if input_tokens is not None or output_tokens is not None:
            return (input_tokens or 0) + (output_tokens or 0)
    return None


def _numeric_unit(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _token_usage(units: dict[str, Any]) -> dict[str, int]:
    """一次调用的 token 拆分。

    **缓存读/写要单列**:它们和 input 不相交(pi 上报前已从 prompt 里减掉),单价也差一个
    数量级(读约输入价一成,写约 1.25 倍)。此前汇总只取 input/output,缓存这两桶落进图表的
    「其他」里 —— 于是"这个月省下多少"这件事在界面上根本看不见,而它恰恰是长对话最大的变量。
    """
    input_tokens = round(_quantity_for_unit(units, "input_token") or 0)
    output_tokens = round(_quantity_for_unit(units, "output_token") or 0)
    cache_read = round(_quantity_for_unit(units, "cache_read_token") or 0)
    cache_write = round(_quantity_for_unit(units, "cache_write_token") or 0)
    total_tokens = round(_quantity_for_unit(units, "token") or 0)
    split = input_tokens + output_tokens + cache_read + cache_write
    if total_tokens <= 0 or split > total_tokens:
        total_tokens = split
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": total_tokens,
    }


# ---------- 记一次可计费的供应商调用 ----------
#
# `record_usage` 有十八个关键字参数,而三处调用点(生成 runner、智能体 host、对话)各拼一遍:
# 各自算耗时、各自编幂等键、各自决定失败要不要记。抄三遍的结果是它们并不一致,而且新增的调用
# 类型(Gemini 原生视频理解、语音合成、向量化)干脆一条都不记 —— 首页那张 Token 图长期是漏的。
#
# 把它们并排看,只有一样东西真的因地而异:**怎么计量**。图片按张、视频按秒、对话按 token,
# 定价规则本来就按 capability + units 查。其余全是同一个形状。
#
# 所以「一次可计费的调用」成为一个显式概念:不变的部分(归属、耗时、成败、幂等、落库)交给
# 下面这个上下文管理器,变化的部分留给调用方一句 `call.meter(...)`。


@dataclass
class BillableCall:
    """一次进行中的可计费调用。用 `meter()` 报计量,可以多次调用(线程池里逐块累加)。"""

    capability: str
    operation: str
    provider: str = ""
    model: str = ""
    provider_profile_id: str | None = None
    source_type: str = ""
    source_id: str = ""
    job_id: str | None = None
    agent_message_id: str | None = None
    units: dict[str, Any] = None  # type: ignore[assignment]
    raw_usage: dict[str, Any] = None  # type: ignore[assignment]
    cost_micros: int | None = None
    #: 记账落库后由 billable 填上,供调用方读取算好的成本(智能体把它写进消息 payload)。
    event: ProviderUsageEvent | None = None
    #: 调用方**捕获了**异常自己处理时,用它显式标失败 —— 异常没往外抛,billable 看不见。
    status: str = "succeeded"

    def mark_failed(self) -> None:
        self.status = "failed"

    def __post_init__(self) -> None:
        if self.units is None:
            self.units = {}
        if self.raw_usage is None:
            self.raw_usage = {}

    def describe(self, *, provider: str = "", model: str = "", provider_profile_id: str | None = None) -> None:
        """调用发生后才知道用了哪个模型时,补登记。"""
        if provider:
            self.provider = provider
        if model:
            self.model = model
        if provider_profile_id:
            self.provider_profile_id = provider_profile_id

    def meter(self, units: dict[str, Any] | None = None, *, raw: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """累加计量。数值相加,其余后写覆盖 —— 线程池里每块报一次,最终合成一条账。"""
        merged = {**(units or {}), **kwargs}
        for key, value in merged.items():
            if isinstance(value, (int, float)) and isinstance(self.units.get(key), (int, float)):
                self.units[key] += value
            else:
                self.units[key] = value
        if raw:
            self.raw_usage = raw

    def annotate(self, **fields: Any) -> None:
        """往 `raw_usage` 里**加**几条注解,不动已经记下的计量。

        和 `meter(raw=…)` 的区别是后者**覆盖** raw_usage —— 拿它记注解会把 token 用量冲掉。
        用来记那些"发生过、而且有成本"的事:比如 response_format 降了一档,那是一个多出来的
        往返,账上看不见的话,"这条流程为什么比预期贵"永远查不出来。
        """
        if not fields:
            return
        self.raw_usage = {**(self.raw_usage or {}), **fields}

    def meter_openai_tokens(self, raw: Any) -> None:
        """OpenAI 风格回包的 `usage` 字段。对话类调用最常见的一种计量。"""
        tokens = raw if isinstance(raw, dict) else {}
        self.meter(
            input_tokens=int(tokens.get("prompt_tokens") or 0),
            output_tokens=int(tokens.get("completion_tokens") or 0),
            raw=tokens,
        )


def once(operation: str) -> str:
    """一个**只保证唯一、不保证幂等**的记账键。

    用在"重放不可能发生"的调用上:请求作用域内的同步调用 —— 进程一死,调用方连返回都没有,
    没有任何东西会把它再跑一遍。这类调用没有稳定的工作单元可以当键。

    **它存在是为了让这个选择看得见。** 此前这是 `billable` 里一句隐式兜底
    (`f"{operation}:{source_id}:{时间戳}"`),而时间戳在键里意味着**任何重放都会生成新键**,
    必然重复入账 —— 兜底键实际上等于"不去重"。而 `billable` 和 `record_usage` 的文档都写着
    「重放同一次调用不会重复入账」。一个在它该生效的那次不生效的保护,比没有保护更坏。

    有稳定工作单元的(job、生成任务、智能体消息)**不要用它** —— 那些是真会被重放的,
    传一个从工作单元算出来的键。
    """
    return f"once:{operation}:{uuid4().hex}"


@contextmanager
def billable(
    db: Session,
    *,
    capability: str,
    operation: str,
    workspace_id: str = "",
    provider: str = "",
    model: str = "",
    provider_profile_id: str | None = None,
    source_type: str = "",
    source_id: str = "",
    idempotency_key: str,
    job_id: str | None = None,
    agent_message_id: str | None = None,
    started: float | None = None,
) -> Iterator[BillableCall]:
    """包住一次供应商调用,结束时记一条账。

    - **归属**:显式 workspace_id 优先;没给就取环境上下文(权限闸门绑的,见 core/usage_scope)。
      两个都没有时不记账,但会 warning 出来 —— 静默漏记正是这次要终结的毛病。
    - **同一个事务**:落库用调用方的 Session。试过给它独立事务(理由是"钱已经花了,调用方
      回滚不该抹掉这笔账"),但 `job_id` / `agent_message_id` 是外键,指向调用方**刚 flush
      还没 commit** 的行 —— 独立事务看不见它们,插入直接违反外键。schema 已经把这件事定了:
      账和它引用的东西必须同生共死。代价是只读接口(翻译、分析、提示词优化)记了账之后要
      自己 commit 一次,那几处都写了注释。
    - **成败**:块里抛异常就记 failed 再原样抛出。失败的调用同样花钱(很多供应商按请求计费),
      而且"最近失败了多少次"本身就是用户想在账上看到的。
    - **幂等**:`idempotency_key` 是**必填的**。重放同一次调用不会重复入账 —— 而这句话只有在
      键真的稳定时才成立,所以不再有隐式兜底。

      有稳定工作单元的(job、生成任务、智能体消息)传一个从它算出来的键:重放时命中同一行,
      不会重复计费。重放不可能发生的(请求作用域内的同步调用 —— 进程一死调用方连返回都没有)
      传 `once(operation)`,那个名字本身就说明这一次不受重放保护。

      **必填是这条的关键。** 此前兜底键是 `f"{operation}:{source_id}:{时间戳}"` —— 时间戳在
      键里,任何重放都会生成新键,于是必然重复入账;而这段文档当时写的是"重放不会重复入账"。
      一个在它该生效的那次不生效的保护,比没有保护更坏,因为下一个需要重放保护的调用点会
      照着文档不传键。
    """
    # started 可由调用方传入:生成任务跨越几分钟,那段时间不在这个 with 块里,计时该由跑任务
    # 的人说了算(time.monotonic 的基准)。
    began = time.monotonic() if started is None else started
    call = BillableCall(
        capability=capability,
        operation=operation,
        provider=provider,
        model=model,
        provider_profile_id=provider_profile_id,
        source_type=source_type,
        source_id=source_id,
        job_id=job_id,
        agent_message_id=agent_message_id,
    )
    try:
        yield call
    except BaseException:
        call.status = "failed"
        raise
    finally:
        target = workspace_id or current_workspace()
        if not target:
            # 记不了(workspace_id 是 NOT NULL)。喊一声:这类调用要么该在工作区闸门之后发生,
            # 要么该显式带上归属 —— 两者都不满足是个建模问题,不该无声无息。
            logger.warning("用量无法归属(operation=%s capability=%s):当前上下文没有工作区", operation, capability)
        else:
            try:
                call.event = record_usage(
                    db,
                    workspace_id=target,
                    provider_profile_id=call.provider_profile_id,
                    provider=call.provider,
                    model=call.model,
                    capability=call.capability,
                    operation=call.operation,
                    source_type=call.source_type,
                    source_id=call.source_id,
                    job_id=call.job_id,
                    agent_message_id=call.agent_message_id,
                    idempotency_key=idempotency_key,
                    status=call.status,
                    duration_seconds=round(max(0.0, time.monotonic() - began), 3),
                    units=call.units,
                    raw_usage=call.raw_usage,
                    cost_micros=call.cost_micros,
                )
            except Exception:  # noqa: BLE001 — 记账是旁路,不该把主流程带下水
                logger.warning("用量入账失败(%s),已忽略", operation, exc_info=True)
