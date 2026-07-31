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
    assert resp.json() == {"created": 3, "models_with_price": 1, "models_seen": 1}

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
    assert resp.json() == {"created": 0, "models_with_price": 0, "models_seen": 1}
    assert client.get("/api/settings/provider-pricing-rules").json() == []


def test_an_endpoint_without_pricing_reports_why_nothing_happened(monkeypatch, client_fixture) -> None:
    """多数 OpenAI 兼容端点不报价。「一条没建」必须能区分是没报价还是早配好了。"""
    client = client_fixture
    _stub_models(monkeypatch, {"data": [{"id": "a"}, {"id": "b"}]})
    profile_id = _profile(client, "openai-compatible", {"api_key": "k", "base_url": "http://x/v1", "default_model": "a"})

    assert client.post(f"/api/settings/providers/{profile_id}/pricing/prefill").json() == {
        "created": 0,
        "models_with_price": 0,
        "models_seen": 2,
    }


def test_subscription_profile_prefills_from_its_stored_catalog(client_fixture) -> None:
    """订阅计划的目录来自登录时 pi 带回的那份(cost 用 cacheRead/cacheWrite 命名)。"""
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = client_fixture
    profile_id = _profile(client, "kimi-coding", {})
    with SessionLocal() as db:
        profile = db.get(ProviderProfile, profile_id)
        profile.model_catalog = [
            {"id": "k3", "name": "K3", "cost": {"input": 3, "output": 15, "cacheRead": 0.3, "cacheWrite": 0}},
            {"id": "k3-256k", "name": "K3 256k", "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}},
        ]
        db.commit()

    resp = client.post(f"/api/settings/providers/{profile_id}/pricing/prefill")
    assert resp.json() == {"created": 3, "models_with_price": 1, "models_seen": 2}

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
