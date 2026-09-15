"""Small remote-deployment rate-limit boundary.

Mosael has one backend process by design, so an in-process rolling window is the same consistency
boundary as sessions, schedulers and job admission.  The module owns policy classification and
storage; routes stay unaware and local desktop traffic is exempt.
"""
from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class RateLimitSettings(Protocol):
    local_desktop: bool
    backend_host: str
    rate_limit_enabled: bool | None
    rate_limit_auth_per_minute: int
    rate_limit_oauth_per_minute: int
    rate_limit_billable_per_minute: int
    rate_limit_trusted_proxies: str


@dataclass(frozen=True)
class LimitRule:
    name: str
    limit: int
    window_seconds: float = 60.0
    identity: str = "client"


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int = 0


class WindowLimiter:
    """Thread-safe rolling timestamp windows with bounded stale-key cleanup."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._hits = 0

    def check(self, rule: LimitRule, identity: str) -> LimitDecision:
        now = self._clock()
        cutoff = now - rule.window_seconds
        key = (rule.name, identity)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= rule.limit:
                retry = max(1, int(events[0] + rule.window_seconds - now + 0.999))
                return LimitDecision(False, rule.limit, 0, retry)
            events.append(now)
            remaining = max(0, rule.limit - len(events))
            self._hits += 1
            if self._hits % 512 == 0:
                self._discard_stale(cutoff)
            return LimitDecision(True, rule.limit, remaining)

    def _discard_stale(self, cutoff: float) -> None:
        for key, events in list(self._events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                self._events.pop(key, None)


def enabled_for(settings: RateLimitSettings) -> bool:
    if settings.rate_limit_enabled is not None:
        return settings.rate_limit_enabled
    if settings.local_desktop:
        return False
    host = settings.backend_host.strip().strip("[]").lower()
    if host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A configured hostname is reachable beyond loopback unless the operator explicitly opts out.
        return True


def classify(method: str, path: str, settings: RateLimitSettings) -> LimitRule | None:
    method = method.upper()
    if path.startswith("/api/auth/oauth/") and method in {"GET", "POST"}:
        return LimitRule("oauth", max(1, settings.rate_limit_oauth_per_minute))
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if path in {"/api/auth/login", "/api/auth/register", "/api/auth/me/password"}:
        return LimitRule("auth", max(1, settings.rate_limit_auth_per_minute))
    tail = path.rsplit("/", 1)[-1]
    billable = (
        path == "/api/generation/jobs"
        or path == "/api/generation/optimize-prompt"
        or path == "/api/confirmations"
        or (path.startswith("/api/confirmations/") and path.endswith("/approve"))
        or path.startswith("/api/agent/tools/")
        or (path.startswith("/api/agent/sessions/") and tail in {"compact", "messages"})
        or path in {"/api/agent/speech", "/api/asr/dictate"}
        or (path.startswith("/api/boards/") and tail in {"generate", "write", "speak"})
        or (
            path.startswith("/api/workflows/")
            and tail in {"run", "ai-edit", "agent-session", "agent-sessions"}
        )
        or (path.startswith("/api/assets/") and tail in {"analyze", "transcribe"})
        or (path.startswith("/api/scheduled-tasks/") and tail == "run")
        or (path.startswith("/api/plugins/instances/") and tail == "invoke")
        or path == "/api/translate"
        or path.startswith("/api/tts/")
        or path == "/api/voices/from-speaker"
        or (
            path.startswith("/api/voices/")
            and tail in {"recognize-reference", "synthesize"}
        )
        or (
            path.startswith("/api/sequences/")
            and (tail in {"export", "dub-subtitles"} or path.endswith("/subtitles/generate"))
        )
        or (
            path.startswith("/api/settings/providers/")
            and (tail in {"quota", "prefill"} or path.endswith("/oauth/login"))
        )
    )
    if billable:
        return LimitRule(
            "billable", max(1, settings.rate_limit_billable_per_minute), identity="session"
        )
    return None


def _client_identity(request: Request, settings: RateLimitSettings) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted = {one.strip() for one in settings.rate_limit_trusted_proxies.split(",") if one.strip()}
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return peer


def _session_identity(request: Request, client: str) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if not authorization:
        return client
    digest = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
    return f"session:{digest}"


def install_rate_limiting(app: FastAPI, settings: RateLimitSettings) -> WindowLimiter:
    limiter = WindowLimiter()

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not enabled_for(settings):
            return await call_next(request)
        rule = classify(request.method, request.url.path, settings)
        if rule is None:
            return await call_next(request)
        client = _client_identity(request, settings)
        identity = _session_identity(request, client) if rule.identity == "session" else client
        # A session bucket keeps users behind one NAT independent.  A wider IP safety bucket also
        # prevents an attacker from rotating arbitrary invalid Bearer strings to create new keys.
        if rule.identity == "session":
            client_rule = LimitRule(f"{rule.name}:client", rule.limit * 4, rule.window_seconds)
            client_decision = limiter.check(client_rule, client)
            if not client_decision.allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试"},
                    headers={
                        "Retry-After": str(client_decision.retry_after),
                        "X-RateLimit-Limit": str(client_decision.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
        decision = limiter.check(rule, identity)
        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
        }
        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after)
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers=headers,
            )
        response = await call_next(request)
        response.headers.update(headers)
        return response

    return limiter


__all__ = [
    "LimitDecision",
    "LimitRule",
    "WindowLimiter",
    "classify",
    "enabled_for",
    "install_rate_limiting",
]
