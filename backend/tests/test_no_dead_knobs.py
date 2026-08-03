"""不留「存了但不起作用」的设置。

一个填得进去、存得下来、界面上看得见,却对行为毫无影响的开关,比没有这个开关坏得多 ——
用户按它调整过,以为调好了。

跑出来的两处:

    scheduled_tasks.timezone   存了,而 compute_next_run_at 只按 UTC 算 —— 在 +08 设"每天
                               09:00",实际 17:00 才跑。
    provider_defaults          同一件事存了两份:(provider_profile_id, model) 与 provider_model_id。
                               两份会漂移的真相里,总有一份是错的。
"""

from __future__ import annotations

from datetime import datetime

from app.domain.scheduler.operations import compute_next_run_at


def test_a_daily_schedule_fires_at_the_local_hour() -> None:
    """「每天 09:00」说的是**他那儿的** 09:00。"""
    reference = datetime(2026, 8, 4, 0, 0)  # UTC
    at = compute_next_run_at(
        "daily", {"time": "09:00"}, reference=reference, timezone="Asia/Shanghai"
    )
    assert at is not None
    assert at.hour == 1, f"上海的 09:00 是 UTC 01:00,算出来却是 {at}"


def test_a_weekly_schedule_uses_the_local_weekday() -> None:
    """跨日界的时候,"周一 09:00"在哪一天也得按他那儿算。"""
    reference = datetime(2026, 8, 4, 0, 0)  # 周二 UTC
    at = compute_next_run_at(
        "weekly", {"weekday": 0, "time": "09:00"}, reference=reference, timezone="Asia/Shanghai"
    )
    assert at is not None and at.hour == 1


def test_utc_stays_the_way_it_was() -> None:
    """没设时区(或设 UTC)的老任务行为不变。"""
    reference = datetime(2026, 8, 4, 0, 0)
    at = compute_next_run_at("daily", {"time": "09:00"}, reference=reference, timezone="UTC")
    assert at is not None and at.hour == 9


def test_an_unknown_timezone_does_not_take_the_scheduler_down() -> None:
    """时区名写错了就退回 UTC —— 一个任务的配置不该让整个调度器炸。"""
    reference = datetime(2026, 8, 4, 0, 0)
    at = compute_next_run_at("daily", {"time": "09:00"}, reference=reference, timezone="Mars/Olympus")
    assert at is not None and at.hour == 9


def test_provider_defaults_keeps_one_truth() -> None:
    """默认模型只存一处 —— 指向模型行。两份会漂移的真相里总有一份是错的。"""
    from app.db.models import ProviderDefault

    columns = set(ProviderDefault.__table__.columns.keys())
    assert "provider_model_id" in columns
    assert "provider_profile_id" not in columns, "旧的那一半还在"
    assert "model" not in columns, "旧的那一半还在"
