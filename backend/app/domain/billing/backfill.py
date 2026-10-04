"""补算老账:费用为空、但现在按价目或服务商回报算得出来的历史用量,补上费用。

库里每条用量都存着两样东西:请求侧计量(`units`)和服务商的回包(`raw_usage`)。记账的读法改过之后 ——
回包里的成片 token 数、GPT Image 的三种 token、Evolink 的实扣现在都读得出来,新补的参考价也在了 —— 老账上那些
当时没算出来的,照现在的读法算一遍就有了。读回包用的是适配器自己的 `reported_usage`,算价用的是 `price_usage`:
和记账是同一处,补出来的数和今天新记的账口径一致。

**保守,只补能确定的**(它在升级时直接作用在用户的库上):
- 只补生图、生视频、生音频:这几种的回包由适配器读、价由价目表给,补出来的数说得清来历。对话不补 —— 订阅计划
  (Kimi Coding、Claude 订阅)的规则来自订阅目录,按它算的是名义价、不是扣费,往回补等于凭空多出一笔账;
  要不要补对话,该由用户看过之后定;
- 已经有费用的不动 —— 唯一的例外是失败、当时按请求侧计量估了价、服务商什么都没回的那几条(请求被当场拒掉):
  照现在的规则(见 usage.record_usage)改成不计费的 0;
- 费用为空的失败调用不补:当场被拒的和「我们没等到回包、远端照样生成扣了费」的在库里长得一样,分不清就不猜;
- 算不出来的照旧留空;
- 补出来的可信度记 `backfilled`(补算),和当场记下的分得开;计量照现在的读法补齐,费用由它解释得通。

重跑什么都不变:第一遍补过的已经有费用,改成 0 的已经不是「按请求侧估的价」了。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_generation_adapter
from app.ai.providers.contracts.generation import ReportedUsage, with_reported
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import price_usage

#: 补算的范围:有生成适配器的能力(回包由适配器读,`reported_usage`)。对话不补,理由见模块说明。
_GENERATION_CAPABILITIES = ("image", "video", "audio")


@dataclass(frozen=True)
class BackfillOutcome:
    #: 补上费用的条数。
    backfilled: int = 0
    #: 失败、当时按请求侧计量估了价、服务商什么都没回 → 改成不计费的条数。
    unbilled_failures: int = 0


def backfill_usage_costs(db: Session) -> BackfillOutcome:
    unbilled = 0
    for event in db.scalars(
        select(ProviderUsageEvent).where(
            ProviderUsageEvent.capability.in_(_GENERATION_CAPABILITIES),
            ProviderUsageEvent.status == "failed",
            ProviderUsageEvent.cost_confidence == "estimated",
            ProviderUsageEvent.cost_micros.is_not(None),
        )
    ):
        if event.raw_usage:
            continue
        event.cost_micros = 0
        event.cost_confidence = "not_billed"
        event.pricing_rule_id = None
        unbilled += 1

    backfilled = 0
    for event in db.scalars(
        select(ProviderUsageEvent).where(
            ProviderUsageEvent.capability.in_(_GENERATION_CAPABILITIES), ProviderUsageEvent.cost_micros.is_(None)
        )
    ):
        if event.status == "failed" and not event.raw_usage:
            continue
        reported = _reported(event)
        units = with_reported(dict(event.units or {}), reported.units)
        if reported.cost_micros is not None:
            event.cost_micros = reported.cost_micros
            event.currency = reported.currency or event.currency
            event.pricing_rule_id = None
        else:
            pricing = price_usage(
                db,
                workspace_id=event.workspace_id,
                provider_profile_id=event.provider_profile_id,
                provider=event.provider,
                capability=event.capability,
                model=event.model,
                units=units,
                moment=event.created_at,
            )
            if pricing.cost_micros is None:
                continue
            event.cost_micros = pricing.cost_micros
            event.currency = pricing.currency or event.currency
            event.pricing_rule_id = pricing.rules[0].id if len(pricing.rules) == 1 else None
        event.units = units
        event.cost_confidence = "backfilled"
        event.unpriced_reason = None
        backfilled += 1
    db.flush()
    return BackfillOutcome(backfilled=backfilled, unbilled_failures=unbilled)


def _reported(event: ProviderUsageEvent) -> ReportedUsage:
    """这条老账的回包里服务商报了什么 —— 由当时那家的适配器来读,和今天记账同一个函数。"""
    if not event.raw_usage:
        return ReportedUsage()
    adapter = get_generation_adapter(event.provider, event.capability)
    return adapter.reported_usage(event.raw_usage) if adapter is not None else ReportedUsage()
