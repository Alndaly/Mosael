"""**分时段价格:一条计价规则在一天(一周)里的不同时段收不同的钱。**

## 为什么是规则上的一张价目,而不是几条互相竞争的规则

DeepSeek 工作日白天是高峰价、其余时间半价 —— 这是**同一个模型、同一个计价单位的一个价**,只是
随时间变。把它拆成「默认规则 + 带时段的规则」两条,就得让时段参与 `_best_price_rules` 的挑选:
挑规则(按作用域谁更具体)和算单价(按时间取哪一档)两件事搅在一起,用户删掉其中一条也不会
察觉账已经错了一半。

所以两步分开:

1. `usage._best_price_rules` **照旧**只按作用域挑出一条规则 —— 时间不参与;
2. `price_at(rule, when)` 在这条规则自己的价目里,按调用发生的时刻(换算到规则的时区)取一档:
   落在哪个时段就用那个时段的价,哪个都不落就用规则的基础价 `unit_amount_micros`。

币种和计价单位跟着规则走,时段只改金额。

## 一个时段长什么样

`{"start": "09:00", "end": "12:00", "weekdays": [1, 2, 3, 4, 5], "unit_amount_micros": 2000000}`

- `start` / `end` 是规则时区里的钟点(`HH:MM`),**左闭右开**。`end` 比 `start` 早就是跨过了
  午夜(`22:00`–`08:00`);`end` 为 `00:00` 就是到当天结束。两者相同不允许 —— 那既可能是
  「一整天」也可能是「零分钟」,说不清。
- `weekdays` 是 ISO 星期(1 = 周一 … 7 = 周日),空 = 每天。**按时段开始的那天算**:周五
  `22:00`–`08:00` 覆盖到周六早上八点。DeepSeek 的高峰只在工作日,所以这一项不是摆设。
- 同一条规则里的时段不许重叠:否则同一时刻有两个价,取哪个全凭列表顺序。

时区是整条规则一个(`time_zone`,IANA 名):厂商按自己的当地时间公布时段(DeepSeek、方舟是
北京时间),规则照抄 —— 不必让用户自己换算成 UTC,也不会在夏令时切换时悄悄错一小时。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.i18n import LocalizedError

_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DAY = 24 * 60
_WEEK = 7 * _DAY
_ALL_DAYS = (1, 2, 3, 4, 5, 6, 7)


class PriceScheduleError(LocalizedError, ValueError):
    """时段价格写得不对。是 ValueError —— 计价规则的路由把 ValueError 一律转成 422。"""


class Priced(Protocol):
    unit_amount_micros: int
    time_prices: list[dict[str, Any]]
    time_zone: str


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise PriceScheduleError("pricingErr_timeZone", zone=name) from exc


def normalize_schedule(time_prices: Any, time_zone: Any) -> tuple[list[dict[str, Any]], str]:
    """校验并规整一条规则的分时段价格。返回 (时段列表, 时区);没有时段时时区一并清空。

    时段按(第一个适用的星期, 开始时刻)排好 —— 存下来的顺序就是界面列出来的顺序。
    """
    raw = list(time_prices or [])
    if not raw:
        return [], ""
    zone = str(time_zone or "").strip()
    if not zone:
        raise PriceScheduleError("pricingErr_timeZoneRequired")
    _zone(zone)

    windows: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise PriceScheduleError("pricingErr_windowClock", index=index)
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        if not _CLOCK.match(start) or not _CLOCK.match(end):
            raise PriceScheduleError("pricingErr_windowClock", index=index)
        if start == end:
            raise PriceScheduleError("pricingErr_windowEmpty", index=index)
        days = item.get("weekdays") or []
        if not isinstance(days, list) or any(isinstance(d, bool) or d not in _ALL_DAYS for d in days):
            raise PriceScheduleError("pricingErr_windowWeekdays", index=index)
        amount = item.get("unit_amount_micros")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise PriceScheduleError("pricingErr_windowAmount", index=index)
        days = sorted(set(days))
        # 七天全选和不选是一回事,存成同一个样子 —— 否则"是不是分星期"要判两种写法。
        windows.append(
            {
                "start": start,
                "end": end,
                "weekdays": [] if days == list(_ALL_DAYS) else days,
                "unit_amount_micros": amount,
            }
        )

    spans = [_week_spans(window) for window in windows]
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            if any(a < d and c < b for a, b in spans[i] for c, d in spans[j]):
                raise PriceScheduleError("pricingErr_windowOverlap", first=i + 1, second=j + 1)

    windows.sort(key=lambda w: ((w["weekdays"] or [1])[0], _minutes(w["start"])))
    return windows, zone


def _week_spans(window: dict[str, Any]) -> list[tuple[int, int]]:
    """把一个时段摊到一周(以周一 00:00 为 0 的分钟数)上,跨周日午夜的那段拆成两截。"""
    start, end = _minutes(window["start"]), _minutes(window["end"])
    length = end - start if end > start else end + _DAY - start
    spans: list[tuple[int, int]] = []
    for day in window["weekdays"] or _ALL_DAYS:
        begin = (day - 1) * _DAY + start
        finish = begin + length
        if finish <= _WEEK:
            spans.append((begin, finish))
        else:
            spans.extend(((begin, _WEEK), (0, finish - _WEEK)))
    return spans


def window_at(time_prices: list[dict[str, Any]], time_zone: str, when: datetime) -> dict[str, Any] | None:
    """`when`(UTC;naive 也按 UTC 读,和库里存的一致)落在哪个时段里,不落在任何时段就是 None。"""
    if not time_prices or not time_zone:
        return None
    moment = when if when.tzinfo else when.replace(tzinfo=UTC)
    local = moment.astimezone(_zone(time_zone))
    minute = local.hour * 60 + local.minute
    today = local.isoweekday()
    yesterday = (local - timedelta(days=1)).isoweekday()
    for window in time_prices:
        start, end = _minutes(window["start"]), _minutes(window["end"])
        days = window.get("weekdays") or _ALL_DAYS
        if start < end:
            hit = today in days and start <= minute < end
        else:
            # 跨午夜:午夜之前那段属于今天开始的时段,午夜之后那段属于昨天开始的。
            hit = (minute >= start and today in days) or (minute < end and yesterday in days)
        if hit:
            return window
    return None


def price_at(rule: Priced, when: datetime) -> int:
    """这条规则在 `when` 这一刻的单价(micros):落进哪个时段取那个时段的价,否则取基础价。"""
    window = window_at(rule.time_prices or [], rule.time_zone or "", when)
    return int(window["unit_amount_micros"]) if window is not None else int(rule.unit_amount_micros)
