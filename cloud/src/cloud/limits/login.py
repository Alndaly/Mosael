"""登录失败的进程内速率限制。

Cloud 是单实例部署（worker 也在同一进程），这里不需要引入 Redis；窗口按进程计，重启清空。
键分账号与 IP 两侧：只按 IP 会让同一 NAT 下的人互相锁死，只按账号则换 IP 就绕过。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from cloud.errors import CloudError

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 8
MAX_KEYS = 20_000


@dataclass
class _Bucket:
    failures: int = 0
    first_failure: float = 0.0
    locked_until: float = 0.0


_lock = threading.Lock()
_buckets: dict[str, _Bucket] = {}


def _now() -> float:
    return time.monotonic()


def _bucket(key: str) -> _Bucket:
    bucket = _buckets.get(key)
    if bucket is None:
        if len(_buckets) >= MAX_KEYS:
            # 进程被大量随机邮箱刷时，先丢掉已经过窗口的桶；仍然满就丢最早的。
            cutoff = _now() - WINDOW_SECONDS
            for name, old in list(_buckets.items()):
                if old.locked_until <= _now() and old.first_failure <= cutoff:
                    _buckets.pop(name, None)
            if len(_buckets) >= MAX_KEYS:
                _buckets.pop(next(iter(_buckets)), None)
        bucket = _Bucket()
        _buckets[key] = bucket
    return bucket


def check(email: str, ip: str) -> None:
    """在验密码之前问一句：这个账号/IP 是否还在冷却。"""
    keys = [f"email:{email.lower()}", f"ip:{ip}"]
    with _lock:
        for key in keys:
            bucket = _bucket(key)
            if bucket.locked_until > _now():
                raise CloudError(429, "too_many_requests")


def failed(email: str, ip: str) -> None:
    now = _now()
    with _lock:
        for key in (f"email:{email.lower()}", f"ip:{ip}"):
            bucket = _bucket(key)
            if bucket.first_failure == 0 or now - bucket.first_failure >= WINDOW_SECONDS:
                bucket.failures = 1
                bucket.first_failure = now
            else:
                bucket.failures += 1
            if bucket.failures >= MAX_FAILURES:
                bucket.locked_until = now + WINDOW_SECONDS


def succeeded(email: str, ip: str) -> None:
    with _lock:
        _buckets.pop(f"email:{email.lower()}", None)
        _buckets.pop(f"ip:{ip}", None)


def reset() -> None:
    """测试用。"""
    with _lock:
        _buckets.clear()
