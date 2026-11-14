"""支付入口的进程内限流。

支付通道是外部副作用：每次下单都会向支付宝/微信申请二维码，每次回调都要验 RSA/AES。
没有闸时，一个登录用户就可以把渠道配额和本进程 CPU 打满。按进程计；Cloud 是单实例部署，
若以后多 worker，应换成数据库/Redis 的共享桶。
"""

from __future__ import annotations

import threading
import time
from collections import deque

from cloud.errors import CloudError

WINDOW_SECONDS = 60.0
ORDER_PER_USER = 10
ORDER_PER_IP = 30
NOTIFY_PER_IP = 120
NOTIFY_GLOBAL = 600
MAX_KEYS = 10_000

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = {}


def _hit(key: str, limit: int, now: float) -> None:
    bucket = _buckets.setdefault(key, deque())
    cutoff = now - WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise CloudError(429, "too_many_requests")
    bucket.append(now)
    if len(_buckets) > MAX_KEYS:
        _prune(now)


def _prune(now: float) -> None:
    cutoff = now - WINDOW_SECONDS
    for key, bucket in list(_buckets.items()):
        if not bucket or bucket[-1] <= cutoff:
            _buckets.pop(key, None)


def order(user_id: str, ip: str) -> None:
    now = time.monotonic()
    with _lock:
        _hit(f"order:user:{user_id}", ORDER_PER_USER, now)
        _hit(f"order:ip:{ip}", ORDER_PER_IP, now)


def notify(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        _hit(f"notify:ip:{ip}", NOTIFY_PER_IP, now)
        _hit("notify:global", NOTIFY_GLOBAL, now)


def reset() -> None:
    with _lock:
        _buckets.clear()
