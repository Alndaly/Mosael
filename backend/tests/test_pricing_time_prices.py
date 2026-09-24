"""分时段价格:一条规则的单价随调用发生的时刻变(见 app/domain/price_schedule)。

盯的是四件事:

1. **取档对不对** —— 跨午夜、按星期、时区换算、左闭右开的边界;
2. **挑规则不看时间** —— 作用域更具体的规则赢,哪怕别的规则上有个此刻正生效的时段;
3. **按发生的时刻算** —— `occurred_at` 决定取哪一档,也就是账上的 `created_at`;
4. **写错的时段拦在门口**,报错带界面语言。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import ProviderPricingRule
from app.domain.price_schedule import PriceScheduleError, normalize_schedule, price_at, window_at
from app.domain.usage import create_pricing_rule, record_usage
from tests.util import fresh_client

#: DeepSeek 的形状:基础价是空闲价,工作日两段高峰。
PEAK = [
    {"start": "09:00", "end": "12:00", "weekdays": [1, 2, 3, 4, 5], "unit_amount_micros": 2_000_000},
    {"start": "14:00", "end": "18:00", "weekdays": [1, 2, 3, 4, 5], "unit_amount_micros": 2_000_000},
]
#: 2026-09-21 是周一。
MONDAY = 21


@dataclass
class Rule:
    unit_amount_micros: int
    time_prices: list[dict[str, Any]] = field(default_factory=list)
    time_zone: str = ""


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    """库里存的是 naive UTC —— 测试用同样的形状喂进去。"""
    return datetime(2026, 9, day, hour, minute)


# ---------- 取档 ----------


def test_utc_moment_is_read_in_the_rules_time_zone() -> None:
    """北京时间 = UTC+8。UTC 01:30 是北京 09:30(高峰),UTC 05:00 是北京 13:00(午间空闲)。"""
    rule = Rule(1_000_000, PEAK, "Asia/Shanghai")
    assert price_at(rule, utc(MONDAY, 1, 30)) == 2_000_000
    assert price_at(rule, utc(MONDAY, 5)) == 1_000_000
    assert price_at(rule, utc(MONDAY, 6)) == 2_000_000  # 北京 14:00,左闭
    assert price_at(rule, utc(MONDAY, 10)) == 1_000_000  # 北京 18:00,右开
    assert price_at(rule, utc(MONDAY, 9, 59)) == 2_000_000  # 北京 17:59


def test_weekdays_limit_the_window() -> None:
    """周六北京 10:00 不是高峰;周五是。"""
    rule = Rule(1_000_000, PEAK, "Asia/Shanghai")
    assert price_at(rule, utc(MONDAY + 4, 2)) == 2_000_000  # 周五
    assert price_at(rule, utc(MONDAY + 5, 2)) == 1_000_000  # 周六


def test_the_utc_date_can_differ_from_the_local_date() -> None:
    """UTC 周日 17:00 = 北京周一 01:00;UTC 周一 17:00 = 北京周二 01:00。星期要按当地算。"""
    night = [{"start": "00:30", "end": "08:30", "weekdays": [1], "unit_amount_micros": 500_000}]
    rule = Rule(1_000_000, night, "Asia/Shanghai")
    assert price_at(rule, utc(MONDAY - 1, 17)) == 500_000
    assert price_at(rule, utc(MONDAY, 17)) == 1_000_000


def test_window_wraps_past_midnight_and_belongs_to_the_day_it_starts() -> None:
    """周一至周五 22:00–08:00:周五夜里跨进周六早上的那段算周五的;周日夜里不算。"""
    night = [{"start": "22:00", "end": "08:00", "weekdays": [1, 2, 3, 4, 5], "unit_amount_micros": 300_000}]
    rule = Rule(1_000_000, night, "UTC")
    assert price_at(rule, utc(MONDAY + 4, 23)) == 300_000  # 周五 23:00
    assert price_at(rule, utc(MONDAY + 5, 7, 59)) == 300_000  # 周六 07:59,仍是周五那段
    assert price_at(rule, utc(MONDAY + 5, 8)) == 1_000_000  # 周六 08:00,右开
    assert price_at(rule, utc(MONDAY + 5, 23)) == 1_000_000  # 周六夜里不是
    assert price_at(rule, utc(MONDAY + 7, 3)) == 1_000_000  # 下周一凌晨:属于周日那段,周日不在
    assert price_at(rule, utc(MONDAY + 1, 3)) == 300_000  # 周二凌晨:周一那段


def test_window_ending_at_midnight_runs_to_the_end_of_the_day() -> None:
    evening = [{"start": "18:00", "end": "00:00", "weekdays": [], "unit_amount_micros": 1}]
    rule = Rule(9, evening, "UTC")
    assert price_at(rule, utc(MONDAY, 23, 59)) == 1
    assert price_at(rule, utc(MONDAY + 1, 0)) == 9


def test_time_zone_with_daylight_saving() -> None:
    """纽约冬夏差一小时:同一个当地钟点,UTC 时刻不一样 —— 规则照当地钟点写,不必自己换算。"""
    nine_to_ten = [{"start": "09:00", "end": "10:00", "weekdays": [], "unit_amount_micros": 7}]
    rule = Rule(1, nine_to_ten, "America/New_York")
    assert price_at(rule, datetime(2026, 7, 1, 13, 30)) == 7  # 夏令时 UTC-4
    assert price_at(rule, datetime(2026, 12, 1, 13, 30)) == 1  # 冬令时 UTC-5,当地 08:30
    assert price_at(rule, datetime(2026, 12, 1, 14, 30)) == 7


def test_no_schedule_means_the_base_price_all_day() -> None:
    assert price_at(Rule(42), utc(MONDAY, 3)) == 42
    assert window_at([], "", utc(MONDAY, 3)) is None


# ---------- 校验 ----------


def test_schedule_is_normalized() -> None:
    windows, zone = normalize_schedule(
        [
            {"start": "14:00", "end": "18:00", "weekdays": [5, 1, 3, 3], "unit_amount_micros": 2},
            {"start": "09:00", "end": "12:00", "weekdays": [1, 2, 3, 4, 5, 6, 7], "unit_amount_micros": 2},
        ],
        " Asia/Shanghai ",
    )
    assert zone == "Asia/Shanghai"
    assert windows == [
        {"start": "09:00", "end": "12:00", "weekdays": [], "unit_amount_micros": 2},
        {"start": "14:00", "end": "18:00", "weekdays": [1, 3, 5], "unit_amount_micros": 2},
    ], "七天全选存成空;星期去重排好;时段按开始时刻排"
    assert normalize_schedule([], "Asia/Shanghai") == ([], ""), "没有时段就没有时区"


@pytest.mark.parametrize(
    ("windows", "zone", "key"),
    [
        (PEAK, "", "pricingErr_timeZoneRequired"),
        (PEAK, "Mars/Olympus", "pricingErr_timeZone"),
        ([{"start": "9:00", "end": "12:00", "unit_amount_micros": 1}], "UTC", "pricingErr_windowClock"),
        ([{"start": "24:00", "end": "02:00", "unit_amount_micros": 1}], "UTC", "pricingErr_windowClock"),
        ([{"start": "09:00", "end": "09:00", "unit_amount_micros": 1}], "UTC", "pricingErr_windowEmpty"),
        ([{"start": "09:00", "end": "10:00", "weekdays": [0], "unit_amount_micros": 1}], "UTC", "pricingErr_windowWeekdays"),
        ([{"start": "09:00", "end": "10:00", "unit_amount_micros": -1}], "UTC", "pricingErr_windowAmount"),
        (
            [
                {"start": "09:00", "end": "12:00", "unit_amount_micros": 1},
                {"start": "11:00", "end": "13:00", "unit_amount_micros": 2},
            ],
            "UTC",
            "pricingErr_windowOverlap",
        ),
        # 周五 22:00–08:00 伸进了周六早上,和周六 07:00 开始的那段撞上。
        (
            [
                {"start": "22:00", "end": "08:00", "weekdays": [5], "unit_amount_micros": 1},
                {"start": "07:00", "end": "09:00", "weekdays": [6], "unit_amount_micros": 2},
            ],
            "UTC",
            "pricingErr_windowOverlap",
        ),
        # 周日夜里跨过一周的边界,撞上周一凌晨那段。
        (
            [
                {"start": "22:00", "end": "02:00", "weekdays": [7], "unit_amount_micros": 1},
                {"start": "01:00", "end": "03:00", "weekdays": [1], "unit_amount_micros": 2},
            ],
            "UTC",
            "pricingErr_windowOverlap",
        ),
    ],
)
def test_bad_schedules_are_rejected(windows: list[dict[str, Any]], zone: str, key: str) -> None:
    with pytest.raises(PriceScheduleError) as caught:
        normalize_schedule(windows, zone)
    assert caught.value.key == key


def test_same_hours_on_different_days_do_not_overlap() -> None:
    windows, _ = normalize_schedule(
        [
            {"start": "09:00", "end": "18:00", "weekdays": [1, 2, 3, 4, 5], "unit_amount_micros": 2},
            {"start": "09:00", "end": "18:00", "weekdays": [6, 7], "unit_amount_micros": 1},
        ],
        "UTC",
    )
    assert len(windows) == 2


def test_api_rejects_a_bad_schedule_in_the_callers_language() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    body = {
        "workspace_id": ws,
        "capability": "chat",
        "billing_unit": "million_input_token",
        "unit_amount_micros": 1_000_000,
        "time_prices": [
            {"start": "09:00", "end": "12:00", "unit_amount_micros": 2_000_000},
            {"start": "11:00", "end": "13:00", "unit_amount_micros": 2_000_000},
        ],
        "time_zone": "Asia/Shanghai",
    }
    zh = client.post("/api/settings/provider-pricing-rules", json=body, headers={"Accept-Language": "zh-CN"})
    en = client.post("/api/settings/provider-pricing-rules", json=body, headers={"Accept-Language": "en"})
    assert zh.status_code == en.status_code == 422
    assert "第 1 个和第 2 个时段有重叠" in zh.json()["detail"]
    assert "Time slots 1 and 2 overlap" in en.json()["detail"]


def test_api_round_trips_a_schedule_and_patches_the_zone_alone() -> None:
    """只改时区也要拿原来的时段一起校验、一起存。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(
        "/api/settings/provider-pricing-rules",
        json={
            "workspace_id": ws,
            "capability": "chat",
            "billing_unit": "million_input_token",
            "unit_amount_micros": 1_000_000,
            "time_prices": PEAK,
            "time_zone": "Asia/Shanghai",
            "currency": "CNY",
        },
    )
    assert created.status_code == 200, created.text
    rule = created.json()
    assert rule["time_prices"] == PEAK and rule["time_zone"] == "Asia/Shanghai"

    moved = client.patch(f"/api/settings/provider-pricing-rules/{rule['id']}", json={"time_zone": "Europe/Berlin"})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["time_prices"], moved.json()["time_zone"]) == (PEAK, "Europe/Berlin")
    bad = client.patch(f"/api/settings/provider-pricing-rules/{rule['id']}", json={"time_zone": "Nowhere/Land"})
    assert bad.status_code == 422

    cleared = client.patch(f"/api/settings/provider-pricing-rules/{rule['id']}", json={"time_prices": []}).json()
    assert (cleared["time_prices"], cleared["time_zone"]) == ([], ""), "去掉时段,时区一并清空"


# ---------- 记账 ----------


def _ws() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _record(db, ws: str, key: str, when: datetime | None, **extra: Any):
    return record_usage(
        db,
        workspace_id=ws,
        provider="deepseek",
        model="deepseek-flash",
        capability="chat",
        operation="agent_turn",
        idempotency_key=key,
        units={"input_tokens": 1_000_000},
        occurred_at=when,
        **extra,
    )


def test_record_usage_prices_by_when_the_call_happened() -> None:
    ws = _ws()
    with SessionLocal() as db:
        create_pricing_rule(
            db,
            workspace_id=ws,
            provider="deepseek",
            model="deepseek-flash",
            capability="chat",
            billing_unit="million_input_token",
            unit_amount_micros=1_000_000,
            currency="CNY",
            time_prices=PEAK,
            time_zone="Asia/Shanghai",
        )
        peak = _record(db, ws, "peak", utc(MONDAY, 1, 30))  # 北京周一 09:30
        lunch = _record(db, ws, "lunch", utc(MONDAY, 5))  # 北京周一 13:00
        weekend = _record(db, ws, "weekend", utc(MONDAY + 5, 2))  # 北京周六 10:00
        db.commit()

    assert (peak.cost_micros, lunch.cost_micros, weekend.cost_micros) == (2_000_000, 1_000_000, 1_000_000)
    assert peak.currency == "CNY"
    assert peak.created_at == utc(MONDAY, 1, 30), "账上的时间就是算价用的时间"


def test_rule_choice_ignores_time_of_day() -> None:
    """连接级的规则比工作区级的更具体。工作区那条上有个此刻正生效的便宜时段,也轮不到它 ——
    时间只决定**挑出来那条规则**取哪一档,不参与挑规则。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    profile = client.post(
        "/api/settings/providers", json={"name": "ds", "vendor": "deepseek", "config": {"api_key": "k"}}
    ).json()
    with SessionLocal() as db:
        create_pricing_rule(
            db,
            workspace_id=ws,
            provider="deepseek",
            model="deepseek-flash",
            capability="chat",
            billing_unit="million_input_token",
            unit_amount_micros=5_000_000,
            time_prices=[{"start": "00:00", "end": "12:00", "weekdays": [], "unit_amount_micros": 1}],
            time_zone="UTC",
        )
        create_pricing_rule(
            db,
            provider_profile_id=profile["id"],
            provider="deepseek",
            model="deepseek-flash",
            capability="chat",
            billing_unit="million_input_token",
            unit_amount_micros=3_000_000,
        )
        event = _record(db, ws, "scoped", utc(MONDAY, 6), provider_profile_id=profile["id"])
        db.commit()
    assert event.cost_micros == 3_000_000


def test_effective_period_is_judged_at_the_occurrence_time() -> None:
    """补记一笔昨天的账,要按昨天生效的那条规则算,不是按今天的。"""
    ws = _ws()
    with SessionLocal() as db:
        db.add(
            ProviderPricingRule(
                workspace_id=ws,
                provider="deepseek",
                model="deepseek-flash",
                capability="chat",
                billing_unit="million_input_token",
                unit_amount_micros=7,
                effective_to=datetime(2026, 9, 22),
            )
        )
        db.flush()
        before = _record(db, ws, "before", utc(MONDAY, 3))
        after = _record(db, ws, "after", utc(MONDAY + 2, 3))
        db.commit()
    assert (before.cost_micros, after.cost_micros) == (7, None)


# ---------- 迁移 ----------


def test_migrate_pricing_time_prices_adds_the_columns_once() -> None:
    """老库的规则没有这两列:迁移补上,老规则 = 全天一个价(空时段、空时区),重跑什么都不做。"""
    from sqlalchemy import text

    from app.core.db import engine
    from app.db.migrations import _migrate_pricing_time_prices

    ws = _ws()
    with SessionLocal() as db:
        rule = create_pricing_rule(
            db, workspace_id=ws, capability="chat", billing_unit="million_input_token", unit_amount_micros=9
        )
        rule_id = rule.id
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_pricing_rules DROP COLUMN time_prices"))
        conn.execute(text("ALTER TABLE provider_pricing_rules DROP COLUMN time_zone"))
    _migrate_pricing_time_prices()
    _migrate_pricing_time_prices()
    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(provider_pricing_rules)"))]
        kept = conn.execute(
            text("SELECT unit_amount_micros, time_prices, time_zone FROM provider_pricing_rules WHERE id = :id"),
            {"id": rule_id},
        ).one()
    assert columns.count("time_prices") == 1 and columns.count("time_zone") == 1
    assert tuple(kept) == (9, "[]", "")
    with SessionLocal() as db:
        loaded = db.get(ProviderPricingRule, rule_id)
        assert (loaded.time_prices, loaded.time_zone) == ([], "")
        assert price_at(loaded, utc(MONDAY, 3)) == 9
