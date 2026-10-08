"""读网页(webfetch)和 HTTP 节点 / 智能体 HTTP 工具收到上限就停,不把整份读进内存(SEC-4)。

此前两处交给下游的文本都截了(6000 字 / 100000 字),可截在**整份读进内存之后**:任何登录用户经 `GET /api/webfetch?url=`、
任何能跑工作流的人经 HTTP 节点,都能让后端去读一个几个 GB 的地址。现在边收边数,超了就停,说清是太大了。
"""

from __future__ import annotations

import httpx
import pytest

from app.core import outbound_guard
from app.domain import websearch
from app.domain.workflows.executors import basic

CHUNK = 16 * 1024


class _Endless(httpx.SyncByteStream):
    """一份大得没边的正文:数着发出去了几块,超了上限还在发就说明没停。"""

    def __init__(self, served: list[int], total: int) -> None:
        self.served = served
        self.total = total

    def __iter__(self):
        for _ in range(self.total):
            self.served.append(1)
            yield b"<p>" + b"x" * (CHUNK - 3)


@pytest.fixture
def huge(monkeypatch) -> list[int]:
    served: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=_Endless(served, total=640))  # 10 MiB

    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(outbound_guard, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler)))
    return served


def test_读网页_收到上限就停_说清太大了(monkeypatch, huge: list[int]) -> None:
    monkeypatch.setattr(websearch, "FETCH_MAX_BYTES", 256 * 1024)

    with pytest.raises(websearch.WebSearchError) as refused:
        websearch.fetch("https://example.com/huge")

    assert refused.value.key == "outboundErr_tooLarge"
    assert len(huge) < 40, f"超了上限还在收:收了 {len(huge)} 块"


def test_HTTP节点_收到上限就停_节点失败说清太大了(monkeypatch, huge: list[int]) -> None:
    from app.domain.workflows.errors import WorkflowDomainError

    monkeypatch.setattr(basic, "HTTP_MAX_BYTES", 256 * 1024)

    with pytest.raises(WorkflowDomainError) as failed:
        basic.http_request(None, None, {"method": "GET", "url": "https://example.com/huge"})

    assert "MB" in str(failed.value)
    assert len(huge) < 40


def test_上限本身够读正常的网页和接口() -> None:
    assert websearch.FETCH_MAX_BYTES >= 4 * 1024 * 1024
    assert basic.HTTP_MAX_BYTES >= 8 * 1024 * 1024
