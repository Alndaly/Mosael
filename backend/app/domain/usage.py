from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import ProviderPricingRule, ProviderUsageEvent, now
from app.domain.jobs import emit_job_event

"""
Provider usage ledger.

This Module owns durable metering rows. Provider profiles say how to call an Adapter; this
Module says what happened, which metered units were consumed, and how confidently Mibu can
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
    rule = None
    if cost_micros is None:
        rule = _best_price_rule(
            db,
            workspace_id=workspace_id,
            provider_profile_id=provider_profile_id,
            provider=provider,
            capability=capability,
            model=model,
        )
        if rule is not None:
            quantity = _quantity_for_unit(normalized_units, rule.billing_unit)
            if quantity is not None:
                cost_micros = round(quantity * rule.unit_amount_micros)
                currency = rule.currency
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
        pricing_rule_id=rule.id if rule is not None and cost_confidence == "estimated" else None,
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
        return None

    def score(rule: ProviderPricingRule) -> tuple[int, datetime]:
        specificity = 0
        specificity += 8 if rule.provider_profile_id else 0
        specificity += 4 if rule.workspace_id else 0
        specificity += 2 if rule.provider else 0
        specificity += 1 if rule.model else 0
        return specificity, rule.effective_from or datetime.min

    return max(candidates, key=score)


def _quantity_for_unit(units: dict[str, Any], billing_unit: str) -> float | None:
    aliases = {
        "request": ("request", "requests", "request_count"),
        "image": ("image", "images", "image_count", "num_images"),
        "video_second": ("video_second", "video_seconds", "duration_seconds"),
        "audio_second": ("audio_second", "audio_seconds", "duration_seconds"),
        "character": ("character", "characters", "input_characters"),
        "token": ("token", "tokens", "total_token", "total_tokens"),
        "input_token": ("input_token", "input_tokens", "prompt_tokens"),
        "output_token": ("output_token", "output_tokens", "completion_tokens"),
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
