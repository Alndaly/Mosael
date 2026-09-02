"""从链接导入素材。

两个判断值得钉住,它们都是「顺手做了会出事」的那种:

1. **先探再下。** 一个链接可能是一条视频,也可能是一整个播放列表 —— 几百条、几十 GB。
   探测只读元数据,不碰媒体流。
2. **一条失败不拖垮整批。** 已经下好的留在素材库里;半小时的下载因为第七条被下架而全部作废,
   是最不该发生的事。
"""
from __future__ import annotations

import pytest

from app.domain.assets.from_url import MAX_ITEMS, UrlImportError, start_url_import
from app.domain.assets.source_url import source_url_key
from app.core.db import SessionLocal
from app.media import ytdlp
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_a_single_video_is_a_listing_of_one() -> None:
    """单条视频也走同一种形状 —— 界面因此只需要处理一种结果,不必分岔。"""
    listing = ytdlp.RemoteListing(title="t", is_playlist=False, entries=[], truncated=False)
    assert listing.is_playlist is False


def test_flat_entries_get_a_usable_url() -> None:
    """播放列表的浅层条目常常只给 id。拼不回地址的话,勾中之后根本无从下载。"""
    entry = ytdlp._entry({"id": "abc123", "title": "x"}, "https://example.com/list")
    assert entry.url == "https://www.youtube.com/watch?v=abc123"

    # 已经给了完整地址就用它自己的,不要覆盖成 YouTube —— yt-dlp 支持上千个站点。
    other = ytdlp._entry({"id": "1", "webpage_url": "https://www.bilibili.com/video/BV1"}, "https://x")
    assert other.url == "https://www.bilibili.com/video/BV1"


def test_supported_video_urls_have_stable_source_identities() -> None:
    assert source_url_key("https://cn.pornhub.com/view_video.php?viewkey=abc&utm_source=x") == "pornhub:abc"
    assert source_url_key("https://youtu.be/video-id?t=20") == "youtube:video-id"
    assert source_url_key("https://www.youtube.com/watch?v=video-id&feature=share") == "youtube:video-id"
    assert source_url_key("https://www.bilibili.com/video/BV1Ab411?spm_id_from=333") == "bilibili:BV1Ab411"


def test_refuses_an_empty_selection() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        with pytest.raises(UrlImportError):
            start_url_import(
                db, workspace_id=workspace_id, project_id=None, items=[], kind="video", created_by=None,
            )


def test_refuses_more_than_the_batch_cap() -> None:
    """一次几百条会变成一个跑几小时、中途失败还说不清进度的任务。分几次比那个好。"""
    client = fresh_client()
    workspace_id = _workspace(client)
    items = [{"url": f"https://example.com/{index}", "title": "t"} for index in range(MAX_ITEMS + 1)]
    with SessionLocal() as db:
        with pytest.raises(UrlImportError):
            start_url_import(
                db, workspace_id=workspace_id, project_id=None, items=items, kind="video", created_by=None,
            )


def test_only_video_or_audio() -> None:
    """`kind` 决定下什么流。别的值会被 yt-dlp 当成格式表达式,下出一个谁也没要的东西。"""
    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        with pytest.raises(UrlImportError):
            start_url_import(
                db, workspace_id=workspace_id, project_id=None,
                items=[{"url": "https://example.com/a", "title": "t"}],
                kind="bestvideo", created_by=None,
            )


def test_error_messages_say_what_to_do() -> None:
    """yt-dlp 的原始报错里混着 URL、格式 id 和 traceback。用户要的是「为什么不行、我能做什么」。"""
    assert "私有" in ytdlp._explain(Exception("ERROR: Private video. Sign in if you've been granted access"))
    assert "下架" in ytdlp._explain(Exception("ERROR: Video unavailable"))
    assert "超时" in ytdlp._explain(Exception("ERROR: The read operation timed out"))
    # 认不出来的照样要给一句话,而不是空串。
    assert ytdlp._explain(Exception("something else entirely")).strip()


def test_titles_with_glob_characters_can_still_be_found() -> None:
    """视频标题里 `[]` 很常见(`[Official MV]`)。不转义的话,找回落地文件那一步会匹配不到自己。"""
    assert ytdlp.glob_escape("Song [Official MV]") == "Song [[]Official MV[]]"


def test_quality_is_a_ceiling_not_an_exact_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """`height<=N` 而不是 `height=N`。

    同一个播放列表里每条能给的画质并不一样。要求"正好 1080p"会让没有这一档的那些直接
    「没有可用格式」;要"不超过 1080p"则每条都取它自己能给的最好的那一档。
    """
    captured: dict = {}

    class FakeYDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"id": "x", "title": "t", "ext": "mp4"}

        def prepare_filename(self, info):
            return str(tmp / "t.mp4")

    import sys
    import types
    from pathlib import Path
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    (tmp / "t.mp4").write_bytes(b"x")
    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)

    ytdlp.download("https://example.com/v", kind="video", target_dir=tmp, max_height=1080)
    assert "[height<=1080]" in captured["format"]
    assert "height=1080" not in captured["format"]

    # 不限时不带任何高度条件 —— 否则"最高画质"会被一个隐形的上限悄悄砍掉。
    ytdlp.download("https://example.com/v", kind="video", target_dir=tmp, max_height=0)
    assert "height<=" not in captured["format"]


def test_audio_ignores_the_quality_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """只要声轨时,画质上限没有意义 —— 把它拼进格式表达式会筛掉所有纯音频流。"""
    captured: dict = {}

    class FakeYDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"id": "x", "title": "t", "ext": "m4a"}

        def prepare_filename(self, info):
            return str(tmp / "t.m4a")

    import sys
    import types
    from pathlib import Path
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    (tmp / "t.m4a").write_bytes(b"x")
    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)

    ytdlp.download("https://example.com/v", kind="audio", target_dir=tmp, max_height=720)
    assert captured["format"] == "bestaudio/best"


def test_heights_are_unknown_not_empty_for_flat_entries() -> None:
    """浅层探测(播放列表)拿不到 formats。**空表示未知,不表示没有** ——
    界面据此给通用档位,而不是说"这条只有这几档"。"""
    assert ytdlp._heights({"id": "x"}) == ()
    assert ytdlp._heights({"formats": [{"height": 1080}, {"height": 720}, {"height": None}]}) == (1080, 720)


def test_signed_in_does_not_pin_a_client() -> None:
    """有登录态时**不指定客户端** —— 交给 yt-dlp 自己挑。

    实测很反直觉:同一份 cookie,写死 `web_safari/web/mweb` 只拿到 360p,而什么都不写反而拿到
    33 个格式、最高 1440p。写死的那串是为「匿名会被 403」准备的经验值,套到有登录态的情形上,
    等于用一个旧结论盖掉 yt-dlp 一直在更新的判断。
    """
    from pathlib import Path

    assert ytdlp._youtube_extractor_args(Path("/tmp/cookies.txt")) == {}
    anonymous = ytdlp._youtube_extractor_args(None)
    assert anonymous["youtube"]["player_client"][0] == "android"


def test_probe_start_shifts_the_window() -> None:
    """频道能有上万条。一次探 200 条,往后翻靠 `start` —— 第 201 条之后并非取不到,只是要再问一次。"""
    captured: dict = {}

    class FakeYDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"id": "x", "title": "t"}

    import sys
    import types

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL  # type: ignore[attr-defined]
    sys.modules["yt_dlp"] = fake
    try:
        ytdlp.probe("https://example.com/list", start=201)
        assert captured["playlist_items"] == f"201-{200 + ytdlp.MAX_ENTRIES}"
    finally:
        sys.modules.pop("yt_dlp", None)
