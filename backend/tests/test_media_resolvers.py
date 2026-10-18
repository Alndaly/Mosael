"""页面 → 媒体地址的窄接缝(`backend/app/media/resolvers`)。

这条接缝只回答一个问题:「这个页面地址对应的媒体地址是什么,取它需要带什么头?」
答案是**有或没有**——认不出来就是 `None`,绝不返回近似。现在注册表是空的(还没有任何站点),
所以测试里的 resolver 是假的;但契约、接线、守卫三样现在就得钉住,以后加一家站点才只是
「一个新文件 + 几条测试」。

接线点两处(见 `domain/assets/from_url`):探测前问一次、每一条下载前再问一次。
resolver 自己抓页面必须走 `RetryingClient` / `ticket(Origin.GIVEN)` —— 裸 httpx 会绕过
出站检查,这条也在这里钉着。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.core.http_retry import RetryingClient
from app.core.outbound_guard import Origin
from app.media import resolvers
from app.media.resolvers import ResolvedMedia
from app.domain.assets import from_url
from app.domain.assets.from_url import start_url_import
from tests.util import fresh_client


@pytest.fixture
def registry():
    added: list = []

    def add(fn):
        resolvers.register(fn)
        added.append(fn)
        return fn

    yield add
    for fn in added:
        resolvers.unregister(fn)


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_注册表默认是空的_认不出来就是_None() -> None:
    """现在没有任何站点。空注册表必须返回 None —— 调用方据此退回 yt-dlp。"""
    assert resolvers.resolve("https://example.com/watch?v=1") is None


def test_探测前问一次_命中时用_resolver_给的地址(monkeypatch: pytest.MonkeyPatch, registry) -> None:
    calls: list[str] = []

    @registry
    def fake(url: str) -> ResolvedMedia | None:
        calls.append(url)
        if url == "https://example.com/watch?v=1":
            return ResolvedMedia(
                url="https://cdn.example.com/media/1.mp4",
                headers={"Referer": "https://example.com/watch?v=1"},
                title="一集",
            )
        return None

    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    listing = from_url.probe_url("https://example.com/watch?v=1", workspace_id="w", actor=None)

    assert calls == ["https://example.com/watch?v=1"]
    assert listing.is_playlist is False
    assert [entry.url for entry in listing.entries] == ["https://cdn.example.com/media/1.mp4"]
    assert listing.entries[0].title == "一集"


def test_认不出来就退回_yt_dlp(monkeypatch: pytest.MonkeyPatch, registry) -> None:
    asked: list[str] = []
    sentinel = object()

    @registry
    def fake(url: str) -> ResolvedMedia | None:
        asked.append(url)
        return None

    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    monkeypatch.setattr(from_url.ytdlp, "probe", lambda url, **kwargs: sentinel)
    assert from_url.probe_url("https://example.com/watch?v=1", workspace_id="w", actor=None) is sentinel
    assert asked == ["https://example.com/watch?v=1"]


def test_下载前再问一次_用_resolver_的地址和头(monkeypatch: pytest.MonkeyPatch, registry) -> None:
    """探测和下载是两次独立的调用:下载这一条自己也要问一次,不能只依赖探测那一次的结果。"""
    calls: list[str] = []
    downloaded: list[dict] = []

    @registry
    def fake(url: str) -> ResolvedMedia | None:
        calls.append(url)
        if url == "https://example.com/watch?v=1":
            return ResolvedMedia(
                url="https://cdn.example.com/media/1.mp4",
                headers={"Referer": "https://example.com/watch?v=1", "User-Agent": "Mozilla/5.0"},
            )
        return None

    def fake_download(url: str, **kwargs):
        downloaded.append({"url": url, **kwargs})
        path = Path(kwargs["target_dir"]) / "clip.mp4"
        path.write_bytes(b"x")
        return path

    assets: list[SimpleNamespace] = []

    def fake_register(db, *, name, **_kwargs):
        asset = SimpleNamespace(id=f"asset-{len(assets) + 1}", media_info={}, name=name)
        assets.append(asset)
        return asset

    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    monkeypatch.setattr(from_url.ytdlp, "download", fake_download)
    monkeypatch.setattr(from_url, "register_file_asset", fake_register)
    monkeypatch.setattr(from_url, "dispatch_job", lambda *args, **kwargs: None)

    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        job = start_url_import(
            db, workspace_id=workspace_id, project_id=None, kind="video", created_by=None,
            items=[{"url": "https://example.com/watch?v=1", "title": "一集"}],
        )
        db.commit()
        job_id = job.id

    from_url._run(job_id)

    assert calls == ["https://example.com/watch?v=1"]
    assert downloaded[0]["url"] == "https://cdn.example.com/media/1.mp4"
    assert downloaded[0]["referer"] == "https://example.com/watch?v=1"
    # 其它必需的头也带过去(有些站点的直链要 UA)。
    assert downloaded[0]["headers"] == {"User-Agent": "Mozilla/5.0"}
    assert assets[0].media_info["source_url"] == "https://example.com/watch?v=1", "出处记页面,不记媒体直链"


def test_认不出来时下载仍用原地址(monkeypatch: pytest.MonkeyPatch, registry) -> None:
    @registry
    def fake(url: str) -> ResolvedMedia | None:
        return None

    downloaded: list[str] = []

    def fake_download(url: str, **kwargs):
        downloaded.append(url)
        path = Path(kwargs["target_dir"]) / "clip.mp4"
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    monkeypatch.setattr(from_url.ytdlp, "download", fake_download)
    monkeypatch.setattr(from_url, "register_file_asset", lambda db, **kwargs: SimpleNamespace(id="a", media_info={}))
    monkeypatch.setattr(from_url, "dispatch_job", lambda *args, **kwargs: None)

    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        job = start_url_import(
            db, workspace_id=workspace_id, project_id=None, kind="video", created_by=None,
            items=[{"url": "https://example.com/watch?v=1", "title": "t"}],
        )
        db.commit()
        job_id = job.id

    from_url._run(job_id)
    assert downloaded == ["https://example.com/watch?v=1"]


def test_resolver_自己抓页面也过出站守卫(monkeypatch: pytest.MonkeyPatch, registry) -> None:
    """resolver 认出了页面,但它要跟去的地址在私网 —— 守卫必须在**那一条连接**上拦下。

    这条也是「不许裸 httpx」的实际判据:走 RetryingClient(Origin.GIVEN) 才会过 GuardedTransport。
    """
    fetched: list[str] = []

    @registry
    def fake(url: str) -> ResolvedMedia | None:
        if not url.startswith("https://example.com/"):
            return None
        with RetryingClient(origin=Origin.GIVEN, max_retries=0, timeout=2.0) as client:
            # 页面里写着一条内网地址:跟过去就是一次 SSRF 尝试。
            client.get("http://127.0.0.1:9/secret")
        fetched.append(url)
        return ResolvedMedia(url="https://cdn.example.com/x.mp4")

    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    with pytest.raises(from_url.UrlImportError) as caught:
        from_url.probe_url("https://example.com/watch", workspace_id="w", actor=None)

    assert fetched == []
    assert caught.value.key.startswith("outboundErr_"), caught.value.key
    assert "127.0.0.1" in str(caught.value)
