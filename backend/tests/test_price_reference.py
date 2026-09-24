"""内置的官方价目表:形状、查表规则、中转的借价规则。

这张表是**手写的查证结果**(见 app/domain/price_reference 模块头),没有任何上游会纠正它 ——
写错一个单位,生视频的账就差出几个数量级;少写一个来源,用户就没法核对那条规则是哪来的。
所以这里盯的是那几条**写表时容易违反的约定**,而不是逐条复读数字。
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.domain import price_reference
from app.domain.price_reference import LIST_PRICES, ListPrice, lookup, lookup_for_relay
from app.domain.provider_presets import KNOWN_CAPABILITY_IDS, provider_definition
from app.domain.usage import PRICING_BILLING_UNITS

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

#: 价目页的来源只能是厂商自己的域名 —— 第三方汇总站不算查证(约定 1)。
OFFICIAL_DOMAINS = (
    "api-docs.deepseek.com",
    "platform.kimi.com",
    "platform.kimi.ai",
    "docs.x.ai",
    "platform.claude.com",
    "help.aliyun.com",
    "www.alibabacloud.com",
    "www.volcengine.com",
    "docs.volcengine.com",
    "docs.byteplus.com",
    "platform.minimaxi.com",
    "platform.minimax.cn",
    "platform.minimax.io",
    "openai.com",
    "platform.openai.com",
    "developers.openai.com",
    "ai.google.dev",
    "app.klingai.com",
    "klingai.com",
)


def _label(entry: ListPrice) -> str:
    return f"{entry.vendor}/{entry.model}/{entry.billing_unit}/{entry.region}"


def test_every_entry_cites_an_official_page_and_a_check_date() -> None:
    for entry in LIST_PRICES:
        assert entry.source.startswith("https://"), f"{_label(entry)} 没有来源页"
        host = entry.source.removeprefix("https://").split("/", 1)[0]
        assert host in OFFICIAL_DOMAINS, f"{_label(entry)} 的来源 {host} 不是厂商官方域名"
        assert re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", entry.checked), f"{_label(entry)} 的查证日期写错了"


def test_every_entry_is_something_the_ledger_can_use() -> None:
    """单位、能力、厂商、币种、地区都得是系统认识的 —— 否则建出来的规则永远匹配不上。"""
    for entry in LIST_PRICES:
        assert entry.billing_unit in PRICING_BILLING_UNITS, f"{_label(entry)} 的单位 {entry.billing_unit} 不存在"
        assert entry.capability in KNOWN_CAPABILITY_IDS, f"{_label(entry)} 的能力 {entry.capability} 不存在"
        definition = provider_definition(entry.vendor)
        assert definition is not None, f"{_label(entry)} 的厂商 id 不存在"
        # 这家连接做不了的能力,记了也永远建不出规则 —— 等适配器接入、预设声明了再收。
        assert entry.capability in definition.capability_ids, f"{_label(entry)}:{entry.vendor} 不提供 {entry.capability}"
        assert entry.currency in ("CNY", "USD"), f"{_label(entry)} 的币种 {entry.currency}"
        assert entry.region in price_reference.REGIONS
        assert entry.model == entry.model.strip() and entry.model, f"{_label(entry)} 的模型 id 有空白"


def test_amounts_are_positive_and_convert_exactly() -> None:
    """金额为正(0 是「未标价」不是「免费」);换成 micros 不能丢精度 —— 丢了就和价目页对不上。"""
    for entry in LIST_PRICES:
        amount = Decimal(entry.amount)
        assert amount > 0, f"{_label(entry)} 的金额不是正数"
        micros = amount * 1_000_000 / entry.per
        assert micros == micros.to_integral_value(), f"{_label(entry)} 换算成 micros 有零头:{micros}"
        assert entry.unit_amount_micros > 0


def test_scaled_prices_say_what_the_vendor_listed() -> None:
    """`per` 不为 1 的(元/万字符)要在备注里写出厂商原话,否则规则里那个 0.0002 没人对得上。"""
    for entry in LIST_PRICES:
        if entry.per != 1:
            zh, en = entry.remark
            assert zh and en, f"{_label(entry)} 按 {entry.per} 计价却没写备注"


def test_remarks_come_in_both_languages() -> None:
    for entry in LIST_PRICES:
        zh, en = entry.remark
        assert bool(zh) == bool(en), f"{_label(entry)} 的备注只有一种语言"


def test_no_cell_is_written_twice() -> None:
    """同一格两个价,查表时谁赢是不确定的 —— 分档的价只记一档(约定 3)。"""
    seen: dict[tuple, ListPrice] = {}
    for entry in LIST_PRICES:
        key = (entry.vendor, entry.model.lower(), entry.prefix, entry.region, entry.capability, entry.billing_unit)
        assert key not in seen, f"{_label(entry)} 写了两遍"
        seen[key] = entry


def test_time_of_day_prices_are_well_formed() -> None:
    """分时段价(约定 4):时段过得了规则自己的校验、有时区、时段价同样为正且换算无零头;
    没有时段的条目不许带时区 —— 那是写到一半的条目。"""
    from app.domain.price_schedule import normalize_schedule

    for entry in LIST_PRICES:
        if not entry.time_prices:
            assert entry.time_zone == "", f"{_label(entry)} 没有时段却写了时区"
            continue
        assert entry.time_zone, f"{_label(entry)} 有时段却没写时区"
        windows, zone = normalize_schedule(list(entry.time_prices_micros), entry.time_zone)
        assert zone == entry.time_zone and len(windows) == len(entry.time_prices)
        for window in entry.time_prices:
            micros = Decimal(window.amount) * 1_000_000 / entry.per
            assert micros > 0 and micros == micros.to_integral_value(), f"{_label(entry)} 的时段价 {window.amount}"
        assert all(entry.remark), f"{_label(entry)} 分时段计价要在备注里说清基础价是哪一档"


def test_deepseek_is_priced_by_its_official_peak_hours() -> None:
    """官方原话:北京时间工作日 9:00–12:00、14:00–18:00 为高峰,其余为空闲,空闲是高峰的一半。"""
    entries = [entry for entry in LIST_PRICES if entry.vendor == "deepseek"]
    assert entries
    for entry in entries:
        assert entry.time_zone == "Asia/Shanghai"
        assert [(w.start, w.end, w.weekdays) for w in entry.time_prices] == [
            ("09:00", "12:00", (1, 2, 3, 4, 5)),
            ("14:00", "18:00", (1, 2, 3, 4, 5)),
        ], _label(entry)
        assert all(Decimal(w.amount) == Decimal(entry.amount) * 2 for w in entry.time_prices), _label(entry)


# ---------- 查表 ----------


def _fake(monkeypatch: pytest.MonkeyPatch, *entries: ListPrice) -> None:
    monkeypatch.setattr(price_reference, "LIST_PRICES", entries)


def _e(vendor: str, model: str, unit: str = "million_input_token", *, prefix: bool = False, region: str = "global") -> ListPrice:
    return ListPrice(vendor, model, "chat", unit, "1", "USD", "https://example.test", prefix=prefix, region=region)


def test_exact_id_beats_prefix_and_longest_prefix_wins(monkeypatch) -> None:
    _fake(
        monkeypatch,
        _e("openai", "gpt-9", prefix=True),
        _e("openai", "gpt-9-mini", prefix=True),
        _e("openai", "gpt-9-mini-2026", "million_output_token"),
    )
    assert [e.model for e in lookup("openai", "gpt-9-mini-2026")] == ["gpt-9-mini-2026"]
    assert [e.model for e in lookup("openai", "gpt-9-mini-0101")] == ["gpt-9-mini"]
    assert [e.model for e in lookup("openai", "GPT-9-turbo")] == ["gpt-9"], "大小写不该影响匹配"
    assert lookup("openai", "gpt-8") == []


def test_lookup_is_scoped_to_the_vendor(monkeypatch) -> None:
    """DeepSeek 的连接不该拿到百炼挂的同名模型的价,反之亦然。"""
    _fake(monkeypatch, _e("alibaba", "deepseek-v4-pro"))
    assert lookup("deepseek", "deepseek-v4-pro") == []
    assert len(lookup("alibaba", "deepseek-v4-pro")) == 1


def test_region_follows_the_endpoint(monkeypatch) -> None:
    _fake(monkeypatch, _e("alibaba", "qwen-x", region="cn"), _e("alibaba", "qwen-x", region="intl"))
    cn = price_reference.region_for("alibaba", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    intl = price_reference.region_for("alibaba", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    assert (cn, intl) == ("cn", "intl")
    assert [e.region for e in lookup("alibaba", "qwen-x", region=intl)] == ["intl"]
    assert [e.region for e in lookup("alibaba", "qwen-x", region=cn)] == ["cn"]


def test_relay_borrows_only_an_unambiguous_exact_id(monkeypatch) -> None:
    """中转后面是谁不知道:两家都卖同一个 id 就不借;前缀在中转上一律不认。"""
    _fake(
        monkeypatch,
        _e("anthropic", "claude-x"),
        _e("deepseek", "shared-id"),
        _e("alibaba", "shared-id"),
        _e("openai", "gpt-9", prefix=True),
    )
    assert [e.vendor for e in lookup_for_relay("claude-x")] == ["anthropic"]
    assert lookup_for_relay("shared-id") == [], "两家都有的 id 不知道是哪家的,不该借价"
    assert lookup_for_relay("gpt-9-mini") == [], "中转上不按前缀借价"


def test_relay_prefers_the_home_region(monkeypatch) -> None:
    _fake(monkeypatch, _e("alibaba", "qwen-x", region="intl"), _e("alibaba", "qwen-x", region="cn"))
    assert [e.region for e in lookup_for_relay("qwen-x")] == ["cn"]


@pytest.mark.parametrize(
    ("vendor", "base_url", "relay"),
    [
        ("openai-compatible", "https://api.147ai.com/v1", True),
        ("evolink", "https://api.evolink.ai/v1", True),
        ("openai", "https://api.openai.com/v1", False),
        ("openai", "", False),
        ("openai", "https://my-relay.example.com/v1", True),
        ("deepseek", "https://api.deepseek.com", False),
    ],
)
def test_relay_detection(vendor: str, base_url: str, relay: bool) -> None:
    assert price_reference.is_relay(vendor, base_url) is relay


def test_real_table_has_the_models_users_actually_run() -> None:
    """几条抽查:改表时误删了整家,这里会先喊出来。"""
    assert {e.billing_unit for e in lookup("deepseek", "deepseek-v4-pro")} == {
        "million_input_token",
        "million_output_token",
        "million_cache_read_token",
    }
    (wan,) = lookup("alibaba", "wan2.7-t2v")
    assert (wan.capability, wan.billing_unit, wan.currency, wan.unit_amount_micros) == ("video", "video_second", "CNY", 600_000)
    (tts,) = lookup("alibaba", "cosyvoice-v2")
    assert (tts.capability, tts.billing_unit, tts.unit_amount_micros) == ("tts", "character", 200)
