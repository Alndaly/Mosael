from __future__ import annotations

from pathlib import Path

from app.ai.providers.media_transfer import download_to_path, trusted_headers_for_url


def test_下载凭据只发给明确受信的同源地址() -> None:
    headers = {"Authorization": "Bearer secret", "x-goog-api-key": "google-secret"}
    assert trusted_headers_for_url(
        "https://api.example/v1/files/1", "https://api.example/v1", headers
    ) == headers
    assert trusted_headers_for_url(
        "https://objects.example/files/1", "https://api.example/v1", headers
    ) == {}
    assert trusted_headers_for_url(
        "http://api.example/files/1", "https://api.example/v1", headers
    ) == {}, "scheme 变化也不是同源"


def test_下载跳转到外域后会丢弃凭据(tmp_path: Path, monkeypatch) -> None:
    clients: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, *, status: int, location: str = "", body: bytes = b"") -> None:
            self.status_code = status
            self.headers = {"location": location} if location else {"content-type": "video/mp4"}
            self._body = body

        @property
        def is_redirect(self) -> bool:
            return 300 <= self.status_code < 400

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            clients.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def stream(self, _method: str, url: str):
            if url.startswith("https://api.example"):
                return FakeResponse(status=302, location="https://objects.example/result.mp4")
            return FakeResponse(status=200, body=b"video")

    monkeypatch.setattr("app.ai.providers.media_transfer.RetryingClient", FakeClient)
    target = tmp_path / "result.mp4"
    download_to_path(
        "https://api.example/v1/files/1",
        target,
        trusted_base_url="https://api.example/v1",
        trusted_headers={"Authorization": "Bearer secret"},
    )

    assert clients[0]["headers"] == {"Authorization": "Bearer secret"}
    assert clients[1]["headers"] == {}
    assert target.read_bytes() == b"video"
