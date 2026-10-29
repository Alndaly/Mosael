"""官方中转网关(ADR 0088 第 2 步):目录、对话转发、预占 → 结算、换通道、各种失败都不多扣。

上游模型服务用 `httpx2.MockTransport` 打桩:断言的是真正发出去的请求(哪条通道、哪把 Key、对上游叫什么模型)。
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cloud.config import CloudConfig
from cloud.domain import catalog, credits
from cloud.domain.channel_keys import new_channel_key
from cloud.gateway import api as gateway_api
from cloud.gateway import chat
from cloud.models import CloudDeviceToken, CloudGatewayCall, CloudUpstreamChannel, CloudUser, now
from conftest import RecordingSender, api, signed_in

PRIMARY_KEY = "sk-primary-0123456789"
BACKUP_KEY = "sk-backup-9876543210"


class FakeUpstream:
    """按通道(用 Key 认)回放回包,并记下每一个出站请求。"""

    def __init__(self) -> None:
        self.replies: dict[str, list[httpx2.Response | Exception]] = {PRIMARY_KEY: [], BACKUP_KEY: []}
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        key = request.headers["authorization"].removeprefix("Bearer ")
        found = self.replies[key].pop(0)
        if isinstance(found, Exception):
            raise found
        return found

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


def sse(*events: dict, done: bool = True) -> httpx2.Response:
    lines = "".join(f"data: {json.dumps(one, ensure_ascii=False)}\n\n" for one in events)
    if done:
        lines += "data: [DONE]\n\n"
    return httpx2.Response(200, content=lines.encode(), headers={"content-type": "text/event-stream"})


def chunk(text: str) -> dict:
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


USAGE = {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 2000}}


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def gateway(tmp_path, upstream):
    from cloud.app import create_app

    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False,
                         channel_key=new_channel_key())
    app = create_app(config, code_sender=RecordingSender(), upstream_transport=httpx2.MockTransport(upstream.handler))
    with app.state.db.session() as db:
        catalog.upsert_model(db, model_id="deepseek-chat", label="DeepSeek V3", kind="chat", max_output_tokens=4000)
        catalog.set_price(db, model_id="deepseek-chat", input_per_1k=2, output_per_1k=4,
                          effective_from=now() - timedelta(days=1))
        catalog.add_channel(db, config, model_id="deepseek-chat", base_url="https://primary.example/v1/",
                            upstream_model="deepseek-v3", api_key=PRIMARY_KEY, priority=0)
        catalog.add_channel(db, config, model_id="deepseek-chat", base_url="https://backup.example/v1",
                            upstream_model="deepseek-v3-backup", api_key=BACKUP_KEY, priority=1)
        db.commit()
    return app


def desktop(app, credits_amount: int | None = 100_000) -> TestClient:
    """登录、换设备令牌、去掉 cookie:之后只拿令牌说话,和桌面端一样。可选地送一批积分。"""
    client = TestClient(app)
    signed_in(client)
    secret = client.post(api("/device-tokens"), json={"name": "Mac"}).json()["secret"]
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {secret}"
    if credits_amount:
        with app.state.db.session() as db:
            user = db.scalar(select(CloudUser))
            credits.gift(db, user, amount=credits_amount, days=30, note="test", at=now())
            db.commit()
    return client


def ask(client: TestClient, **extra):
    return client.post(api("/gateway/chat"), json={
        "model": "deepseek-chat", "messages": [{"role": "user", "content": "你好"}], **extra,
    })


def credits_left(app) -> int:
    with app.state.db.session() as db:
        return credits.balance(db, db.scalar(select(CloudUser)).id, at=now()).total


def only_call(app) -> CloudGatewayCall:
    with app.state.db.session() as db:
        return db.scalar(select(CloudGatewayCall))


def test_catalog_lists_priced_models_and_the_users_credits(gateway):
    with gateway.state.db.session() as db:
        catalog.upsert_model(db, model_id="no-channel", label="x", kind="chat", max_output_tokens=10)
        catalog.set_price(db, model_id="no-channel", input_per_1k=1, output_per_1k=1, effective_from=now())
        db.commit()
    client = desktop(gateway, credits_amount=500)
    body = client.get(api("/gateway/catalog")).json()
    #: 没有通道的模型不列。
    assert [one["id"] for one in body["models"]] == ["deepseek-chat"]
    assert body["models"][0]["price"] == {"input_per_1k": 2, "output_per_1k": 4}
    assert body["credits"]["total"] == 500
    assert body["credits"]["batches"][0]["source"] == "gift"


def test_the_gateway_only_accepts_device_tokens(gateway):
    client = TestClient(gateway)
    signed_in(client)
    assert client.get(api("/gateway/catalog")).status_code == 401


def test_a_streamed_chat_relays_the_upstream_and_charges_the_reported_usage(gateway, upstream):
    client = desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(sse(chunk("你"), chunk("好"), USAGE))

    response = ask(client, temperature=0.3)
    assert response.status_code == 200, response.text
    text = response.text
    assert '"content": "你"' in text and '"content": "好"' in text
    #: 结算事件在 [DONE] 之前,[DONE] 是最后一行。
    usage_event = text.split("event: mosael.usage\ndata: ")[1].split("\n")[0]
    settled = json.loads(usage_event)
    #: 1000 × 2 / 1000 + 2000 × 4 / 1000 = 10
    assert settled["charged"] == 10 and settled["usage_reported"] is True
    assert settled["credits_left"] == 100_000 - 10
    assert text.rstrip().endswith("data: [DONE]")
    assert response.headers["x-mosael-call-id"] == settled["call_id"]

    sent = upstream.body()
    assert str(upstream.requests[-1].url) == "https://primary.example/v1/chat/completions"
    assert upstream.requests[-1].headers["authorization"] == f"Bearer {PRIMARY_KEY}"
    assert sent["model"] == "deepseek-v3"
    assert sent["max_tokens"] == 4000
    assert sent["temperature"] == 0.3
    assert sent["stream_options"] == {"include_usage": True}
    assert credits_left(gateway) == 100_000 - 10
    call = only_call(gateway)
    assert (call.status, call.input_tokens, call.output_tokens) == ("settled", 1000, 2000)


def test_a_busy_channel_is_cooled_down_and_the_next_one_serves_the_call(gateway, upstream):
    client = desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(httpx2.Response(429, json={"error": {"message": "rate limited"}}))
    upstream.replies[BACKUP_KEY].append(sse(chunk("hi"), USAGE))

    response = ask(client)
    assert response.status_code == 200, response.text
    assert [str(one.url) for one in upstream.requests] == [
        "https://primary.example/v1/chat/completions", "https://backup.example/v1/chat/completions",
    ]
    assert upstream.body()["model"] == "deepseek-v3-backup"
    #: 只扣一次。
    assert credits_left(gateway) == 100_000 - 10
    with gateway.state.db.session() as db:
        primary = db.scalar(select(CloudUpstreamChannel).where(CloudUpstreamChannel.priority == 0))
        assert primary.cooldown_until is not None and primary.cooldown_until > now()
        call = db.scalar(select(CloudGatewayCall))
        assert call.channel_id != primary.id

    #: 冷却中的那条排到后面:下一次直接先试备用。
    upstream.replies[BACKUP_KEY].append(sse(chunk("again"), USAGE))
    assert ask(client).status_code == 200
    assert str(upstream.requests[-1].url) == "https://backup.example/v1/chat/completions"


def test_when_every_channel_fails_nothing_is_charged(gateway, upstream):
    client = desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(httpx2.ConnectError("down"))
    upstream.replies[BACKUP_KEY].append(httpx2.Response(503, text="<html>bad gateway</html>"))

    response = ask(client)
    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"
    assert credits_left(gateway) == 100_000
    assert only_call(gateway).status == "released"


def test_an_upstream_rejection_is_not_retried_and_never_echoes_the_key(gateway, upstream):
    client = desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(
        httpx2.Response(400, json={"error": {"message": f"bad request for key {PRIMARY_KEY}"}})
    )

    response = ask(client)
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "upstream_rejected"
    assert PRIMARY_KEY not in response.text
    assert "bad request for key ***" in body["message"]["en"]
    assert len(upstream.requests) == 1
    assert credits_left(gateway) == 100_000


def test_not_enough_credits_is_refused_before_anything_goes_upstream(gateway, upstream):
    client = desktop(gateway, credits_amount=5)
    response = ask(client)
    assert response.status_code == 402
    body = response.json()
    assert body["error"] == "insufficient_credits"
    #: 输入 2 个字按 2 个 token 预占,输出按上限 4000:ceil((2×2 + 4000×4)/1000) = 17。
    assert body["details"] == {"needed": 17, "available": 5, "next_grant_at": None}
    assert upstream.requests == []
    #: 没有半截的调用记录留下。
    assert only_call(gateway) is None


def test_asking_for_fewer_tokens_reserves_less(gateway, upstream):
    client = desktop(gateway, credits_amount=5)
    upstream.replies[PRIMARY_KEY].append(sse(chunk("ok"), {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3}}))
    response = ask(client, max_tokens=100)
    assert response.status_code == 200, response.text
    assert upstream.body()["max_tokens"] == 100


def test_max_tokens_above_the_model_ceiling_is_refused(gateway):
    client = desktop(gateway)
    response = ask(client, max_tokens=4001)
    assert response.status_code == 400
    assert response.json()["error"] == "gateway_max_tokens_too_large"


def test_an_unknown_model_is_404(gateway):
    client = desktop(gateway)
    response = client.post(api("/gateway/chat"), json={"model": "gpt-9", "messages": [{"role": "user", "content": "x"}]})
    assert response.status_code == 404
    assert response.json()["error"] == "gateway_model_unknown"


def test_without_a_channel_key_the_gateway_says_it_is_not_configured(tmp_path):
    from cloud.app import create_app

    app = create_app(CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False),
                     code_sender=RecordingSender())
    client = desktop(app)
    response = ask(client)
    assert response.status_code == 503
    assert response.json()["error"] == "gateway_not_configured"


def test_a_non_streamed_chat_carries_the_settlement_in_the_reply(gateway, upstream):
    client = desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(httpx2.Response(200, json={
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"}}],
        "usage": {"prompt_tokens": 500, "completion_tokens": 250},
    }))
    response = ask(client, stream=False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "你好"
    #: ceil((500×2 + 250×4)/1000) = 2
    assert body["mosael"]["charged"] == 2
    assert "stream_options" not in upstream.body()


def test_without_reported_usage_the_charge_is_estimated_from_the_text(gateway, upstream):
    client = desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(sse(chunk("x" * 3000), done=False))
    response = ask(client)
    settled = json.loads(response.text.split("event: mosael.usage\ndata: ")[1].split("\n")[0])
    assert settled["usage_reported"] is False
    #: 输入 2 字 → 1 token;输出 3000 字 → 1500 token:ceil((1×2 + 1500×4)/1000) = 7
    assert (settled["input_tokens"], settled["output_tokens"], settled["charged"]) == (1, 1500, 7)
    #: 上游没发 [DONE],网关也不替它补。
    assert "[DONE]" not in response.text


def test_a_stream_cut_off_midway_is_settled_for_what_was_generated(gateway, upstream):
    desktop(gateway)
    upstream.replies[PRIMARY_KEY].append(sse(chunk("y" * 1000), chunk("never read")))
    # 直接驱动转发生成器:读到第一段就关掉,和桌面端中途断开一样。
    with gateway.state.db.session() as db:
        user = db.scalar(select(CloudUser))
        token = db.scalar(select(CloudDeviceToken))
        begun = chat.begin(db, gateway.state.config, user_id=user.id, device_token_id=token.id, model_id="deepseek-chat",
                           max_tokens=None, input_chars=2, at=now())
        upstream_client = httpx2.Client(transport=httpx2.MockTransport(upstream.handler))
        _channel, response = chat.connect(db, gateway.state.config, upstream_client, begun,
                                          body={"messages": [], "max_tokens": 4000, "stream": True}, at=now())
        call_id = begun.call.id
    relay = gateway_api._relay(gateway.state.db, upstream_client, response, begun, call_id)
    assert "y" * 1000 in next(relay)
    relay.close()

    with gateway.state.db.session() as db:
        call = db.get(CloudGatewayCall, call_id)
        #: 读到的 1000 字 → 500 token:ceil((1×2 + 500×4)/1000) = 3;其余预占退回。
        assert (call.status, call.charged, call.usage_reported) == ("settled", 3, False)
    assert credits_left(gateway) == 100_000 - 3


def test_thinking_text_counts_toward_the_estimate_under_either_name():
    from cloud.gateway.upstream import generated_chars

    deepseek = {"choices": [{"delta": {"content": "", "reasoning_content": "abcd"}}]}
    ollama = {"choices": [{"delta": {"content": "x", "reasoning": "abc"}}]}
    assert generated_chars(deepseek) == 4
    assert generated_chars(ollama) == 4
