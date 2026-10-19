"""站点适配器的骨架:自定义 extractor 的工厂 + MissAV 的认领/拒绝。

**这一阶段不解析页面。** 认领(MissAV 是不是这个站、是不是视频详情页)现在就能确定 ——
URL parser 的 scheme / hostname / path 都是看得见的;而页面里媒体地址长什么样,要等真实页面
样本,不猜。所以这里钉两头:

1. **工厂的顺序**:自定义 extractor 必须先于 yt-dlp 默认被问到。判据不是「读了文档」,而是
   一条真的 `suitable()` 调用记录 —— 同一个 URL 只有自定义认领时,generic 一次都不该被问。
2. **适配器的认领/拒绝**:四个镜像的详情页命中;分类页、搜索页、相似域名、别的站点拒绝;
   认领了但解析还没写的,给一句明确的「还没支持这个站」,不是崩溃、不是空。

测试全部是本地 URL 字符串,不连外网。
"""
from __future__ import annotations

import pytest
from yt_dlp.extractor.common import InfoExtractor

from app.core.i18n import MESSAGES
from app.media import extractors, ytdlp


class _Claimed(Exception):
    """假 extractor 拿到 URL 之后表示「归我,而且我处理完了」。"""


@pytest.fixture
def site():
    """按需导入 MissAV 骨架:工厂那几条不该被一个还没写的模块挡住。"""
    from app.media.extractors import missav

    return missav


# ---------------- ① 工厂:自定义排在默认之前 ----------------


def test_custom_extractor_is_asked_before_ytdlp_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自定义 extractor 的 `suitable()` 必须先于 generic 被调用。

    这条是**运行时**判据,不是读 yt-dlp 的文档:同一个 URL 只有自定义认领,generic 一旦被问到,
    记录里就会多一条 `"generic"`。同时钉住 `_ies` 的插入顺序 —— 那正是「先问谁」的来源。
    """
    from yt_dlp.extractor.generic import GenericIE

    calls: list[str] = []

    class FirstIE(InfoExtractor):
        IE_NAME = "first"
        _VALID_URL = False

        @classmethod
        def suitable(cls, url: str) -> bool:
            calls.append("custom")
            return url == "https://example.com/claimed"

        def _real_extract(self, url: str) -> None:
            raise _Claimed

    def generic_suitable(cls, url: str) -> bool:
        calls.append("generic")
        return False

    monkeypatch.setattr(GenericIE, "suitable", classmethod(generic_suitable))
    monkeypatch.setattr(extractors, "CUSTOM_EXTRACTORS", (FirstIE,))

    ydl = ytdlp._youtube_dl({"quiet": True, "no_warnings": True})
    keys = list(ydl._ies)
    assert keys.index("First") < keys.index("Generic"), f"自定义没有排在默认前面:{keys[:5]}"

    with pytest.raises(_Claimed):
        ydl.extract_info("https://example.com/claimed", download=False)

    assert calls == ["custom"], "自定义认领之后,默认 extractor 不该再被问到"


def test_matching_extractor_asks_custom_extractors_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL 支持判定用**同一份集合、同一顺序**:自定义先于 yt-dlp 上游注册表。

    否则会出现「url-support 说支持 vimeo,但同一个地址下载时先被我们的适配器接管」这种分叉。
    """

    class SiteIE(InfoExtractor):
        IE_NAME = "site"
        _VALID_URL = False

        @classmethod
        def suitable(cls, url: str) -> bool:
            return url.startswith("https://vimeo.com/")

    monkeypatch.setattr(extractors, "CUSTOM_EXTRACTORS", (SiteIE,))

    # vimeo 本来是 yt-dlp 认得的(见 test_url_import 的注册表用例);自定义认领后必须先答。
    assert ytdlp.matching_extractor("https://vimeo.com/76979871") == "site"


def test_factory_and_matching_agree_on_the_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个自定义都认同一个 URL 时,工厂和 `matching_extractor` 都必须让**排在前面的**那一个赢。

    这是「两边顺序一致」的实际判据:不是各自都能认出站点,而是同一个 URL 在两边归同一个适配器。
    """

    class FirstIE(InfoExtractor):
        IE_NAME = "first"
        _VALID_URL = False

        @classmethod
        def suitable(cls, url: str) -> bool:
            return url == "https://example.com/both"

        def _real_extract(self, url: str) -> None:
            raise _Claimed

    class SecondIE(InfoExtractor):
        IE_NAME = "second"
        _VALID_URL = False

        @classmethod
        def suitable(cls, url: str) -> bool:
            return url == "https://example.com/both"

        def _real_extract(self, url: str) -> None:
            raise AssertionError("排在后面的适配器不该赢")

    monkeypatch.setattr(extractors, "CUSTOM_EXTRACTORS", (FirstIE, SecondIE))

    assert ytdlp.matching_extractor("https://example.com/both") == "first"
    ydl = ytdlp._youtube_dl({"quiet": True, "no_warnings": True})
    with pytest.raises(_Claimed):
        ydl.extract_info("https://example.com/both", download=False)


def test_custom_extractor_set_stays_empty_until_a_site_can_parse() -> None:
    """阶段一不登记还没写完解析的适配器。

    登记了它,`/api/assets/url-support` 会对 MissAV 详情页说「支持」,而真正导入只能报「还没支持
    这个站」—— 用户看到的是两句相反的话。等第二阶段解析能给出媒体地址,再把它加进 `CUSTOM_EXTRACTORS`。
    """
    assert extractors.CUSTOM_EXTRACTORS == ()


# ---------------- ② 认领与拒绝 ----------------


@pytest.mark.parametrize("host", ["missav.com", "missav.ws", "missav.ai", "missav.live"])
@pytest.mark.parametrize("path", ["/en/ssis-001", "/ja/abc-123", "/en/fc2-ppv-1234567"])
def test_each_mirror_detail_page_is_claimed(site, host: str, path: str) -> None:
    """四个镜像的详情页各命中。镜像列表是**代码配置事实**,不保证这些域名当下可用。"""
    url = f"https://{host}{path}"
    assert site.claims(url) is True
    assert site.MissAVIE.suitable(url) is True
    assert site.video_code(url) == path.rsplit("/", 1)[-1]


def test_detail_page_routing_prefix_and_trailing_slash_are_accepted(site) -> None:
    """详情页常见的两种写法:带 `dm<数字>` 路由前缀、末尾多一个斜杠。

    它们不改变「这是哪一条」,所以认领不该因为它们而漏掉。
    """
    assert site.claims("https://missav.ws/dm12/en/ssis-001")
    assert site.claims("https://missav.ws/en/ssis-001/")
    assert site.claims("https://missav.ws/ssis-001")
    assert site.video_code("https://missav.ws/dm12/en/SSIS-001/") == "ssis-001"


@pytest.mark.parametrize(
    "url",
    [
        # 分类 / 索引页:路径段是栏目名,不是某一条视频。
        "https://missav.ws/en/categories",
        "https://missav.ws/en/categories/ssis",
        "https://missav.ws/en/genres",
        "https://missav.ws/en/actresses/abc",
        "https://missav.ws/en/makers",
        # 搜索页:带查询串,而且路径就是 search。
        "https://missav.ws/en/search?q=ssis-001",
        "https://missav.ws/search?q=ssis-001",
        # 相似域名:精确 hostname,不是字符串包含。子域、后缀、前缀、别家 TLD 都不算。
        "https://missav.ws.evil.example/en/ssis-001",
        "https://www.missav.ws/en/ssis-001",
        "https://notmissav.ws/en/ssis-001",
        "https://missav.ws.example.com/en/ssis-001",
        "https://missav.example/en/ssis-001",
        "https://missav.tv/en/ssis-001",
        # 别的站点。
        "https://example.com/en/ssis-001",
        "https://vimeo.com/76979871",
        # 不是详情页的路径形状。
        "https://missav.ws/",
        "https://missav.ws/en",
        "https://missav.ws/en/ssis-001/extra",
        "https://missav.ws/en/../ssis-001",
        "https://missav.ws/en/ssis-001%2Fextra",
        # scheme / 端口 / 凭据:不认。
        "ftp://missav.ws/en/ssis-001",
        "https://missav.ws:8443/en/ssis-001",
        "https://user:pass@missav.ws/en/ssis-001",
    ],
)
def test_non_detail_pages_and_lookalikes_are_rejected(site, url: str) -> None:
    assert site.claims(url) is False
    assert site.MissAVIE.suitable(url) is False
    assert site.video_code(url) is None


# ---------------- ③ 认领了、但解析还没写 ----------------


def test_claimed_but_unparsed_site_raises_a_clear_localized_error(site) -> None:
    """不许返回近似地址,也不许崩在 NotImplementedError 上。

    适配器层抛 `SiteAdapterPending`(带站点名),**不 import `media/ytdlp`** —— 翻成给用户看的
    那句话是 `ytdlp.classify` 的事(见下一条走真实导入路径的用例)。
    """
    url = "https://missav.ws/en/ssis-001"
    assert site.claims(url)

    with pytest.raises(extractors.SiteAdapterPending) as caught:
        site.MissAVIE()._real_extract(url)

    assert caught.value.site == site.SITE_NAME
    assert "not implemented" in str(caught.value)
    assert set(MESSAGES["urlImportErr_sitePending"]) >= {"zh", "en"}
    # 缺省语言下的那句话要真的说清「还没接入」,而不是一句「取不到」。
    assert "还没接入" in str(ytdlp.YtdlpError("urlImportErr_sitePending", site=site.SITE_NAME))


def test_registered_adapter_pending_error_reaches_the_import_path(
    monkeypatch: pytest.MonkeyPatch, site
) -> None:
    """把适配器临时登记进集合时,`probe` 拿到的必须是同一句「还没支持这个站」。

    这条走的是真实构造路径(工厂 -> yt-dlp 认领 -> `_real_extract`),不连外网:适配器在发出
    任何请求之前就抛了。它同时钉住 `classify` 把 `SiteAdapterPending` 翻成带 key 的
    `YtdlpError`,而不是降级成一句泛泛的「取不到」。
    """
    monkeypatch.setattr(extractors, "CUSTOM_EXTRACTORS", (site.MissAVIE,))

    with pytest.raises(ytdlp.YtdlpError) as caught:
        ytdlp.probe("https://missav.ws/en/ssis-001")

    assert caught.value.key == "urlImportErr_sitePending"
    assert caught.value.params == {"site": site.SITE_NAME}


def test_youtube_dl_is_constructed_only_here() -> None:
    """所有 `YoutubeDL(...)` 构造点都走工厂 —— 否则自定义 extractor 的顺序就只在一处生效。

    这条是 `_youtube_dl` 上「唯一入口」那句话的守卫:扫 `app/` 下真的 `YoutubeDL(` 调用。
    """
    import pathlib

    app = pathlib.Path(ytdlp.__file__).resolve().parents[1]
    hits = sorted(
        str(path.relative_to(app))
        for path in app.rglob("*.py")
        if "YoutubeDL(" in path.read_text(encoding="utf-8")
    )
    assert hits == ["media/ytdlp.py"]
    assert pathlib.Path(ytdlp.__file__).read_text(encoding="utf-8").count("YoutubeDL(") == 1
