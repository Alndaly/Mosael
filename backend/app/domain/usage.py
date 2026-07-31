from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import ProviderPricingRule, ProviderUsageEvent, now
from app.domain.jobs import emit_job_event

"""
Provider usage ledger.

This Module owns durable metering rows. Provider profiles say how to call an Adapter; this
Module says what happened, which metered units were consumed, and how confidently Open Studio can
price them. The small Interface is intentional: callers should not learn pricing rules.
"""


@dataclass(frozen=True)
class UsageSummary:
    total_cost_micros: int
    currency: str
    event_count: int
    unknown_cost_events: int
    duration_seconds: float
    token_count: int
    daily: list[dict[str, Any]]
    token_daily: list[dict[str, Any]]
    by_capability: dict[str, int]
    by_provider: dict[str, int]


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


def estimate_text_tokens(text: str) -> int:
    """Cheap local token estimate for providers that do not return token usage.

    This is intentionally marked by callers with token_estimate=true: it is good enough for
    home charts and usage auditing trends, but not a substitute for provider billing records.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    cjk_chars = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", stripped))
    non_cjk = re.sub(r"[\u3400-\u9fff\uf900-\ufaff\s]", "", stripped)
    latinish_tokens = len(non_cjk) / 4
    return max(1, round(cjk_chars + latinish_tokens))


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
    if cost_micros is None:
        rules = _best_price_rules(
            db,
            workspace_id=workspace_id,
            provider_profile_id=provider_profile_id,
            provider=provider,
            capability=capability,
            model=model,
        )
        estimated_cost = 0
        estimated_currency: str | None = None
        for rule in rules:
            quantity = _quantity_for_unit(normalized_units, rule.billing_unit)
            if quantity is not None:
                if estimated_currency is None:
                    estimated_currency = rule.currency
                if rule.currency != estimated_currency:
                    continue
                estimated_cost += round(quantity * rule.unit_amount_micros)
                applied_rules.append(rule)
        if applied_rules:
            cost_micros = estimated_cost
            currency = estimated_currency or currency
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
    rows = list(
        db.scalars(
            select(ProviderUsageEvent)
            .where(ProviderUsageEvent.workspace_id == workspace_id, ProviderUsageEvent.created_at >= start_dt)
            .order_by(ProviderUsageEvent.created_at.asc())
        )
    )
    daily_index = {
        str(start_date + timedelta(days=offset)): {
            "date": str(start_date + timedelta(days=offset)),
            "cost_micros": 0,
            "events": 0,
            "unknown": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        for offset in range(days)
    }
    by_capability: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    total_cost = 0
    unknown = 0
    duration = 0.0
    token_count = 0
    currency = "USD"
    for event in rows:
        amount = int(event.cost_micros or 0)
        tokens = _token_usage(event.units or {})
        token_count += tokens["total_tokens"]
        if event.cost_micros is not None:
            total_cost += amount
            currency = event.currency or currency
        else:
            unknown += 1
        if event.duration_seconds:
            duration += float(event.duration_seconds)
        day = str(event.created_at.date())
        if day in daily_index:
            daily_index[day]["cost_micros"] += amount
            daily_index[day]["events"] += 1
            if event.cost_micros is None:
                daily_index[day]["unknown"] += 1
            daily_index[day]["input_tokens"] += tokens["input_tokens"]
            daily_index[day]["output_tokens"] += tokens["output_tokens"]
            daily_index[day]["total_tokens"] += tokens["total_tokens"]
        by_capability[event.capability] = by_capability.get(event.capability, 0) + amount
        provider_key = event.provider or "unknown"
        by_provider[provider_key] = by_provider.get(provider_key, 0) + amount
    daily = list(daily_index.values())
    return UsageSummary(
        total_cost_micros=total_cost,
        currency=currency,
        event_count=len(rows),
        unknown_cost_events=unknown,
        duration_seconds=round(duration, 1),
        token_count=token_count,
        daily=daily,
        token_daily=[
            {
                "date": day["date"],
                "input_tokens": day["input_tokens"],
                "output_tokens": day["output_tokens"],
                "total_tokens": day["total_tokens"],
            }
            for day in daily
        ],
        by_capability=by_capability,
        by_provider=by_provider,
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
    input_tokens = round(_quantity_for_unit(units, "input_token") or 0)
    output_tokens = round(_quantity_for_unit(units, "output_token") or 0)
    total_tokens = round(_quantity_for_unit(units, "token") or 0)
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    elif input_tokens + output_tokens > total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
