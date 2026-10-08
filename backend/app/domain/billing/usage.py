from __future__ import annotations


from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re
from uuid import uuid4
import time
from typing import Any

from sqlalchemy import event as orm_event, func, or_, select, update
from sqlalchemy.orm import Session, SessionTransaction

from app.core.usage_scope import current_workspace
from app.db.models import Job, ProviderPricingRule, ProviderUsageEvent, now
from app.domain.jobs import current_parent_job_id, emit_job_event
from app.domain.billing.price_schedule import normalize_schedule, price_at

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
    domain/billing/price_reference 保留厂商原币种)—— 而此前每一处汇总都是把 `cost_micros` 直接加起来,
    再贴上「最近一条计过价的事件」的币种:¥12 + $4.5 显示成 16.5 USD。那个数既不是人民币也不是
    美元,而且换一条最近事件,单位就跟着变。

    所以金额的汇总形状是 `list[CostAmount]`:每个币种一笔,各算各的。也**不做汇率换算** ——
    汇率随日子变,换算出来的数没人能对账;厂商的账单本来就是按原币种开的。
    """

    currency: str
    micros: int


#: 账上记 0、但不是一笔花费的两种:免费的引擎、失败了没扣钱。汇总金额时不算它们(见 costs_by_currency)。
NOT_SPENT = ("free", "not_billed")


def costs_by_currency(
    db: Session,
    *where: Any,
    group_by: Iterable[Any] = (),
) -> dict[tuple[Any, ...], list[CostAmount]]:
    """按币种汇总计过价的用量事件 —— **全仓唯一一处把 cost_micros 加起来的地方。**

    `where` 是筛选条件,`group_by` 是除币种之外还要分的组(哪一天、哪家供应商、哪个人 —— 人记在用量自己身上,
    按 `user_id` 分;没记下是谁的落进键为 None 的那一组,即「无归属」)。
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
    #: 没花的钱不是钱:免费的引擎(`free`)、失败了服务商什么都没回(`not_billed`)都记 0,混进来的话账上会冒出一笔
    #: 「$0.00」—— 一个人民币部署里一笔美元的零,一次没扣钱的失败显示成「费用 US$0.00」(没定价的模型失败了,币种
    #: 只能猜成美元),还按次数把它排成主要币种。界面另说「未扣费」(见 NOT_SPENT)。
    stmt = stmt.where(
        ProviderUsageEvent.cost_micros.is_not(None), ProviderUsageEvent.cost_confidence.not_in(NOT_SPENT), *where
    ).group_by(*keys, ProviderUsageEvent.currency)
    counted: dict[tuple[Any, ...], list[tuple[int, CostAmount]]] = {}
    for row in db.execute(stmt).all():
        key = tuple(row[: len(keys)])
        currency, micros, events = row[len(keys) :]
        counted.setdefault(key, []).append((int(events or 0), CostAmount(str(currency or "USD"), int(micros or 0))))
    return {
        key: [amount for _, amount in sorted(items, key=lambda item: (-item[0], item[1].currency))]
        for key, items in counted.items()
    }


#: 回包里的 token 数和我们估的 token 数不拿来比(估的本来就不准,回包的才是实数),只拿来按价目核对扣费。
_TOKEN_KEYS = frozenset({"input_tokens", "output_tokens", "image_input_tokens", "total_tokens"})


def usage_mismatches(billed: dict[str, Any], observed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """记下的计量和服务商回包说的事实(`ReportedUsage.observed`)哪几项对不上。两边都有的键才比:
    数按 2% 或半个单位的容差比(5 秒和 5.0 秒是一回事);分辨率这类文字有数字的只比数字(`720P` 和 SR 720 是同一档)。
    我们自己估的 token(`token_estimate`)不比。"""
    estimated = bool(billed.get("token_estimate"))
    mismatched: dict[str, dict[str, Any]] = {}
    for key, reported in observed.items():
        if key not in billed or (estimated and key in _TOKEN_KEYS):
            continue
        mine = billed[key]
        if isinstance(mine, bool) or isinstance(reported, bool):
            same = mine == reported
        elif isinstance(mine, (int, float)) and isinstance(reported, (int, float)):
            same = abs(float(mine) - float(reported)) <= max(0.5, abs(float(reported)) * 0.02)
        else:
            left, right = str(mine).strip().lower(), str(reported).strip().lower()
            digits = re.sub(r"\D", "", left), re.sub(r"\D", "", right)
            same = digits[0] == digits[1] if digits[0] and digits[1] else left == right
        if not same:
            mismatched[key] = {"billed": mine, "reported": reported}
    return mismatched


def run_costs(db: Session, job_id: str) -> dict[str, Any]:
    """一次运行(任务连同它派生的全部子任务)花了多少钱:`amounts` 每个币种一笔、`calls` 几次计费调用、
    `unpriced` 其中几次没能定价。

    运行自己的账(工作流里大模型那几次调用)挂在运行的任务上,生成、配音这些子任务的账挂在各自的子任务上 ——
    所以顺着 `parent_job_id` 把整棵树收齐再加。
    """
    ids: set[str] = {job_id}
    frontier = {job_id}
    while frontier:
        frontier = set(db.scalars(select(Job.id).where(Job.parent_job_id.in_(frontier)))) - ids
        ids |= frontier
    in_run = ProviderUsageEvent.job_id.in_(ids)
    calls, unpriced = db.execute(
        select(func.count(), func.sum(func.iif(ProviderUsageEvent.cost_micros.is_(None), 1, 0))).where(in_run)
    ).one()
    return {
        "amounts": [{"currency": amount.currency, "micros": amount.micros} for amount in costs_by_currency(db, in_run).get((), [])],
        "calls": int(calls or 0),
        "unpriced": int(unpriced or 0),
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
        #: 按首/按段计的音频(音乐生成多按「每首」报价)。和 audio_second 并存,理由同上。
        "audio",
        "audio_second",
        "character",
        "token",
        "input_token",
        "output_token",
        "cache_read_token",
        "cache_write_token",
        #: 图像输入 token(GPT Image 的参考图)。和文字输入是两个价(gpt-image-2:$8 对 $5),
        #: 也是独立的桶:适配器把服务商回报的输入拆成文字 / 图像两格(见 adapters/openai/image)。
        "image_input_token",
        "million_token",
        "million_input_token",
        "million_output_token",
        "million_cache_read_token",
        "million_cache_write_token",
        "million_image_input_token",
    }
)

#: 按 token 计的单位(去掉 million_ 前缀之后)。计量里的 token 数是按提示词估的(`token_estimate`)时,
#: 这些单位不计价 —— 见 price_usage。
_TOKEN_UNITS = frozenset({"token", "input_token", "output_token", "cache_read_token", "cache_write_token", "image_input_token"})




def normalize_resolution(value: Any) -> str:
    """分辨率的写法归一成小写:万相写 1080P、Evolink 写 1080p、海螺写 2K —— 说的是同一档。"""
    return str(value or "").strip().lower()


def create_pricing_rule(
    db: Session,
    *,
    workspace_id: str | None = None,
    provider_profile_id: str | None = None,
    provider: str = "",
    capability: str,
    model: str = "",
    resolution: str = "",
    billing_unit: str,
    unit_amount_micros: int,
    time_prices: list[dict[str, Any]] | None = None,
    time_zone: str = "",
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
            "resolution": resolution,
            "billing_unit": billing_unit,
            "unit_amount_micros": unit_amount_micros,
            "time_prices": time_prices or [],
            "time_zone": time_zone,
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
    domain/billing/price_reference)—— 写进规则的 source 列,界面和用户都分得清哪条是哪来的。

    `time_prices` / `time_zone` 是这一个价的分时段价目(见 domain/billing/price_schedule):它是**同一条
    规则**的一部分,不是另一条规则 —— DeepSeek 的高峰价和空闲价落在同一行上。
    """

    capability: str
    billing_unit: str
    unit_amount_micros: int
    currency: str
    source: str
    notes: str
    time_prices: tuple[dict[str, Any], ...] = ()
    time_zone: str = ""
    #: 只对这个输出分辨率生效;空 = 不限(见 ProviderPricingRule.resolution)。
    resolution: str = ""


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
        # 「缺」按 (单位, 分辨率) 这一格算:老库里那条不限分辨率的价原样留着,只补它旁边缺的那几档。
        if any(
            rule.billing_unit == quote.billing_unit and rule.resolution == normalize_resolution(quote.resolution)
            for rule in existing
        ):
            continue
        if any(rule.currency != quote.currency for rule in existing):
            continue
        create_pricing_rule(
            db,
            provider_profile_id=provider_profile_id,
            provider=provider,
            capability=quote.capability,
            model=model,
            resolution=quote.resolution,
            billing_unit=quote.billing_unit,
            unit_amount_micros=quote.unit_amount_micros,
            time_prices=[dict(window) for window in quote.time_prices],
            time_zone=quote.time_zone,
            currency=quote.currency,
            source=quote.source,
            notes=quote.notes,
        )
        created.append(quote)
    return created


def update_pricing_rule(db: Session, rule: ProviderPricingRule, **patch: Any) -> ProviderPricingRule:
    # 时段和时区要**合在一起**校验:只改了时区,也得拿它去读原来那几个时段。
    if "time_prices" in patch or "time_zone" in patch:
        patch.setdefault("time_prices", rule.time_prices)
        patch.setdefault("time_zone", rule.time_zone)
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
    user_id: str | None,
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
    occurred_at: datetime | None = None,
    supersedes: str | None = None,
) -> ProviderUsageEvent:
    """记一次可计费调用的账。**`db` 只拿来读**(价目、这一笔记过没有);这条账由记账这一层随 `db` 提交的那一刻写
    (见下面「账随调用方提交的那一刻落库」那一节的契约)。

    交回算好的那一条:**还没落库**的对象(`id` 为空),成本那几格(`cost_micros` / `currency` / `cost_confidence`)
    已经算好,调用方读它们就够了(智能体把成本写进消息)。同一个 `idempotency_key` 已经记过(库里有、或者这个会话里
    已经排着)就交回那一条,不重记 —— 键是接口的一部分:重试、崩溃后接着干都不会把同一次调用记两遍。

    `occurred_at`(UTC,缺省为现在)是这次调用**发生的时刻**:挑哪条规则(生效期)、按哪一档
    时段价计,都按它;它也就是这条账的 `created_at` —— 账上记的时间和算价用的时间是同一个,
    事后对着时段价目核一笔账才对得上。

    `supersedes`:这一条接替的那一条账的键(见 superseded_attempt)。写这一条的同一个事务里把那一条撤下。

    `user_id`(**必填**,ADR 0050 D30):替谁花的钱 —— 跑的人。没有默认值:漏了它的调用点在调用那一刻就报错,而不是悄悄
    记成「无归属」。真不知道是谁(没有人在场的后台调用)就传那个变量本身的 None,棘轮不许写字面量 None(见
    tests/test_usage_knows_who_spent.py)。
    """
    moment = occurred_at or now()
    queued = _queued_usage(db, idempotency_key)
    if queued is not None:
        return queued
    existing = db.scalar(select(ProviderUsageEvent).where(ProviderUsageEvent.idempotency_key == idempotency_key))
    if existing is not None:
        return existing

    normalized_units = dict(units or {})
    applied_rules: tuple[ProviderPricingRule, ...] = ()
    unpriced_reason: str | None = None
    if cost_micros is None:
        pricing = price_usage(
            db,
            workspace_id=workspace_id,
            provider_profile_id=provider_profile_id,
            provider=provider,
            capability=capability,
            model=model,
            units=normalized_units,
            moment=moment,
        )
        if status == "failed" and not raw_usage:
            # **失败了、服务商什么都没回,就是没扣钱。**请求被当场拒掉(参数不对、额度不够、
            # 内容审核)时既没有产出也没有回包;此前照样按请求侧计量套价 —— 一次请求两张、
            # 当场被拒的生图记了两张的钱,而那笔钱从来没被扣过。请求侧计量照旧留在账上
            # (失败了多少次、都是什么请求),只是它不是扣费的依据。
            #
            # 服务商回报了用量或扣费的(有的平台失败也扣),走下面同一条路照它记。
            # 币种跟着这个模型的价走,¥0 和这家其余的人民币账放在一起,不另起一个 $0。
            cost_micros = 0
            cost_confidence = "not_billed"
            currency = pricing.currency or currency
        elif pricing.cost_micros is not None:
            applied_rules = pricing.rules
            cost_micros = pricing.cost_micros
            currency = pricing.currency or currency
            cost_confidence = "estimated"
        else:
            unpriced_reason = pricing.unpriced_reason

    values = dict(
        workspace_id=workspace_id,
        user_id=user_id,
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
        created_at=moment,
    )
    _write_after_caller(db, values, supersedes=supersedes)
    return ProviderUsageEvent(**values)


def superseded_attempt(db: Session, idempotency_key: str) -> dict[str, Any] | None:
    """要被接替的那一条账原来的样子(写进接替它的那一条的注解里);没有这一条就是 None。只读 —— 撤下它的是
    写接替那一条的同一个事务(`record_usage(..., supersedes=键)`)。

    **只为一种情形存在:同一次服务商调用先被记成了失败,后来又拿到了结果。** 生成在下载成片时断了、或者等远端时出了确定性
    的错,运行器按「成片没拿到」记一笔(服务商回报的扣费,或者远端任务没了结时的请求侧估价);之后用户点「重新取回」,拿到了
    **同一个**远端任务的成片 —— 那不是又花了一次钱。两条都留着,这次生成的花费就被加两遍(`costs_by_currency` 把同一条生成
    的几条账加在一起),失败次数也多算一次。所以成功的那一条接替失败的那一条:失败的撤下,它原来记了什么写进成功那条的
    注解,账上看得见曾经发生过什么。
    """
    event = db.scalar(select(ProviderUsageEvent).where(ProviderUsageEvent.idempotency_key == idempotency_key))
    if event is None:
        return None
    return {
        "status": event.status,
        "cost_micros": event.cost_micros,
        "currency": event.currency,
        "cost_confidence": event.cost_confidence,
        "recorded_at": event.created_at.isoformat() if event.created_at else None,
        "units": dict(event.units or {}),
    }


@dataclass(frozen=True)
class Pricing:
    """一次调用按计价规则算出来的价。

    `cost_micros` 为 None = 没能定价,`unpriced_reason` 说得出原因时写原因(目前只有币种不一致)。
    `currency` 是对上的规则的币种:定不了价时只要规则币种一致也照样给 —— 记一笔不计费的 0
    时,它决定这个 0 归到哪个币种下。
    """

    cost_micros: int | None
    currency: str | None
    rules: tuple[ProviderPricingRule, ...] = ()
    unpriced_reason: str | None = None


def price_usage(
    db: Session,
    *,
    workspace_id: str,
    provider_profile_id: str | None,
    provider: str,
    capability: str,
    model: str,
    units: dict[str, Any],
    moment: datetime,
) -> Pricing:
    """按计价规则给一份计量算价 —— **记账和补算老账共用这一处**,两边认的规则不会漂开。

    每个计价单位挑一条规则(见 `_best_price_rules`),有计量的那几条按发生时刻的单价相加。
    """
    rules = _best_price_rules(
        db,
        workspace_id=workspace_id,
        provider_profile_id=provider_profile_id,
        provider=provider,
        capability=capability,
        model=model,
        moment=moment,
        resolution=str(units.get("resolution") or ""),
    )
    metered = [
        (rule, quantity) for rule in rules if (quantity := _priced_quantity(units, rule.billing_unit)) is not None
    ]
    currencies = {rule.currency for rule, _ in metered} or {rule.currency for rule in rules}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    if len({rule.currency for rule, _ in metered}) > 1:
        # **币种不一致就不定价,不挑一种算一半。**此前这里取第一条规则的币种、把其余币种的
        # 规则静默跳过 —— 输入按人民币、输出按美元的话,账上只剩输入那一半,而且哪一半
        # 留下取决于查询返回的顺序。少算的钱看不出是少算的,比「未定价」更坏。
        #
        # 也**不**退一步去找另一币种里不那么具体的规则凑成一种:规则的具体程度是用户的
        # 意图(给这条连接单配的价压过通用价),为了凑币种悄悄换掉它等于替用户改账。
        # 记成未定价、写明原因,界面据此告诉他去把规则改成同一种币。
        return Pricing(cost_micros=None, currency=None, unpriced_reason="mixed_currency")
    if not metered:
        return Pricing(cost_micros=None, currency=currency)
    return Pricing(
        cost_micros=sum(round(quantity * price_at(rule, moment)) for rule, quantity in metered),
        currency=currency,
        rules=tuple(rule for rule, _ in metered),
    )


def _priced_quantity(units: dict[str, Any], billing_unit: str) -> float | None:
    """这个单位能拿来**计价**的数量。

    **按提示词估的 token 数不计价。**它是给首页图表看趋势的(见 core/token_estimate),不是账单:回包没报
    用量的兼容端点上,GPT Image 只剩估的十几个输入 token,按它记出几十 micros —— 看起来「有价」,实际差
    两个数量级,而真正的大头(图像输出)根本没记。宁可记成未定价,一眼看得出缺什么。服务商报了 token 数的,
    适配器读回包时会把估的那份换掉(见 contracts.generation.with_reported)。张数、秒数这些不是估的,照算。
    """
    if units.get("token_estimate") is True and billing_unit.removeprefix("million_") in _TOKEN_UNITS:
        return None
    return _quantity_for_unit(units, billing_unit)


def _announce(db: Session, event: ProviderUsageEvent) -> None:
    """记在任务上的那一条时间线事件(有任务才有)。"""
    if not event.job_id:
        return
    emit_job_event(
        db,
        event.job_id,
        "usage.recorded",
        {
            "usage_event_id": event.id,
            "capability": event.capability,
            "provider": event.provider,
            "model": event.model,
            "cost_micros": event.cost_micros,
            "currency": event.currency,
            "cost_confidence": event.cost_confidence,
            "duration_seconds": event.duration_seconds,
        },
    )


# ---------- 账随调用方提交的那一刻落库(D66) ----------
#
# **契约**:可计费调用的账(provider_usage_events 的一行)由记账这一层写,调用方不碰。调用期间它只排在调用方会话上
# (`session.info`),**调用方提交的那一刻**(`before_commit`)随这次提交一起落库;调用方没提交(回滚、没提交就关、提交
# 失败)的,在它的事务结束之后用一个新会话、一个短事务补写。调用方那边看到的是:
#
# 1. **调用方不因为记账攥写锁跨过别的调用。** SQLite 只有一个写者,flush 一次就攥着写锁直到那个事务结束。账要是在调用
#    之后当场 flush 进调用方的事务,一个会话里接连几次付费调用(工作流的「口播收紧」一个节点里两三轮大模型)时,第一笔
#    之后每一次大模型请求都攥着写锁,别的节点、任务进度、请求排在后面,超过等锁的上限就是 database is locked。现在账只在
#    提交那一刻写,写完就提交。
# 2. **谁看得见调用方提交的东西,谁就看得见这条账。** 账和调用方这次提交的东西(任务落终态、消息落库)在同一个事务里,
#    一起出现:落终态之后跑的收拾、回执、界面上「任务结束了就去取成本」,都不会读到一个「已经成功、还没记账」的样子。
#    此前(D66 第一版)账在调用方提交**之后**另开事务写,中间有一段窗口:AI Studio 在任务落终态那一下去取记录的成本,
#    碰上窗口就一直空着(那一条不再轮询),CI 上「接着取回之后账在」的测试也碰上过。
# 3. **调用方的事务里、提交之前看不见这条账**:要读成本就读 `record_usage` / `billable` 交回的那一条(`BillableCall.event`:
#    成本已经算好、还没落库的对象,`id` 为空)。
# 4. **钱花了就有账,跟调用方的事务成不成无关。** 失败的工作流节点会回滚、会话用完没提交就关 —— 账在它的事务结束之后
#    照写。那时账上的引用(`job_id`、`agent_message_id`)指向的行没能活下来的置空,和 schema 里 `ondelete="SET NULL"`
#    同一个语义;工作区都没了(CASCADE)的不写。
# 5. **同一个键只记一条**:库里有、或者这个会话里已经排着,`record_usage` 交回那一条;写的时候库里已经有了就跳过。
# 6. **接替**(`supersedes`,见 superseded_attempt):撤下被接替的那一条和写这一条在同一个事务里。
# 7. 挂在会话的事务跳变上(`before_commit` / `after_commit` / `after_transaction_end`),不挂在某个调用点上 —— 和
#    jobs._note_settled_jobs 同一个理由:调用方有十几处,各自记得做某件事的做法已经证明靠不住。保存点提交时写进去的,
#    要等外层提交才算数;外层回滚了,事务结束之后照样补写。
#
# 归属(这条账记在谁、哪个工作区名下)按调用发生时定:`workspace_id` 显式给的优先,否则取环境上下文;`job_id` 同理
# (见 billable)。写入时间推迟,归属不跟着变。
#
# 代价:进程在调用之后、调用方事务结束之前没了,这一笔账就没了 —— 和账写进调用方事务时一样(那时同样跟着丢)。

#: 这个会话里排着、还没随一次提交落库的账(列值、`supersedes`、这一回提交有没有写进去)。挂在 session.info 上而不是
#: 模块级 —— 后台线程各有各的会话。
_QUEUED = "mosael_queued_usage"


def _write_after_caller(db: Session, values: dict[str, Any], *, supersedes: str | None) -> None:
    db.info.setdefault(_QUEUED, []).append({"values": values, "supersedes": supersedes, "written": False})


def _queued_usage(db: Session, idempotency_key: str) -> ProviderUsageEvent | None:
    for queued in db.info.get(_QUEUED, ()):
        if queued["values"]["idempotency_key"] == idempotency_key:
            return ProviderUsageEvent(**queued["values"])
    return None


@orm_event.listens_for(Session, "before_commit")
def _write_with_the_caller(session: Session) -> None:
    """调用方提交的那一刻:排着的账写进这次提交。提交成功之前不从队里摘(见 _settled_with_the_caller)。

    先把调用方还没 flush 的东西 flush 掉(提交本来就要 flush):账上引用的任务、消息可能就是这一次刚建的,不先落进事务,
    下面核对引用时会当成「已经没了」置空。"""
    unwritten = [queued for queued in session.info.get(_QUEUED, ()) if not queued["written"]]
    if not unwritten:
        return
    session.flush()
    for queued in unwritten:
        _write(session, queued["values"], supersedes=queued["supersedes"])
        queued["written"] = True


@orm_event.listens_for(Session, "after_commit")
def _settled_with_the_caller(session: Session) -> None:
    """根事务提交成功了:写进去的账随它落了库。保存点提交也发 after_commit —— 那时还在保存点里(外层还可能回滚),不摘。"""
    if session.in_nested_transaction():
        return
    session.info.pop(_QUEUED, None)


@orm_event.listens_for(Session, "after_transaction_end")
def _settle_usage(session: Session, transaction: SessionTransaction) -> None:
    """调用方的根事务结束了、账还排着(回滚、没提交就关、提交失败):用一个新会话、一个短事务补写。"""
    if transaction.parent is not None:
        return  # 保存点结束不算:外层事务还没完
    queued = session.info.pop(_QUEUED, None)
    if not queued:
        return
    from app.core.unit_of_work import unit_of_work

    try:
        with unit_of_work() as fresh:
            for one in queued:
                _write(fresh, one["values"], supersedes=one["supersedes"])
    except Exception:  # noqa: BLE001 — 记账是旁路,写失败也不该把调用方带下水(unit_of_work 已回滚)
        logger.warning("用量入账失败,已忽略", exc_info=True)


def _write(db: Session, values: dict[str, Any], *, supersedes: str | None) -> None:
    """写一条账(已经在库里就什么都不做)。引用的行没了的置空;被接替的那一条在同一个事务里撤下。"""
    key = values["idempotency_key"]
    if db.scalar(select(ProviderUsageEvent.id).where(ProviderUsageEvent.idempotency_key == key)) is not None:
        return
    values = dict(values)
    for fk in ProviderUsageEvent.__table__.foreign_keys:
        column = fk.parent.key
        if values.get(column) is None:
            continue
        target = fk.column
        if db.scalar(select(target).where(target == values[column])) is not None:
            continue
        if fk.ondelete != "SET NULL":
            logger.warning("用量入账跳过:%s=%s 已不存在(idempotency_key=%s)", column, values[column], key)
            return
        values[column] = None
    if supersedes:
        replaced = db.scalar(select(ProviderUsageEvent).where(ProviderUsageEvent.idempotency_key == supersedes))
        if replaced is not None:
            db.delete(replaced)
            db.flush()
    event = ProviderUsageEvent(**values)
    db.add(event)
    db.flush()
    _announce(db, event)


def _normalize_pricing_fields(fields: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    normalized = dict(fields)
    for key in ("workspace_id", "provider_profile_id"):
        if key in normalized:
            normalized[key] = str(normalized[key]).strip() if normalized[key] else None
    for key in ("provider", "capability", "model", "billing_unit", "currency", "source", "notes"):
        if key in normalized and normalized[key] is not None:
            normalized[key] = str(normalized[key]).strip()
    if "resolution" in normalized:
        normalized["resolution"] = normalize_resolution(normalized["resolution"])
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
    if "time_prices" in normalized or "time_zone" in normalized:
        normalized["time_prices"], normalized["time_zone"] = normalize_schedule(
            normalized.get("time_prices"), normalized.get("time_zone")
        )
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
    moment: datetime | None = None,
) -> ProviderPricingRule | None:
    rules = _best_price_rules(
        db,
        workspace_id=workspace_id,
        provider_profile_id=provider_profile_id,
        provider=provider,
        capability=capability,
        model=model,
        moment=moment,
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
    moment: datetime | None = None,
    resolution: str = "",
) -> list[ProviderPricingRule]:
    """每个计价单位挑一条规则:作用域最具体的那条(连接 > 工作区 > 供应商 > 模型),同一作用域里
    写了分辨率的压过不限分辨率的,再同分取生效最晚的。

    **分辨率排在作用域之后。**给这条连接、这个工作区单配的价是用户的意图(谈下来的折扣常常不分档),
    不该被一条更细分辨率的通用价悄悄压过;同一作用域里,对上这次分辨率的那一档才比「不限」更准。
    写了分辨率、但和这次调用对不上的规则根本不进候选 —— 4k 没有价就是没有价,不拿 720p 的顶上。

    **时间只用来判生效期,不参与挑选。**分时段价格是挑出来那条规则**自己**的价目,由
    `price_schedule.price_at` 在算钱时取档 —— 挑规则和取单价是两件事(见 domain/billing/price_schedule)。
    """
    moment = moment or now()
    candidates = list(
        db.scalars(
            select(ProviderPricingRule).where(
                ProviderPricingRule.capability == capability,
                or_(ProviderPricingRule.resolution == "", ProviderPricingRule.resolution == normalize_resolution(resolution)),
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

    def score(rule: ProviderPricingRule) -> tuple[int, int, datetime]:
        specificity = 0
        specificity += 8 if rule.provider_profile_id else 0
        specificity += 4 if rule.workspace_id else 0
        specificity += 2 if rule.provider else 0
        specificity += 1 if rule.model else 0
        return specificity, 1 if rule.resolution else 0, rule.effective_from or datetime.min

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
        "audio": ("audio", "audios", "audio_count"),
        "audio_second": ("audio_second", "audio_seconds", "duration_seconds"),
        "character": ("character", "characters", "input_characters"),
        "token": ("token", "tokens", "total_token", "total_tokens"),
        # 注意 prompt_tokens 只作为 input_token 的**兜底**别名:适配器直接给 input_tokens 时
        # 用它(已扣除缓存);只有那些自己不拆分的来源才会落到 prompt_tokens 上。
        "input_token": ("input_token", "input_tokens", "prompt_tokens"),
        "output_token": ("output_token", "output_tokens", "completion_tokens"),
        "cache_read_token": ("cache_read_token", "cache_read_tokens", "cached_tokens"),
        "cache_write_token": ("cache_write_token", "cache_write_tokens"),
        "image_input_token": ("image_input_token", "image_input_tokens"),
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
    #: 服务商回报的这一次实扣(见 report_cost)。为空就按计价规则估。
    cost_micros: int | None = None
    currency: str = "USD"
    cost_confidence: str = "unknown"
    #: 记账落库后由 billable 填上,供调用方读取算好的成本(智能体把它写进消息 payload)。
    event: ProviderUsageEvent | None = None
    #: 调用方**捕获了**异常自己处理时,用它显式标失败 —— 异常没往外抛,billable 看不见。
    status: str = "succeeded"

    def mark_failed(self) -> None:
        self.status = "failed"

    def report_cost(self, micros: int, currency: str) -> None:
        """服务商在回包里报了这一次实扣多少钱:直接记它(`reported`),不再拿价目去估。币种照它报的。"""
        self.cost_micros = int(micros)
        self.currency = (currency or "USD").upper()
        self.cost_confidence = "reported"

    def mark_free(self) -> None:
        """这一次不花钱(免费的引擎):记 0,可信度 `free` —— 不拿价目去估,也不落成「没能定价」。"""
        self.cost_micros = 0
        self.cost_confidence = "free"

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
    user_id: str | None,
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
    supersedes: str | None = None,
) -> Iterator[BillableCall]:
    """包住一次供应商调用,结束时记一条账。

    - **归属**:显式 workspace_id 优先;没给就取环境上下文(权限闸门绑的,见 core/usage_scope)。`job_id` 同理:
      没给就挂在当前正在执行的任务上(见 jobs.current_parent_job_id)。
      两个都没有时不记账,但会 warning 出来 —— 静默漏记正是这次要终结的毛病。
    - **替谁花的钱**(`user_id`,必填,ADR 0050 D30):调用点自己说 —— 就是它拿来挑连接、用钥匙和额度的那个人。不从环境
      里取:工作区是「这次请求关于哪个工作区」,一个就够;人在智能体、定时任务、工作流节点里各有各的说法(会话主人、任务主人、
      运行的发起人),只有调用点知道这一次是哪一种。
    - **调用期间不写进调用方的会话**(D66):`db` 只拿来读价目;这条账随 `db` 提交的那一刻一起落库,没提交的在事务结束
      之后补写(契约见上面「账随调用方提交的那一刻落库」)。调用方照常提交或回滚,不必为账操心,也不会因为记账而攥着
      写锁跨过下一次供应商调用。块结束之后 `call.event` 是算好成本、还没落库的那一条。
    - `supersedes`:这一条接替的那一条账的键(见 superseded_attempt),写这一条时一并撤下。
    - **成败**:块里抛异常就记 failed 再原样抛出。失败的调用照样记一条 ——"最近失败了多少次"
      本身就是用户想在账上看到的;服务商回报了用量或扣费的照它计价,什么都没回的记 0
      (`not_billed`,见 record_usage)。
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
        #: 没说挂在哪个任务上的,挂在**这次调用发生在其中的那个任务**上(工作流节点、任务的执行体都立了它,
        #: 见 jobs.set_parent_job)—— 和归属取环境上下文同一个做法。此前工作流里大模型的调用都没挂上,按运行汇总的
        #: 费用、管理页按人分的花费(顺着任务找是谁花的)都漏掉它们。
        job_id=job_id if job_id is not None else current_parent_job_id(),
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
                    user_id=user_id,
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
                    currency=call.currency,
                    cost_confidence=call.cost_confidence,
                    supersedes=supersedes,
                )
            except Exception:  # noqa: BLE001 — 记账是旁路,不该把主流程带下水
                logger.warning("用量入账失败(%s),已忽略", operation, exc_info=True)


def follow_moved_models(db: Session, profile_id: str, renames: dict[str, str], *, why: str = "moved") -> None:
    """连接上的模型改了名(ADR 0045,见 providers.moved_models):这条连接上记的用量、按这条连接定的价跟着改到新名字 ——
    它们说的就是改名之后叫新名字的那一个(ComfyUI 有表单的工作流,以前路径指那张表单)。用量是事实记录,只改名、不动别的。"""
    for source, target in renames.items():
        db.execute(
            update(ProviderUsageEvent)
            .where(ProviderUsageEvent.provider_profile_id == profile_id, ProviderUsageEvent.model == source)
            .values(model=target)
        )
        db.execute(
            update(ProviderPricingRule)
            .where(ProviderPricingRule.provider_profile_id == profile_id, ProviderPricingRule.model == source)
            .values(model=target)
        )
