"""从链接导入素材。

两个判断值得钉住,它们都是「顺手做了会出事」的那种:

1. **先探再下。** 一个链接可能是一条视频,也可能是一整个播放列表 —— 几百条、几十 GB。
   探测只读元数据,不碰媒体流。
2. **一条失败不拖垮整批。** 已经下好的留在素材库里;半小时的下载因为第七条被下架而全部作废,
   是最不该发生的事。
"""
from __future__ import annotations

import pytest
from yt_dlp.networking.exceptions import TransportError
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError, UnsupportedError

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


def _download_error(inner: BaseException) -> BaseException:
    """yt-dlp 抛给调用方的形状:外面一层 DownloadError,真正的原因藏在 exc_info 里。"""
    return DownloadError(f"ERROR: {inner}", (type(inner), inner, None))


class Test取不到时说清是哪一种原因:
    """「不支持」和「没有」是两回事。

    此前 Unsupported URL 和 no video 共用一句「这个链接里没有可下载的视频」:站点根本不认识,
    却被说成里面没有视频;要登录、被删除、被地区限制的又各落各的桶。样本都是 yt-dlp 的原话。
    """

    @pytest.mark.parametrize(
        ("error", "key"),
        [
            # 站点不认识(通用解析器在页面里也没找到视频)—— 不是「里面没有视频」。
            (_download_error(UnsupportedError("https://example.com/article")), "urlImportErr_unsupported"),
            (Exception("ERROR: 'foo' is not a valid URL. Set --default-search"), "urlImportErr_unsupported"),
            # 站点认识,这一条确实没有媒体流。
            (Exception("ERROR: [BiliBili] BV1xx: No video formats found!"), "urlImportErr_noMedia"),
            (Exception("ERROR: [Gettr] abc: There's no video in this post."), "urlImportErr_noMedia"),
            # 要登录:yt-dlp 的 raise_login_required 原话,以及 YouTube 的人机验证。
            (
                _download_error(ExtractorError(
                    "This video is only available for registered users. Use --cookies-from-browser or --cookies "
                    "for the authentication.", expected=True,
                )),
                "urlImportErr_loginRequired",
            ),
            (Exception("ERROR: [youtube] abc: Sign in to confirm you’re not a bot"), "urlImportErr_loginRequired"),
            (Exception("ERROR: [youtube] abc: Join this channel to get access to members-only content"), "urlImportErr_loginRequired"),
            # 私密 / 删除 / 下架:内容本身不可用。私密那句同时带着「Sign in」,但它首先是私密的。
            (Exception("ERROR: [youtube] abc: Private video. Sign in if you've been granted access to this video"), "urlImportErr_unavailable"),
            (Exception("ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader"), "urlImportErr_unavailable"),
            # 地区。
            (
                _download_error(GeoRestrictedError(
                    "This video is not available from your location due to geo restriction",
                )),
                "urlImportErr_geoBlocked",
            ),
            (Exception("ERROR: [youtube] abc: The uploader has not made this video available in your country"), "urlImportErr_geoBlocked"),
            (Exception("Your IP address is blocked from accessing this post"), "urlImportErr_geoBlocked"),
            # 网络:按类型认(TransportError 的原文可以是任何话)也按原话认。
            (
                _download_error(TransportError(
                    msg="EOF occurred in violation of protocol",
                )),
                "urlImportErr_network",
            ),
            (Exception("ERROR: [BiliBili] BV1: Unable to download webpage: The read operation timed out"), "urlImportErr_network"),
            (Exception("ERROR: Unable to download webpage: <urlopen error [Errno 61] Connection refused>"), "urlImportErr_network"),
            # 其余几类沿用原来的判断。
            (Exception("ERROR: [BiliBili] 1xx411c7X: Unable to download webpage: HTTP Error 404: Not Found"), "urlImportErr_notFound"),
            (Exception("HTTP Error 412: Precondition Failed"), "urlImportErr_forbidden"),
            (Exception("ERROR: [youtube] abc: Requested format is not available"), "urlImportErr_formatMismatch"),
            (Exception("ERROR: [x] abc: This video is DRM protected"), "urlImportErr_drm"),
            (Exception("ERROR: Postprocessing: ffmpeg exited with code 1"), "urlImportErr_mergeFailed"),
        ],
    )
    def test_按原因归类(self, error, key: str) -> None:
        assert ytdlp.classify(error).key == key

    def test_不支持和没有说的不是同一句话(self) -> None:
        from app.core.i18n import t

        unsupported = ytdlp.classify(Exception("ERROR: Unsupported URL: https://example.com/article"))
        empty = ytdlp.classify(Exception("ERROR: [BiliBili] BV1: No video formats found!"))
        assert str(unsupported) != str(empty)
        assert "不支持" in str(unsupported) and "没有找到视频或音频" in str(empty)
        assert "isn't supported" in t(unsupported.key, "en")

    def test_认不出来的给原文最后一行(self) -> None:
        error = ytdlp.classify(Exception("Traceback …\nERROR: something else entirely"))
        assert error.key == "urlImportErr_other"
        assert "something else entirely" in str(error) and "Traceback" not in str(error)

    def test_探测失败按请求方的语言说(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unsupported(*args, **kwargs):
            raise ytdlp.YtdlpError("urlImportErr_unsupported")

        monkeypatch.setattr(ytdlp, "probe", unsupported)
        client = fresh_client()
        workspace_id = _workspace(client)
        body = {"workspace_id": workspace_id, "url": "https://example.com/article"}
        english = client.post("/api/assets/probe-url", json=body, headers={"Accept-Language": "en-US"})
        chinese = client.post("/api/assets/probe-url", json=body, headers={"Accept-Language": "zh-CN"})
        assert english.status_code == chinese.status_code == 422
        assert "isn't supported" in english.json()["detail"]
        assert "不支持" in chinese.json()["detail"]


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


def test_url_support_uses_the_installed_ytdlp_registry() -> None:
    assert ytdlp.matching_extractor("https://vimeo.com/76979871") == "vimeo"
    assert ytdlp.matching_extractor("https://www.dailymotion.com/video/x84sh87") == "dailymotion"
    assert ytdlp.matching_extractor("https://www.tiktok.com/@scout2015/video/6718335390845095173") == "TikTok"
    assert ytdlp.matching_extractor("https://soundcloud.com/iameden/rock-roll") == "soundcloud"
    assert ytdlp.matching_extractor("https://example.com/video") is None
    assert ytdlp.matching_extractor("file:///tmp/video.mp4") is None


def test_url_support_api_exposes_registry_matching_without_network() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = client.get(
        "/api/assets/url-support",
        params={"workspace_id": workspace_id, "url": "https://vimeo.com/76979871"},
    )
    assert response.status_code == 200
    assert response.json() == {"supported": True, "extractor": "vimeo"}


def test_every_ytdlp_site_extractor_with_a_sample_remains_routable() -> None:
    """Exercise the entire installed registry without hitting 1,750 remote services.

    Live calls to every extractor are impossible (many require accounts, geo access or deleted
    media), but each extractor ships canonical test URLs. Every such site must still route through
    the same registry used by ``url-support`` after a yt-dlp upgrade.
    """
    unmatched: list[str] = []
    checked = 0
    for extractor in ytdlp.extractor_classes():
        samples = getattr(extractor, "_TESTS", ()) or ()
        sample = next(
            (
                str(item.get("url"))
                for item in samples
                if isinstance(item, dict)
                and str(item.get("url") or "").lower().startswith(("http://", "https://"))
            ),
            "",
        )
        if not sample:
            continue
        checked += 1
        matched = ytdlp.matching_extractor(sample)
        if matched != str(extractor.IE_NAME):
            unmatched.append(f"{extractor.IE_NAME} routed to {matched}: {sample}")
    assert checked >= 1_000
    assert unmatched == []


class Test没下成的那几条要说清为什么:
    """原因本来就是现成的,只是从来没交到用户手上。

    ytdlp._explain 已经把「HTTP Error 403」翻成了「站点拒绝了匿名取流,请选择已登录的浏览器
    档案」—— 一句能照着做的话。而任务上写的却是常量「没有一条下载成功」:既不说是哪一条,
    也不说该怎么办。一批 20 条里挂了 3 条时更糟,连哪 3 条都找不出来。
    """

    def test_全挂时把原因端出来(self) -> None:
        from app.domain.assets.from_url import failure_report

        report = failure_report([("某条视频", "这条内容是私有的 / 会员专属,没有登录态就取不到。")])
        assert "某条视频" in report and "私有" in report

    def test_整批同一个原因只说一遍(self) -> None:
        """多半是登录态或代理的问题 —— 逐条重复同一句话只是噪音,还会把真正不同的那条淹掉。"""
        from app.domain.assets.from_url import failure_report

        same = [(f"第{i}条", "站点要求登录或人机验证才能取这条内容。") for i in range(5)]
        report = failure_report(same)
        assert report.count("站点要求登录") == 1
        assert "5 条都失败了" in report

    def test_原因不同就逐条列(self) -> None:
        from app.domain.assets.from_url import failure_report

        report = failure_report([("甲", "已下架"), ("乙", "需要登录")])
        assert "「甲」:已下架" in report and "「乙」:需要登录" in report

    def test_太多条时截断并说还有几条(self) -> None:
        """一批 50 条全挂,把 50 行糊进任务详情只会让人一行都不看。"""
        from app.domain.assets.from_url import failure_report

        many = [(f"第{i}条", f"原因{i}") for i in range(20)]
        report = failure_report(many)
        assert report.count("\n") < 12
        assert "还有 12 条" in report

    def test_一条都没记下来时仍有话说(self) -> None:
        from app.domain.assets.from_url import failure_report

        assert failure_report([]) == "没有一条下载成功"


#: yt-dlp 2026.08.19 对 B 站多 P 视频 `extract_flat="in_playlist"` 的真实输出(截取三条)。
#: 条目只有地址 —— 没有 id、没有标题,分 P 名不在这里。
_BILIBILI_COLLECTION = "【ComfyUI】MiniMaxH3最强人物替换 ！宗主第二式多人替换也能稳住？动作迁移与角色替换的开源天花板工作流"
_BILIBILI_FLAT = {
    "_type": "playlist",
    "id": "BV1qEtn6ZEWe",
    "title": _BILIBILI_COLLECTION,
    "extractor": "BiliBili",
    "entries": [
        {"ie_key": "BiliBili", "_type": "url", "url": f"https://www.bilibili.com/video/BV1qEtn6ZEWe?p={part}"}
        for part in (1, 2, 3)
    ],
}
#: 同一版本对单个分 P 地址 `process=False` 的输出(只留用得到的字段)。
_BILIBILI_PARTS = {
    f"https://www.bilibili.com/video/BV1qEtn6ZEWe?p={part}": {
        "_type": "video",
        "id": f"BV1qEtn6ZEWe_p{part}",
        "title": f"{_BILIBILI_COLLECTION} p{part:02d} {name}",
        "webpage_url": f"https://www.bilibili.com/video/BV1qEtn6ZEWe?p={part}",
        "duration": duration,
        "uploader": "comfyui大本营",
        "thumbnail": "http://i1.hdslb.com/bfs/archive/x.jpg",
        "formats": [{"height": 1080}, {"height": 720}],
    }
    for part, name, duration in (
        (1, "开篇", 393.531),
        (2, "全新ComfyUI中文桌面版", 432.217),
        (3, "01.ComfyUI 界面的常用按钮和功能", 1153.195),
    )
}


class Test浅层条目没标题时逐条补:
    """B 站多 P 视频探出来九行「未命名」。

    浅层探测里每条只有 `{"_type": "url", "url": "…?p=2"}` —— 分 P 名 yt-dlp 自己取到了,
    却没放进条目。补法与站点无关:对缺标题的那几条再问一次(`process=False`,不挑格式、不下载)。
    """

    def _fake_ytdlp(self, monkeypatch: pytest.MonkeyPatch, flat: dict, *, broken: frozenset[str] = frozenset()) -> list[tuple]:
        import sys
        import types

        calls: list[tuple] = []

        class FakeYDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False, process=True):
                calls.append((url, download, process))
                if url in _BILIBILI_PARTS:
                    if url in broken:
                        raise RuntimeError("HTTP Error 412: Precondition Failed")
                    return dict(_BILIBILI_PARTS[url])
                return dict(flat)

        fake = types.ModuleType("yt_dlp")
        fake.YoutubeDL = FakeYDL  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "yt_dlp", fake)
        return calls

    def test_分P条目带上各自的标题(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._fake_ytdlp(monkeypatch, _BILIBILI_FLAT)
        listing = ytdlp.probe("https://www.bilibili.com/video/BV1qEtn6ZEWe/?t=6")

        assert listing.title == _BILIBILI_COLLECTION
        # 合集标题已经在表头;每行只留区分各条的那段,不然截断后九行看起来一模一样。
        assert [entry.title for entry in listing.entries] == [
            "p01 开篇", "p02 全新ComfyUI中文桌面版", "p03 01.ComfyUI 界面的常用按钮和功能",
        ]
        assert [entry.id for entry in listing.entries] == ["BV1qEtn6ZEWe_p1", "BV1qEtn6ZEWe_p2", "BV1qEtn6ZEWe_p3"]
        assert listing.entries[1].url == "https://www.bilibili.com/video/BV1qEtn6ZEWe?p=2"
        assert listing.entries[1].duration == 432.217
        assert listing.entries[1].heights == (1080, 720)
        # 补元数据绝不能碰媒体流。
        per_entry = [call for call in calls if call[0] in _BILIBILI_PARTS]
        assert len(per_entry) == 3
        assert all(download is False and process is False for _, download, process in per_entry)

    def test_已有标题的条目一条也不多问(self, monkeypatch: pytest.MonkeyPatch) -> None:
        titled = {**_BILIBILI_FLAT, "entries": [{"id": "a", "title": "第一条", "url": "https://example.com/a"}]}
        calls = self._fake_ytdlp(monkeypatch, titled)
        listing = ytdlp.probe("https://example.com/list")
        assert [entry.title for entry in listing.entries] == ["第一条"]
        assert len(calls) == 1

    def test_某条补不上不拖垮整份清单(self, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = "https://www.bilibili.com/video/BV1qEtn6ZEWe?p=2"
        self._fake_ytdlp(monkeypatch, _BILIBILI_FLAT, broken=frozenset({broken}))
        listing = ytdlp.probe("https://www.bilibili.com/video/BV1qEtn6ZEWe")
        assert [entry.title for entry in listing.entries] == ["p01 开篇", "未命名", "p03 01.ComfyUI 界面的常用按钮和功能"]
        assert listing.entries[1].url == broken


def test_imported_assets_take_the_entry_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户勾的是哪个名字,素材就叫哪个名字。

    落地文件名按 `%(title).120B [%(id)s]` 截断;B 站分 P 的标题前面是七八十字的合集标题,
    截掉的恰好是分 P 名 —— 九条入库后名字只差末尾的 `[BV…_p2]`。
    """
    from types import SimpleNamespace

    from app.domain.assets import from_url

    truncated = "【ComfyUI】MiniMaxH3最强人物替换 ！宗主第二式多人替换也能稳住？动作迁移与角 [BV1qEtn6ZEWe_p2].mp4"

    def fake_download(url, *, target_dir, **kwargs):
        path = target_dir / truncated
        path.write_bytes(b"x")
        return path

    names: list[str] = []

    def fake_register(db, *, name, **kwargs):
        names.append(name)
        return SimpleNamespace(id=f"asset-{len(names)}", media_info={})

    monkeypatch.setattr(from_url.ytdlp, "download", fake_download)
    monkeypatch.setattr(from_url, "register_file_asset", fake_register)
    monkeypatch.setattr(from_url, "dispatch_job", lambda *args, **kwargs: None)

    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        job = start_url_import(
            db, workspace_id=workspace_id, project_id=None, kind="video", created_by=None,
            items=[
                {"url": "https://www.bilibili.com/video/BV1qEtn6ZEWe?p=2", "title": "p02 全新ComfyUI中文桌面版"},
                {"url": "https://www.bilibili.com/video/BV1qEtn6ZEWe?p=3", "title": ""},
            ],
        )
        db.commit()
        job_id = job.id
    from_url._run(job_id)

    # 没给标题(直接调接口)时才退回落地文件名。
    assert names == ["p02 全新ComfyUI中文桌面版.mp4", truncated]
