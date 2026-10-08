"""计价规则按**输出分辨率**分档。

生视频几乎家家按分辨率报价:万相 720P 0.6 元/秒、1080P 1 元/秒;海螺 H3 768P 0.5 元/秒、2K 0.8 元/秒;
Evolink 上的 Seedance 2.5 480p / 720p / 1080p 三个价。此前规则没有分辨率这一格,只能记一档、把其余档
写在备注里 —— 而万相在应用里默认就是 1080P、海螺 H3 默认 2K,于是默认参数跑出来的每一条都按便宜那档记,
少算四成。

规则多一格 `resolution`(空 = 不限分辨率)。挑规则时它和作用域一起排序:作用域先比(给这条连接、这个
工作区单配的价是用户的意图,不该被一条更细分辨率的通用价压过),同一作用域里写了分辨率的压过不限的。
计量里的分辨率是请求时就定了的(`units.resolution`),大小写不论(万相写 1080P,Evolink 写 1080p)。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.domain.billing.usage import create_pricing_rule, record_usage
from tests.util import fresh_client


def _ws() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _record(db, ws: str, *, provider: str, model: str, units: dict, key: str):
    return record_usage(
        db,
        user_id=None,
        workspace_id=ws,
        provider=provider,
        model=model,
        capability="video",
        operation="generation_job",
        idempotency_key=key,
        units=units,
    )


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [("2K", 4_800_000), ("768P", 3_000_000)],
)
def test_minimax_h3_is_priced_per_second_by_resolution(resolution: str, expected: int) -> None:
    """海螺 H3:768P 0.5 元/秒、2K 0.8 元/秒(platform.minimax.cn)。6 秒。"""
    ws = _ws()
    with SessionLocal() as db:
        create_pricing_rule(db, provider="minimax", capability="video", model="MiniMax-H3",
                            billing_unit="video_second", unit_amount_micros=500_000, currency="CNY")
        create_pricing_rule(db, provider="minimax", capability="video", model="MiniMax-H3", resolution="2K",
                            billing_unit="video_second", unit_amount_micros=800_000, currency="CNY")
        event = _record(db, ws, provider="minimax", model="MiniMax-H3", key=f"h3-{resolution}",
                        units={"requests": 1, "videos": 1, "video_seconds": 6.0, "resolution": resolution})
        db.commit()
    assert (event.cost_micros, event.currency) == (expected, "CNY")


def test_wan_at_its_default_1080p_is_not_priced_at_the_720p_rate() -> None:
    """万相 2.7 在应用里默认 1080P —— 此前按 720P 的 0.6 元记,每秒少记 0.4 元。"""
    ws = _ws()
    with SessionLocal() as db:
        create_pricing_rule(db, provider="alibaba", capability="video", model="wan2.7-t2v",
                            billing_unit="video_second", unit_amount_micros=600_000, currency="CNY")
        create_pricing_rule(db, provider="alibaba", capability="video", model="wan2.7-t2v", resolution="1080P",
                            billing_unit="video_second", unit_amount_micros=1_000_000, currency="CNY")
        hd = _record(db, ws, provider="alibaba", model="wan2.7-t2v", key="wan-1080",
                     units={"videos": 1, "video_seconds": 5.0, "resolution": "1080P"})
        sd = _record(db, ws, provider="alibaba", model="wan2.7-t2v", key="wan-720",
                     units={"videos": 1, "video_seconds": 5.0, "resolution": "720P"})
        db.commit()
    assert hd.cost_micros == 5_000_000
    assert sd.cost_micros == 3_000_000, "没单列的分辨率按不限分辨率的那条(基础档)记"


def test_a_resolution_nobody_priced_and_no_catch_all_stays_unpriced() -> None:
    ws = _ws()
    with SessionLocal() as db:
        create_pricing_rule(db, provider="evolink", capability="video", model="m", resolution="720p",
                            billing_unit="video_second", unit_amount_micros=296_000, currency="USD")
        event = _record(db, ws, provider="evolink", model="m", key="evo-4k",
                        units={"videos": 1, "video_seconds": 5.0, "resolution": "4k"})
        db.commit()
    assert event.cost_micros is None, "4k 没有价就不拿 720p 的价顶上"


def test_scope_outranks_resolution() -> None:
    """用户给这个工作区单配了一个不分档的价(谈下来的折扣):它压过一条更细分辨率的通用价。"""
    ws = _ws()
    with SessionLocal() as db:
        create_pricing_rule(db, workspace_id=ws, provider="alibaba", capability="video", model="wan2.7-t2v",
                            billing_unit="video_second", unit_amount_micros=450_000, currency="CNY")
        create_pricing_rule(db, provider="alibaba", capability="video", model="wan2.7-t2v", resolution="1080p",
                            billing_unit="video_second", unit_amount_micros=1_000_000, currency="CNY")
        event = _record(db, ws, provider="alibaba", model="wan2.7-t2v", key="wan-mine",
                        units={"videos": 1, "video_seconds": 2.0, "resolution": "1080P"})
        db.commit()
    assert event.cost_micros == 900_000


def test_the_rule_api_round_trips_a_normalized_resolution() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    created = client.post(
        "/api/settings/provider-pricing-rules",
        json={"provider": "minimax", "capability": "video", "model": "MiniMax-H3", "resolution": " 2K ",
              "billing_unit": "video_second", "unit_amount_micros": 800_000, "currency": "CNY"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["resolution"] == "2k"
    patched = client.patch(f"/api/settings/provider-pricing-rules/{created.json()['id']}", json={"resolution": "768P"})
    assert patched.json()["resolution"] == "768p"
    cleared = client.patch(f"/api/settings/provider-pricing-rules/{created.json()['id']}", json={"resolution": ""})
    assert cleared.json()["resolution"] == "", "清空 = 不限分辨率"


def test_migration_adds_the_resolution_column_once() -> None:
    """老库的规则没有这一列:补上,老规则 = 不限分辨率,重跑什么都不做。"""
    from sqlalchemy import text

    from app.core.db import engine
    from app.db.migrations import _migrate_pricing_rules_by_resolution

    _ws()
    with SessionLocal() as db:
        rule_id = create_pricing_rule(db, capability="video", billing_unit="video_second", unit_amount_micros=7).id
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_pricing_rules DROP COLUMN resolution"))
    _migrate_pricing_rules_by_resolution()
    _migrate_pricing_rules_by_resolution()
    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(provider_pricing_rules)"))]
        kept = conn.execute(text("SELECT resolution FROM provider_pricing_rules WHERE id = :id"), {"id": rule_id}).scalar()
    assert columns.count("resolution") == 1
    assert kept == ""
