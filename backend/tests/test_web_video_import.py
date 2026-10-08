"""「下载页面里的视频」走的是从链接导入那个任务,多带两样东西:出处,以及能真的停下来。

- **出处**:条目带着所在页面(`page_url` / `page_title`)时,素材的 media_info 记下来源网址、页面标题、截取时间
  (= 点下载的那一刻)和 `capture = page_video`;`source_url` 仍是字节真正来自的那个地址。
- **直链要带 Referer**:很多站点的视频直链防盗链,不带「从哪一页来」只回 403。平台页面(地址就是页面本身)
  交给 yt-dlp 的站点解析器,不替它加请求头。
- **取消要真的停**:此前取消只改了任务那一行,yt-dlp 照样下完,收尾时再把任务写回「成功」、把素材塞进库里。
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.assets import from_url
from app.domain.assets.from_url import start_url_import
from app.domain.jobs import cancel_job, was_cancelled
from app.media import ytdlp
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _start(workspace_id: str, items: list[dict]) -> str:
    with SessionLocal() as db:
        job = start_url_import(db, workspace_id=workspace_id, project_id=None, kind="video", created_by=None, items=items)
        db.commit()
        return job.id


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    assets: list[SimpleNamespace] = []

    def fake_download(url, *, target_dir, **kwargs):
        calls.append({"url": url, **kwargs})
        path = target_dir / "clip.mp4"
        path.write_bytes(b"x")
        return path

    def fake_register(db, *, name, **kwargs):
        asset = SimpleNamespace(id=f"asset-{len(assets) + 1}", media_info={}, name=name)
        assets.append(asset)
        return asset

    monkeypatch.setattr(from_url.ytdlp, "download", fake_download)
    monkeypatch.setattr(from_url, "register_file_asset", fake_register)
    monkeypatch.setattr(from_url, "dispatch_job", lambda *args, **kwargs: None)
    # 内网守卫要解析域名,结果随本机网络而变;这里验的是出处与 Referer,守卫另有测试。
    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    return SimpleNamespace(calls=calls, assets=assets)


def test_页面里的直链带着出处入库_下载时带上_Referer(recorded) -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    job_id = _start(workspace_id, [{
        "url": "https://cdn.example.com/v/clip.mp4",
        "title": "一条视频",
        "page_url": "https://example.com/post/1",
        "page_title": "帖子标题",
    }])
    from_url._run(job_id)

    assert recorded.calls[0]["url"] == "https://cdn.example.com/v/clip.mp4"
    assert recorded.calls[0]["referer"] == "https://example.com/post/1"
    info = recorded.assets[0].media_info
    assert info["source_url"] == "https://cdn.example.com/v/clip.mp4"
    assert info["source_page_url"] == "https://example.com/post/1"
    assert info["source_page_title"] == "帖子标题"
    assert info["capture"] == "page_video"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None and job.status == "succeeded"
        assert info["captured_at"] == job.created_at.replace(tzinfo=__import__("datetime").timezone.utc).isoformat()


def test_平台页面交给站点解析器_不替它加_Referer(recorded) -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    page = "https://www.bilibili.com/video/BV1xx411c7mD"
    job_id = _start(workspace_id, [{"url": page, "title": "B 站视频", "page_url": page, "page_title": "B 站视频"}])
    from_url._run(job_id)
    assert recorded.calls[0]["referer"] == ""
    assert recorded.assets[0].media_info["source_page_url"] == page


def test_没有页面出处的普通导入不变(recorded) -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    job_id = _start(workspace_id, [{"url": "https://www.youtube.com/watch?v=abc", "title": "t"}])
    from_url._run(job_id)
    assert recorded.calls[0]["referer"] == ""
    assert "source_page_url" not in recorded.assets[0].media_info
    assert recorded.assets[0].media_info["source_url"] == "https://www.youtube.com/watch?v=abc"


def test_页面出处只认_http_s(recorded) -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        with pytest.raises(from_url.UrlImportError):
            start_url_import(
                db, workspace_id=workspace_id, project_id=None, kind="video", created_by=None,
                items=[{"url": "https://cdn.example.com/a.mp4", "title": "t", "page_url": "javascript:alert(1)"}],
            )


def test_取消之后真的停下_不再写回成功也不入库(monkeypatch: pytest.MonkeyPatch) -> None:
    """取消时下载正在进行:下一次进度回调就停下,任务保持「已取消」,这一条不进素材库。"""
    started = threading.Event()
    stopped: list[bool] = []
    registered: list[str] = []

    def slow_download(url, *, target_dir, should_stop, **kwargs):
        started.set()
        for _ in range(200):
            if should_stop():
                stopped.append(True)
                raise ytdlp.YtdlpCancelled()
            threading.Event().wait(0.02)
        path = target_dir / "late.mp4"
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr(from_url.ytdlp, "download", slow_download)
    monkeypatch.setattr(from_url, "register_file_asset", lambda db, **kw: registered.append(kw["name"]))
    monkeypatch.setattr(from_url, "dispatch_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)

    client = fresh_client()
    workspace_id = _workspace(client)
    job_id = _start(workspace_id, [
        {"url": "https://cdn.example.com/a.mp4", "title": "第一条", "page_url": "https://example.com/p", "page_title": "p"},
        {"url": "https://cdn.example.com/b.mp4", "title": "第二条", "page_url": "https://example.com/p", "page_title": "p"},
    ])
    worker = threading.Thread(target=from_url._run, args=(job_id,))
    worker.start()
    assert started.wait(5)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        cancel_job(db, job, by=None)
        db.commit()
    worker.join(10)
    assert not worker.is_alive()

    assert stopped == [True]
    assert registered == []
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None and was_cancelled(job)


def test_下载器收到停止信号就中止并说是被取消的(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """yt-dlp 的进度回调里抛 DownloadCancelled 是它自己认的中止方式;我们把它换成 YtdlpCancelled,
    不让它落进 classify 被说成一句「下载失败」。Referer 走 http_headers。"""
    captured: dict = {}

    class FakeYDL:
        def __init__(self, options):
            captured.update(options)
            self.hooks = options["progress_hooks"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            for hook in self.hooks:
                hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100})
            return {"id": "x", "title": "t", "ext": "mp4"}

        def prepare_filename(self, info):
            return str(tmp_path / "t.mp4")

    import sys
    import types

    from yt_dlp.utils import DownloadCancelled

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL  # type: ignore[attr-defined]
    fake_utils = types.ModuleType("yt_dlp.utils")
    fake_utils.DownloadCancelled = DownloadCancelled  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", fake_utils)

    with pytest.raises(ytdlp.YtdlpCancelled):
        ytdlp.download(
            "https://cdn.example.com/a.mp4", kind="video", target_dir=tmp_path,
            referer="https://example.com/p", should_stop=lambda: True,
        )
    assert captured["http_headers"] == {"Referer": "https://example.com/p"}
