"""连接背后的服务通不通(「在 ComfyUI 工作台里打开」能不能点的依据):有人应答就是通(哪怕 401),连不上 / 超时才不通。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.domain.plugins import reachability


def _manifest():
    field = SimpleNamespace(key="server_url", required=True, type="string")
    return SimpleNamespace(config=[field], name_template="ComfyUI · {server_url}")


def _probe(monkeypatch, handler, address="http://127.0.0.1:8188"):
    monkeypatch.setattr(reachability, "manifest_for", lambda _db, _instance: _manifest())
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        reachability, "RetryingClient", lambda **kwargs: httpx.Client(transport=transport, timeout=kwargs.get("timeout"))
    )
    return reachability.probe(None, SimpleNamespace(config={"server_url": address}))


def test_any_answer_counts_as_reachable(monkeypatch):
    for status in (200, 401, 404):
        found = _probe(monkeypatch, lambda request, status=status: httpx.Response(status))
        assert found == reachability.Reachability(reachable=True, address="http://127.0.0.1:8188")


def test_refused_or_timed_out_is_unreachable(monkeypatch):
    def refused(request):
        raise httpx.ConnectError("[Errno 61] Connection refused")

    def slow(request):
        raise httpx.ReadTimeout("timeout")

    assert _probe(monkeypatch, refused).reachable is False
    assert _probe(monkeypatch, slow) == reachability.Reachability(reachable=False, address="http://127.0.0.1:8188")


def test_without_an_http_address_there_is_nothing_to_probe(monkeypatch):
    def never(request):
        raise AssertionError("should not be called")

    assert _probe(monkeypatch, never, address="") == reachability.Reachability(reachable=False, address="")
