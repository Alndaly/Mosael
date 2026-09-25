from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import LimitRule, WindowLimiter, classify, enabled_for, install_rate_limiting


def _settings(**overrides):
    values = {
        "local_desktop": False,
        "backend_host": "0.0.0.0",
        "rate_limit_enabled": None,
        "rate_limit_auth_per_minute": 2,
        "rate_limit_oauth_per_minute": 3,
        "rate_limit_billable_per_minute": 4,
        "rate_limit_trusted_proxies": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_auto_mode_exempts_desktop_and_loopback_but_protects_remote_hosts():
    assert enabled_for(_settings(local_desktop=True)) is False
    assert enabled_for(_settings(backend_host="127.0.0.1")) is False
    assert enabled_for(_settings(backend_host="::1")) is False
    assert enabled_for(_settings(backend_host="0.0.0.0")) is True
    assert enabled_for(_settings(backend_host="mosael.internal")) is True
    assert enabled_for(_settings(backend_host="127.0.0.1", rate_limit_enabled=True)) is True


def test_policy_limits_auth_oauth_and_billable_mutations_only():
    settings = _settings()
    assert classify("POST", "/api/auth/login", settings).name == "auth"
    assert classify("POST", "/api/auth/oauth/google/start", settings).name == "oauth"
    assert classify("GET", "/api/auth/oauth/google/callback", settings).name == "oauth"
    assert classify("POST", "/api/generation/jobs", settings).identity == "session"
    assert classify("POST", "/api/agent/sessions/s1/messages", settings).name == "billable"
    assert classify("POST", "/api/boards/b1/run", settings).name == "billable"
    assert classify("POST", "/api/workflows/w1/run", settings).name == "billable"
    assert classify("POST", "/api/workflows/w1/agent-session", settings).name == "billable"
    assert classify("POST", "/api/assets/a1/transcribe", settings).name == "billable"
    assert classify("POST", "/api/scheduled-tasks/t1/run", settings).name == "billable"
    assert classify("POST", "/api/plugins/instances/p1/tools/tool/invoke", settings).name == "billable"
    assert classify("POST", "/api/sequences/s1/subtitles/generate", settings).name == "billable"
    assert classify("POST", "/api/tts/synthesize", settings).name == "billable"
    assert classify("POST", "/api/tts/podcast", settings).name == "billable"
    assert classify("POST", "/api/settings/providers/p1/quota", settings).name == "billable"
    assert classify("GET", "/api/generation/jobs", settings) is None
    assert classify("PATCH", "/api/notes/n1", settings) is None


def test_window_reopens_and_reports_retry_after():
    now = [100.0]
    limiter = WindowLimiter(lambda: now[0])
    rule = LimitRule("auth", 2, window_seconds=10)
    assert limiter.check(rule, "one").allowed
    assert limiter.check(rule, "one").allowed
    blocked = limiter.check(rule, "one")
    assert blocked.allowed is False
    assert blocked.retry_after == 10
    assert limiter.check(rule, "another").allowed
    now[0] = 110.0
    assert limiter.check(rule, "one").allowed


def test_middleware_returns_429_and_does_not_limit_local_mode():
    remote = FastAPI()
    install_rate_limiting(remote, _settings())

    @remote.post("/api/auth/login")
    def login():
        return {"ok": True}

    client = TestClient(remote)
    assert client.post("/api/auth/login").status_code == 200
    assert client.post("/api/auth/login").status_code == 200
    response = client.post("/api/auth/login")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"

    local = FastAPI()
    install_rate_limiting(local, _settings(local_desktop=True))

    @local.post("/api/auth/login")
    def local_login():
        return {"ok": True}

    local_client = TestClient(local)
    assert all(local_client.post("/api/auth/login").status_code == 200 for _ in range(4))


def test_forwarded_client_identity_is_used_only_for_trusted_proxies():
    def make_app(settings):
        app = FastAPI()
        install_rate_limiting(app, settings)

        @app.post("/api/auth/login")
        def login():
            return {"ok": True}

        return TestClient(app)

    untrusted = make_app(_settings(rate_limit_auth_per_minute=1))
    assert untrusted.post("/api/auth/login", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert untrusted.post("/api/auth/login", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 429

    trusted = make_app(
        _settings(rate_limit_auth_per_minute=1, rate_limit_trusted_proxies="testclient")
    )
    assert trusted.post("/api/auth/login", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert trusted.post("/api/auth/login", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
