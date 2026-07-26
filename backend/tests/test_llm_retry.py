"""工作流 LLM 节点对供应商瞬断/限流/过载自动重试,4xx 立即失败;最大重试次数可在设置页配置。

背景:供应商偶发「Server disconnected without sending a response」等网络瞬断,旧实现一次就把
整条工作流判失败(真丢过一条,28 秒后同参数重试即成功)。这里锁定重试语义 + 可配置次数。
"""

from __future__ import annotations

import httpx
import pytest

from app.core.db import SessionLocal
from app.db.models import AiRuntimeConfig
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import ai
from tests.util import fresh_client


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://provider.test/chat/completions")


def _ok() -> httpx.Response:
    return httpx.Response(200, request=_req(), json={"choices": [{"message": {"content": "ok"}}]})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ai.time, "sleep", lambda *a, **k: None)  # 别在测试里真退避


def test_transient_disconnect_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=_req())
        return _ok()

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    resp = ai._post_with_retry("https://provider.test", "key", {"model": "m"}, "m", max_retries=3)
    assert calls["n"] == 3  # 前 2 次瞬断,第 3 次成功(在 3 重试=4 次尝试的额度内)
    assert resp.json()["choices"][0]["message"]["content"] == "ok"


def test_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=_req())

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    with pytest.raises(WorkflowDomainError) as ei:
        ai._post_with_retry("https://provider.test", "key", {"model": "m"}, "m", max_retries=3)
    assert calls["n"] == 4  # 首次 + 3 次重试
    assert "网络/连接" in str(ei.value) and "重试 3 次" in str(ei.value)


def test_zero_retries_fails_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=_req())

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    with pytest.raises(WorkflowDomainError) as ei:
        ai._post_with_retry("https://provider.test", "key", {"model": "m"}, "m", max_retries=0)
    assert calls["n"] == 1  # 关掉重试就只尝试一次
    assert "重试" not in str(ei.value)  # 不显示「已重试 N 次」


def test_4xx_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return httpx.Response(400, request=_req(), json={"error": {"message": "bad request"}})

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    with pytest.raises(WorkflowDomainError) as ei:
        ai._post_with_retry("https://provider.test", "key", {"model": "m"}, "m", max_retries=3)
    assert calls["n"] == 1  # 4xx 是请求本身的问题,立即失败不重试
    assert "400" in str(ei.value)


def test_5xx_retried_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, request=_req(), json={"error": {"message": "overloaded"}})
        return _ok()

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    resp = ai._post_with_retry("https://provider.test", "key", {"model": "m"}, "m", max_retries=3)
    assert calls["n"] == 2
    assert resp.status_code == 200


def test_configured_max_retries_reads_setting_and_clamps():
    fresh_client()  # 建库建表
    with SessionLocal() as db:
        assert ai.configured_max_retries(db) == 3  # 无行 → 缺省 3
        db.add(AiRuntimeConfig(id="default", max_retries=5))
        db.commit()
        assert ai.configured_max_retries(db) == 5
    with SessionLocal() as db:
        row = db.get(AiRuntimeConfig, "default")
        row.max_retries = 99  # 超范围
        db.commit()
        assert ai.configured_max_retries(db) == ai.MAX_RETRIES_CAP  # 夹到上限 10


def test_settings_endpoint_roundtrip():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 拥有工作区 → 满足 ensure_instance_admin
    assert client.get("/api/settings/ai-runtime").json()["max_retries"] == 3
    assert client.put("/api/settings/ai-runtime", json={"max_retries": 6}).json()["max_retries"] == 6
    assert client.get("/api/settings/ai-runtime").json()["max_retries"] == 6
    assert client.put("/api/settings/ai-runtime", json={"max_retries": 20}).status_code == 422  # 超范围拒绝
