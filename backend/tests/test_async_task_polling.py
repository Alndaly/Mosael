"""异步任务的轮询:六家共用的那一段。

此前**六个适配器各写了一遍**这个循环,各自定义间隔、各自抛超时。代价不是行数 —— 是每家都
可能漏掉一件事,而没有任何机制能发现谁漏了。收成一份之后,这里补的每一条对六家同时生效。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import time

import pytest

from app.ai.providers.contracts.generation import ProviderError, poll_until_ready


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """按剧本逐次返回回包,并记下被问了几次、问的是哪个地址。"""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.paths: list[str] = []

    def get(self, path: str) -> _FakeResponse:
        self.paths.append(path)
        return _FakeResponse(self.script.pop(0) if self.script else {})


def _extract(payload: dict) -> str | None:
    status = payload.get("status")
    if status == "done":
        return str(payload["url"])
    if status == "failed":
        raise ProviderError(f"failed: {payload.get('reason')}")
    return None


def test_轮到终态就返回_地址和整个回包都给出来() -> None:
    """回包也要返回:调用方拿它去记账(用量在里面),只给地址的话那份数据就丢了。"""
    client = _FakeClient([{"status": "running"}, {"status": "done", "url": "https://x/a.mp4", "usage": {"n": 1}}])
    url, payload = poll_until_ready(client, "/tasks/1", _extract, interval=0)

    assert url == "https://x/a.mp4"
    assert payload["usage"] == {"n": 1}
    assert client.paths == ["/tasks/1", "/tasks/1"]


def test_失败由extract自己抛_因为只有它知道原因在哪个字段() -> None:
    client = _FakeClient([{"status": "failed", "reason": "内容审核未通过"}])
    with pytest.raises(ProviderError) as err:
        poll_until_ready(client, "/tasks/1", _extract, interval=0)
    assert "内容审核未通过" in str(err.value)


def test_超时要抛_而不是静静返回空() -> None:
    """一直回"还在跑"的任务:到点必须抛。静静返回的话,调用方会拿一个空地址去下载。"""
    client = _FakeClient([{"status": "running"}] * 50)
    with pytest.raises(ProviderError, match="timed out"):
        poll_until_ready(client, "/tasks/1", _extract, interval=0, timeout=0.05)


def test_用单调时钟计时_墙钟跳了也不受影响(monkeypatch) -> None:
    """六家原本都用 `time.time()`。墙钟会跳(NTP 校时、夏令时),跳一下要么把还在跑的任务判成
    超时,要么让它白等一个小时。这条把时钟来源钉死。"""
    calls: list[str] = []
    real_monotonic = time.monotonic

    monkeypatch.setattr(time, "time", lambda: calls.append("wall") or 0.0)
    monkeypatch.setattr(time, "monotonic", lambda: calls.append("mono") or real_monotonic())

    client = _FakeClient([{"status": "done", "url": "https://x/a.mp4"}])
    poll_until_ready(client, "/tasks/1", _extract, interval=0)

    assert "mono" in calls, "没用单调时钟"
    assert "wall" not in calls, "还在读墙钟 —— 时钟一跳就会误判"
