"""人民币和美元**不相加**。

用户的原话:「不要把人民币和美元的费用加在一起。」计价规则带币种 —— 国内厂商按人民币、海外厂商
按美元(内置价目表保留厂商原币种)—— 而此前每一处汇总都是把 `cost_micros` 直接加起来,再贴上
「最近一条计过价的事件」的币种:¥12 + $4.5 显示成 16.5 USD。

所以这里每一条都用**同一组数**:一笔 ¥12(CNY 12_000_000 micros)、一笔 $4.5(USD 4_500_000)。
混加的结果是 16_500_000 —— 每条断言都顺带确认这个数哪里都不出现。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job, ProviderPricingRule, ProviderUsageEvent, User
from app.domain.usage import CostAmount, record_usage, summarize_usage
from tests.util import fresh_client, second_client

CNY = {"currency": "CNY", "micros": 12_000_000}
USD = {"currency": "USD", "micros": 4_500_000}
MIXED_SUM = 16_500_000


def _event(workspace_id: str, key: str, *, provider: str, micros: int | None, currency: str, **extra) -> ProviderUsageEvent:
    return ProviderUsageEvent(
        workspace_id=workspace_id,
        provider=provider,
        model=f"{provider}-model",
        capability="chat",
        operation="chat",
        idempotency_key=key,
        cost_micros=micros,
        currency=currency,
        cost_confidence="estimated" if micros is not None else "unknown",
        **extra,
    )


def _never_the_mixed_sum(payload: object) -> None:
    assert str(MIXED_SUM) not in str(payload), f"人民币和美元被加在了一起:{payload}"


def test_工作区汇总_每个币种一笔() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        # 人民币用得更多(两次),所以它排第一 —— 「主要用的那种钱」。
        db.add(_event(ws, "cny-1", provider="alibaba", micros=8_000_000, currency="CNY"))
        db.add(_event(ws, "cny-2", provider="alibaba", micros=4_000_000, currency="CNY"))
        db.add(_event(ws, "usd-1", provider="openai", micros=4_500_000, currency="USD"))
        db.add(_event(ws, "none-1", provider="openai", micros=None, currency="USD"))
        db.commit()

    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    assert summary["usage_costs"] == [CNY, USD]
    assert summary["usage_unknown_cost_events"] == 1
    # 逐日:同一天里两种钱各占一笔,图表按币种切换着看。
    assert summary["usage_daily"][-1]["costs"] == [CNY, USD]
    assert summary["usage_daily"][-1]["events"] == 4
    assert summary["usage_daily"][0]["costs"] == []
    # 按供应商:各家只有自己的币种。
    assert summary["usage_by_provider"] == {"alibaba": [CNY], "openai": [USD]}
    _never_the_mixed_sum(summary)


def test_同一家供应商两种币种也分开() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(_event(ws, "a", provider="openrouter", micros=12_000_000, currency="CNY"))
        db.add(_event(ws, "b", provider="openrouter", micros=4_500_000, currency="USD"))
        db.commit()
        summary = summarize_usage(db, workspace_id=ws)

    # 次数相同时按币种代码排 —— 顺序是确定的,不随查询返回的顺序漂。
    assert summary.by_provider == {"openrouter": [CostAmount("CNY", 12_000_000), CostAmount("USD", 4_500_000)]}
    assert summary.costs == [CostAmount("CNY", 12_000_000), CostAmount("USD", 4_500_000)]


def test_管理页按人分_每个人每个币种一笔() -> None:
    admin = fresh_client()
    ws = admin.post("/api/workspaces", json={"name": "W"}).json()["id"]
    second_client("mate")
    with SessionLocal() as db:
        users = {user.username: user.id for user in db.query(User).all()}
        mine = Job(workspace_id=ws, kind="test", payload={}, created_by=users["tester"])
        theirs = Job(workspace_id=ws, kind="test", payload={}, created_by=users["mate"])
        db.add_all([mine, theirs])
        db.flush()
        # tester:¥12 + $4.5;mate:¥20(人民币花得更多)。
        db.add(_event(ws, "t-cny", provider="alibaba", micros=12_000_000, currency="CNY", job_id=mine.id))
        db.add(_event(ws, "t-usd", provider="openai", micros=4_500_000, currency="USD", job_id=mine.id))
        db.add(_event(ws, "m-cny", provider="alibaba", micros=20_000_000, currency="CNY", job_id=theirs.id))
        db.commit()

    overview = admin.get("/api/admin/overview").json()
    assert overview["costs"] == [{"currency": "CNY", "micros": 32_000_000}, USD]
    rows = [(row["username"], row["costs"], row["calls"]) for row in overview["spend_by_user"]]
    # 按主要币种(人民币)上的金额排:mate 的 ¥20 在 tester 的 ¥12 之前 —— 而不是拿
    # tester 的 12 + 4.5 = 16.5 去和 20 比。
    assert rows == [
        ("mate", [{"currency": "CNY", "micros": 20_000_000}], 1),
        ("tester", [CNY, USD], 2),
    ]
    _never_the_mixed_sum(overview)


def test_一条生成的多个事件_按币种各自求和() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        gen = GenerationJob(workspace_id=ws, provider="x", model="y", kind="image", request={"prompt": "a"})
        db.add(gen)
        db.flush()
        for key, micros, currency in (("g1", 12_000_000, "CNY"), ("g2", 4_500_000, "USD")):
            db.add(_event(ws, key, provider="x", micros=micros, currency=currency, source_type="generation_job", source_id=gen.id))
        db.commit()
        gen_id = gen.id

    listed = {row["id"]: row for row in client.get(f"/api/generation/jobs?workspace_id={ws}").json()}
    assert listed[gen_id]["costs"] == [CNY, USD]
    assert listed[gen_id]["cost_confidence"] == "estimated"
    _never_the_mixed_sum(listed[gen_id])


def _rule(ws: str, unit: str, amount: int, currency: str) -> ProviderPricingRule:
    return ProviderPricingRule(
        workspace_id=ws, provider="deepseek", capability="chat", model="deepseek-v4",
        billing_unit=unit, unit_amount_micros=amount, currency=currency,
    )


def test_一次调用对上的规则币种不一致_整条记成未定价() -> None:
    """此前取第一条规则的币种、把另一币种的规则**静默跳过** —— 账上只剩一半,而且留下哪一半
    取决于查询返回的顺序。少算看不出是少算,比「未定价」更坏。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(_rule(ws, "million_input_token", 2_000_000, "CNY"))
        db.add(_rule(ws, "million_output_token", 1_000_000, "USD"))
        db.flush()
        event = record_usage(
            db, workspace_id=ws, provider="deepseek", model="deepseek-v4", capability="chat",
            operation="chat", idempotency_key="mixed", units={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        )
        db.commit()
        assert (event.cost_micros, event.cost_confidence, event.unpriced_reason) == (None, "unknown", "mixed_currency")
        assert event.pricing_rule_id is None
        summary = summarize_usage(db, workspace_id=ws)

    assert summary.costs == []
    # 缺价清单说得出**为什么**:规则是配了的,只是币种不一致。
    assert summary.unpriced == [
        {"provider": "deepseek", "model": "deepseek-v4", "capability": "chat", "reason": "mixed_currency", "events": 1}
    ]


def test_同一币种的规则照常相加() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(_rule(ws, "million_input_token", 2_000_000, "CNY"))
        db.add(_rule(ws, "million_output_token", 8_000_000, "CNY"))
        db.flush()
        event = record_usage(
            db, workspace_id=ws, provider="deepseek", model="deepseek-v4", capability="chat",
            operation="chat", idempotency_key="same", units={"input_tokens": 1_000_000, "output_tokens": 500_000},
        )
        db.commit()
    assert (event.cost_micros, event.currency, event.unpriced_reason) == (6_000_000, "CNY", None)


def test_没用上的那条规则不算混币种() -> None:
    """按次计价的美元规则在,但这次调用没报请求数 —— 它没参与计价,不该把人民币那笔弄没。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(_rule(ws, "million_input_token", 2_000_000, "CNY"))
        db.add(_rule(ws, "request", 1_000, "USD"))
        db.flush()
        event = record_usage(
            db, workspace_id=ws, provider="deepseek", model="deepseek-v4", capability="chat",
            operation="chat", idempotency_key="unused", units={"input_tokens": 1_000_000},
        )
        db.commit()
    assert (event.cost_micros, event.currency, event.unpriced_reason) == (2_000_000, "CNY", None)


def test_migrate_usage_unpriced_reason_adds_the_column_once() -> None:
    """老库的 provider_usage_events 没有 unpriced_reason:迁移补上这一列,老事件留空(当时没问过
    这个问题,也补不出来),重跑什么都不做。"""
    from sqlalchemy import text

    from app.core.db import engine
    from app.db.migrations import _migrate_usage_unpriced_reason

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(_event(ws, "old", provider="alibaba", micros=12_000_000, currency="CNY"))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_usage_events DROP COLUMN unpriced_reason"))
    _migrate_usage_unpriced_reason()
    _migrate_usage_unpriced_reason()
    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(provider_usage_events)"))]
        kept = conn.execute(
            text("SELECT cost_micros, currency, unpriced_reason FROM provider_usage_events WHERE idempotency_key = 'old'")
        ).one()
    assert columns.count("unpriced_reason") == 1
    assert tuple(kept) == (12_000_000, "CNY", None)
