"""积分账本(ADR 0088 §2):余额是流水的和;月度批次与到期按需补记;先扣快到期的;不够当场拒;结算多退。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from cloud.domain import credits
from cloud.errors import CloudError
from cloud.models import CloudGatewayCall, CloudPlan, CloudUsageEntry, CloudUser

T0 = datetime(2026, 1, 31, 12, 0)


@pytest.fixture
def db(app):
    with app.state.db.session() as session:
        yield session


@pytest.fixture
def user(db) -> CloudUser:
    found = CloudUser(email="alice@example.com")
    db.add(found)
    db.flush()
    return found


def plan(db, *, period: str = "month", monthly: int = 1000, ttl: int = 60) -> CloudPlan:
    found = CloudPlan(slug=f"p-{period}-{monthly}", name="Pro", period=period, monthly_credits=monthly, credit_ttl_days=ttl)
    db.add(found)
    db.flush()
    return found


def call(db, user: CloudUser, reserved: int) -> CloudGatewayCall:
    found = CloudGatewayCall(user_id=user.id, model_id="m", reserved=reserved)
    db.add(found)
    db.flush()
    return found


def test_add_months_clamps_to_the_last_day():
    assert credits.add_months(T0, 1) == datetime(2026, 2, 28, 12, 0)
    assert credits.add_months(T0, 12) == datetime(2027, 1, 31, 12, 0)


def test_chat_cost_rounds_up():
    assert credits.chat_cost(input_per_1k=1, output_per_1k=2, input_tokens=1, output_tokens=0) == 1
    assert credits.chat_cost(input_per_1k=1, output_per_1k=2, input_tokens=1000, output_tokens=500) == 2


def test_a_yearly_plan_grants_monthly_batches_that_expire(db, user):
    credits.subscribe(db, user, plan(db, period="year", monthly=1000, ttl=60), at=T0)
    assert credits.balance(db, user.id, at=T0).total == 1000

    #: 一个月后第二批到了,第一批还没过 60 天:两批都在。
    one_month = credits.balance(db, user.id, at=T0 + timedelta(days=31))
    assert one_month.total == 2000
    assert [one.remaining for one in one_month.batches] == [1000, 1000]

    #: 第 60 天(4 月 1 日):第一批到期清零;第三批 3 月 31 日已到 —— 按开通日数月,没有漂成 3 月 28 日。
    later = credits.balance(db, user.id, at=T0 + timedelta(days=60))
    assert later.total == 2000
    assert [one.expires_at - timedelta(days=60) for one in later.batches] == [datetime(2026, 2, 28, 12, 0),
                                                                             datetime(2026, 3, 31, 12, 0)]
    expired = db.scalars(select(CloudUsageEntry).where(CloudUsageEntry.kind == "expire")).all()
    assert [one.delta for one in expired] == [-1000]

    #: 再读一次:什么都不多写(幂等)。
    credits.balance(db, user.id, at=T0 + timedelta(days=60))
    assert len(db.scalars(select(CloudUsageEntry).where(CloudUsageEntry.kind == "expire")).all()) == 1


def test_a_plan_stops_granting_when_it_ends(db, user):
    credits.subscribe(db, user, plan(db, period="month", monthly=100, ttl=400), at=T0)
    #: 一年后:月付只发了开通那一批,订阅已结束,也就没有下一批。
    year_later = credits.balance(db, user.id, at=T0 + timedelta(days=365))
    assert year_later.total == 100
    assert year_later.next_grant_at is None


def test_reserve_takes_the_soonest_expiring_batch_first_and_settle_refunds(db, user):
    credits.gift(db, user, amount=50, days=10, note="welcome", at=T0)
    credits.subscribe(db, user, plan(db, monthly=1000, ttl=60), at=T0)

    first = call(db, user, reserved=120)
    credits.reserve(db, first, at=T0)
    batches = credits.balance(db, user.id, at=T0).batches
    #: 赠送的 10 天那批先扣光,剩下的 70 从月度那批出。
    assert [(one.source, one.remaining) for one in batches] == [("plan", 930)]

    credits.settle(db, first, charged=30, at=T0)
    assert first.status == "settled" and first.charged == 30
    #: 退回 90:后扣的先退 —— 月度那批拿回 70,赠送那批拿回 20。
    after = credits.balance(db, user.id, at=T0).batches
    assert [(one.source, one.remaining) for one in after] == [("gift", 20), ("plan", 1000)]
    assert credits.balance(db, user.id, at=T0).total == 1050 - 30


def test_release_returns_everything(db, user):
    credits.gift(db, user, amount=100, days=10, note="", at=T0)
    failed = call(db, user, reserved=80)
    credits.reserve(db, failed, at=T0)
    credits.settle(db, failed, charged=0, at=T0)
    assert failed.status == "released"
    assert credits.balance(db, user.id, at=T0).total == 100


def test_charge_is_capped_at_the_reservation(db, user):
    credits.gift(db, user, amount=100, days=10, note="", at=T0)
    over = call(db, user, reserved=40)
    credits.reserve(db, over, at=T0)
    credits.settle(db, over, charged=75, at=T0)
    assert over.charged == 40
    assert credits.balance(db, user.id, at=T0).total == 60


def test_not_enough_credits_is_a_402_that_says_how_much(db, user):
    #: 年付:下一批在一个月后(月付的「下一批」正好落在订阅结束那一刻,不再发 —— 续费是第 3 步的事)。
    credits.subscribe(db, user, plan(db, period="year", monthly=100, ttl=60), at=T0)
    big = call(db, user, reserved=150)
    with pytest.raises(CloudError) as raised:
        credits.reserve(db, big, at=T0)
    assert raised.value.status_code == 402
    assert raised.value.code == "insufficient_credits"
    assert raised.value.details["needed"] == 150
    assert raised.value.details["available"] == 100
    assert raised.value.details["next_grant_at"] == credits.add_months(T0, 1).isoformat()


def test_a_reserved_call_cannot_be_settled_twice(db, user):
    credits.gift(db, user, amount=10, days=1, note="", at=T0)
    once = call(db, user, reserved=5)
    credits.reserve(db, once, at=T0)
    credits.settle(db, once, charged=5, at=T0)
    with pytest.raises(ValueError):
        credits.settle(db, once, charged=0, at=T0)
