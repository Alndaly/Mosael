from __future__ import annotations

import httpx
import pytest

from app.ai.model_catalog import clear_cache, fetch_models
from tests.util import fresh_client

"""按供应商模型目录预填计价规则。

这条链路的价值在于**省掉手抄**:配一个 OpenRouter 或订阅计划,几十上百个模型的进出价不该让人
一条条填。但它也最容易好心办坏事,所以三条判据是关于「不做什么」的:

  1. 已有规则一律不动 —— 目录报价是厂商挂牌价,用户填过的才是他核对过的账(有折扣、企业协议、
     订阅额度)。自动覆盖等于悄悄改账,而且改完没人知道。
  2. 目录里的 0 不写成规则 —— 那是「未标价 / 订阅内含」,不是「免费」。写成 0 会让这一项在报表里
     变成**确定的**零成本,比留空更误导。
  3. 计价始终只有一处来源(ProviderPricingRule)。pi 自己也算 cost,那份不进账。
"""


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def client_fixture():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _profile(client, vendor: str, config: dict) -> str:
    resp = client.post("/api/settings/providers", json={"name": vendor, "vendor": vendor, "config": config})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _stub_models(monkeypatch, payload: object) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)


def test_per_token_pricing_is_converted_to_per_million(monkeypatch) -> None:
    """OpenRouter 一类端点给的是每 token 的美元价(还是字符串)。搞错量级会让费用差一百万倍。"""
    _stub_models(monkeypatch, {"data": [{"id": "m", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]})
    (model,) = fetch_models("http://x/v1", "k")
    assert model.input_cost == pytest.approx(3.0)
    assert model.output_cost == pytest.approx(15.0)
    assert model.cache_read_cost is None, "端点没给缓存价就该留空,不能补 0"


def test_prefill_creates_rules_from_the_catalog(monkeypatch, client_fixture) -> None:
    client = client_fixture
    _stub_models(
        monkeypatch,
        {"data": [{"id": "m", "pricing": {"prompt": "0.000003", "completion": "0.000015", "input_cache_read": "0.0000003"}}]},
    )
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "m"})

    resp = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "created": 3,
        "created_from_catalog": 3,
        "created_from_reference": 0,
        "models_with_price": 1,
        "models_seen": 1,
        "unpriced_models": [],
    }

    rules = {r["billing_unit"]: r for r in client.get("/api/settings/provider-pricing-rules").json()}
    assert rules["million_input_token"]["unit_amount_micros"] == 3_000_000
    assert rules["million_output_token"]["unit_amount_micros"] == 15_000_000
    assert rules["million_cache_read_token"]["unit_amount_micros"] == 300_000
    assert rules["million_input_token"]["source"] == "catalog", "要能看出这条不是手填的"


def test_prefill_never_touches_an_existing_rule(monkeypatch, client_fixture) -> None:
    """用户填的 1.5 是他核对过的账(折扣/企业价);目录说 3 也不许改。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "m", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]})
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "m"})

    mine = client.post(
        "/api/settings/provider-pricing-rules",
        json={
            "provider_profile_id": profile_id,
            "provider": "openai-compatible",
            "capability": "chat",
            "model": "m",
            "billing_unit": "million_input_token",
            "unit_amount_micros": 1_500_000,
        },
    )
    assert mine.status_code == 200, mine.text

    resp = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")
    assert resp.json()["created"] == 1, "只该补上缺的输出价,输入价必须原样保留"

    rules = {r["billing_unit"]: r for r in client.get("/api/settings/provider-pricing-rules").json()}
    assert rules["million_input_token"]["unit_amount_micros"] == 1_500_000
    assert rules["million_input_token"]["source"] == "manual"


def test_prefill_is_idempotent(monkeypatch, client_fixture) -> None:
    """按两次不该翻倍 —— 规则重复了,匹配时谁赢是不确定的。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "m", "pricing": {"prompt": "0.000003"}}]})
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "m"})

    assert client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()["created"] == 1
    assert client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()["created"] == 0
    assert len(client.get("/api/settings/provider-pricing-rules").json()) == 1


def test_zero_priced_models_produce_no_rule(monkeypatch, client_fixture) -> None:
    """0 在目录里是「未标价 / 订阅内含」。写成规则就等于宣称这一项确定不花钱。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "free", "pricing": {"prompt": "0", "completion": "0"}}]})
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "free"})

    resp = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")
    body = resp.json()
    assert (body["created"], body["models_with_price"], body["models_seen"]) == (0, 0, 1)
    assert body["unpriced_models"] == ["free"]
    assert client.get("/api/settings/provider-pricing-rules").json() == []


def test_an_endpoint_without_pricing_reports_why_nothing_happened(monkeypatch, client_fixture) -> None:
    """多数 OpenAI 兼容端点不报价。「一条没建」必须能区分是没报价还是早配好了。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "a"}, {"id": "b"}]})
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "a"})

    assert client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json() == {
        "created": 0,
        "created_from_catalog": 0,
        "created_from_reference": 0,
        "models_with_price": 0,
        "models_seen": 2,
        # 剩下要手填的是哪几个,点名说出来 —— 那才是用户接下来要做的事。
        "unpriced_models": ["a", "b"],
    }


def test_subscription_profile_prefills_from_its_stored_catalog(client_fixture) -> None:
    """订阅计划的目录来自登录时 pi 带回的那份(cost 用 cacheRead/cacheWrite 命名)。"""
    from app.core.db import SessionLocal
    from app.db.models import User
    from app.domain import provider_credentials

    client = client_fixture
    profile_id = _profile(client, "kimi-coding", {})
    with SessionLocal() as db:
        # 目录是**这次登录**的结果,跟着钥匙走(见 domain/provider_credentials)。
        me = db.query(User).order_by(User.created_at).first()
        credential = provider_credentials.upsert(db, profile_id, me.id, api_key="k")
        credential.model_catalog = [
            {"id": "k3", "name": "K3", "cost": {"input": 3, "output": 15, "cacheRead": 0.3, "cacheWrite": 0}},
            {"id": "k3-256k", "name": "K3 256k", "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}},
        ]
        db.commit()

    resp = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")
    body = resp.json()
    assert (body["created"], body["created_from_catalog"], body["models_with_price"], body["models_seen"]) == (3, 3, 1, 2)
    assert body["unpriced_models"] == ["k3-256k"]

    rules = {(r["model"], r["billing_unit"]): r["unit_amount_micros"] for r in client.get("/api/settings/provider-pricing-rules").json()}
    assert rules[("k3", "million_input_token")] == 3_000_000
    assert rules[("k3", "million_cache_read_token")] == 300_000
    assert ("k3", "million_cache_write_token") not in rules, "cacheWrite 为 0 = 未标价,不该建规则"
    assert not any(model == "k3-256k" for model, _ in rules), "整个模型都没标价时一条都不该建"


def test_prefilled_rules_actually_price_a_turn(monkeypatch, client_fixture) -> None:
    """端到端:预填完就能算出钱来 —— 否则这个按钮只是往表里塞行。"""
    from app.core.db import SessionLocal
    from app.domain.usage import record_usage

    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "m", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]})
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "m"})
    client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")

    ws = client.get("/api/workspaces").json()[0]["id"]
    with SessionLocal() as db:
        event = record_usage(
            db,
            workspace_id=ws,
            provider_profile_id=profile_id,
            provider="openai-compatible",
            capability="chat",
            model="m",
            units={"input_tokens": 1_000_000, "output_tokens": 200_000},
            operation="chat.turn",
            idempotency_key="prefill-e2e",
        )
    # 3.00(输入) + 3.00(输出 0.2M × $15) = 6.00
    assert event.cost_micros == 6_000_000, f"实际 ${(event.cost_micros or 0) / 1e6:.2f}"


# ---------- 官方价目表补缺(domain/price_reference)----------


def _add_models(profile_id: str, *models: tuple[str, list[str]]) -> None:
    """给连接挂几条模型行 —— 生图/生视频连接的模型只在这里,不在 /models 目录里。"""
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile
    from app.domain import provider_models

    with SessionLocal() as db:
        profile = db.get(ProviderProfile, profile_id)
        for model_id, capabilities in models:
            provider_models.upsert(db, profile, model_id, capability_ids=capabilities)
        db.commit()


def _rules(client) -> dict[tuple[str, str, str], dict]:
    return {(r["model"], r["capability"], r["billing_unit"]): r for r in client.get("/api/settings/provider-pricing-rules").json()}


def test_an_official_endpoint_without_catalog_prices_is_filled_from_the_price_list(monkeypatch, client_fixture) -> None:
    """用户撞到的正是这个:DeepSeek 官方端点的目录只列 id,于是「没有新建规则」。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-chat"}]})
    profile_id = _profile(client, "deepseek", {"api_key": "k"})

    body = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()
    assert (body["created"], body["created_from_catalog"], body["created_from_reference"]) == (3, 0, 3)
    assert body["models_with_price"] == 1
    assert body["unpriced_models"] == ["deepseek-chat"], "价目页不再列的旧名要点出来让人手填,而不是瞎补"

    rules = _rules(client)
    input_rule = rules[("deepseek-v4-pro", "chat", "million_input_token")]
    assert (input_rule["unit_amount_micros"], input_rule["currency"], input_rule["source"]) == (9_000_000, "CNY", "reference")
    assert "api-docs.deepseek.com" in input_rule["notes"] and "2026-09" in input_rule["notes"], "备注要能让人回去核对"
    assert "高峰" in input_rule["notes"], "分时段计价要在备注里说清记的是哪一档"
    assert rules[("deepseek-v4-pro", "chat", "million_cache_read_token")]["unit_amount_micros"] == 300_000


def test_catalog_price_beats_the_price_list_for_the_whole_model(monkeypatch, client_fixture) -> None:
    """端点自己报的价优先;而且不拿价目表去给它补缓存价 —— 两边的数拼在一张账上谁也解释不了。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "deepseek-v4-pro", "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]})
    profile_id = _profile(client, "deepseek", {"api_key": "k"})

    body = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()
    assert (body["created_from_catalog"], body["created_from_reference"]) == (2, 0)
    rules = _rules(client)
    assert rules[("deepseek-v4-pro", "chat", "million_input_token")]["source"] == "catalog"
    assert rules[("deepseek-v4-pro", "chat", "million_input_token")]["currency"] == "USD"
    assert ("deepseek-v4-pro", "chat", "million_cache_read_token") not in rules


def test_price_list_never_touches_or_mixes_with_existing_rules(monkeypatch, client_fixture) -> None:
    """用户手填了一条美元的输入价:不改它,也不补人民币的输出价 —— 混币种的那条入账时会被跳过。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "deepseek-v4-pro"}]})
    profile_id = _profile(client, "deepseek", {"api_key": "k"})
    mine = client.post(
        "/api/settings/provider-pricing-rules",
        json={
            "provider_profile_id": profile_id,
            "capability": "chat",
            "model": "deepseek-v4-pro",
            "billing_unit": "million_input_token",
            "unit_amount_micros": 1_000_000,
            "currency": "USD",
        },
    )
    assert mine.status_code == 200, mine.text

    body = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()
    assert body["created"] == 0
    assert body["unpriced_models"] == []
    rules = _rules(client)
    assert list(rules) == [("deepseek-v4-pro", "chat", "million_input_token")]
    assert rules[("deepseek-v4-pro", "chat", "million_input_token")]["unit_amount_micros"] == 1_000_000


def test_generation_and_speech_models_get_their_own_units(monkeypatch, client_fixture) -> None:
    """生图按张、生视频按秒、语音按字符 —— 这几种从来没被预填过,目录也不可能给。"""
    from app.core.db import SessionLocal
    from app.domain.usage import record_usage

    client = client_fixture
    _stub_models(monkeypatch, {"data": []})
    profile_id = _profile(client, "alibaba", {"api_key": "k"})
    _add_models(
        profile_id,
        ("wan2.7-t2v", ["video"]),
        ("qwen-image", ["image"]),
        ("cosyvoice-v2", ["tts"]),
        ("my-finetune", ["chat"]),
    )

    body = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()
    assert (body["created"], body["created_from_reference"], body["models_seen"]) == (3, 3, 4)
    assert body["unpriced_models"] == ["my-finetune"]

    rules = _rules(client)
    video = rules[("wan2.7-t2v", "video", "video_second")]
    assert (video["unit_amount_micros"], video["currency"]) == (600_000, "CNY")
    assert "720P" in video["notes"], "按分辨率分档的价要说清记的是哪一档"
    assert rules[("qwen-image", "image", "image")]["unit_amount_micros"] == 250_000
    assert rules[("cosyvoice-v2", "tts", "character")]["unit_amount_micros"] == 200, "2 元/万字符 = 每字符 200 micros"

    ws = client.get("/api/workspaces").json()[0]["id"]
    with SessionLocal() as db:
        event = record_usage(
            db,
            workspace_id=ws,
            provider_profile_id=profile_id,
            provider="alibaba",
            capability="video",
            model="wan2.7-t2v",
            units={"requests": 1, "videos": 1, "video_seconds": 5.0, "input_tokens": 30},
            operation="generation_job",
            idempotency_key="reference-video",
        )
    assert (event.cost_micros, event.currency) == (3_000_000, "CNY"), "5 秒 × 0.6 元"


def test_capability_the_model_row_does_not_offer_is_skipped(monkeypatch, client_fixture) -> None:
    """模型行说它只做对话,就别给它建一条视频规则 —— 那条永远匹配不上,只是往表里塞行。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": []})
    profile_id = _profile(client, "alibaba", {"api_key": "k"})
    _add_models(profile_id, ("wan2.7-t2v", ["chat"]))

    body = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()
    assert body["created"] == 0
    assert body["unpriced_models"] == ["wan2.7-t2v"]


def test_international_endpoint_gets_international_prices(monkeypatch, client_fixture) -> None:
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "qwen-max"}]})
    profile_id = _profile(
        client, "alibaba", {"api_key": "k", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"}
    )
    client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")
    rule = _rules(client)[("qwen-max", "chat", "million_input_token")]
    assert (rule["currency"], rule["unit_amount_micros"]) == ("USD", 1_600_000)


def test_relay_borrows_the_original_vendor_price_and_says_so(monkeypatch, client_fixture) -> None:
    """147ai 一类中转:目录不报价时,只按唯一属于某家的 id 借原厂价,并在备注里说明中转可能另价。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "claude-sonnet-4-6"}, {"id": "claude-sonnet-4-6-thinking"}]})
    profile_id = _profile(
        client, "openai-compatible", {"api_key": "k", "base_url": "https://relay.example/v1", "default_model": "claude-sonnet-4-6"}
    )

    body = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json()
    assert body["created_from_reference"] == 4
    assert body["unpriced_models"] == ["claude-sonnet-4-6-thinking"], "中转自己起的变体名不按前缀猜"
    rule = _rules(client)[("claude-sonnet-4-6", "chat", "million_output_token")]
    assert (rule["unit_amount_micros"], rule["currency"]) == (15_000_000, "USD")
    assert "中转" in rule["notes"] and "platform.claude.com" in rule["notes"]


def test_prefilled_rules_show_up_in_the_workspace_list(monkeypatch, client_fixture) -> None:
    """预填的规则不属于任何工作区(对所有工作区生效)—— 此前列表只取本工作区的,新建了也看不见。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "deepseek-v4-pro"}]})
    profile_id = _profile(client, "deepseek", {"api_key": "k"})
    client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")

    ws = client.get("/api/workspaces").json()[0]["id"]
    listed = client.get(f"/api/settings/provider-pricing-rules?workspace_id={ws}").json()
    assert {r["billing_unit"] for r in listed} == {"million_input_token", "million_output_token", "million_cache_read_token"}
