"""站点适配器:自定义 extractor 的工厂 + MissAV 的认领与页面解析。

这一版钉三头:

1. **工厂的顺序**:自定义 extractor 必须先于 yt-dlp 默认被问到。判据不是「读了文档」,而是
   一条真的 `suitable()` 调用记录 —— 同一个 URL 只有自定义认领时,generic 一次都不该被问。
2. **认领/拒绝**:可用的两个镜像的详情页命中;被 Cloudflare 拦下的 `.ai/.ws`、占位页 `.com`、
   分类/搜索页、相似域名拒绝;`send-154-uncensored-leak`、`pondo-100524_001` 这些真实代码形状命中。
3. **解析**:页面里的媒体地址藏在 Dean Edwards packer 块里。用**离线构造**的标准 packer 块做 fixture
   (不含任何真实 uuid),断言一次解出三个地址、master 交给 yt-dlp 的 HLS 解析器、720p/1080p 成为
   额外 format、每个 format 都带 `Referer` 与浏览器 UA;坏页面给明确错误,不是崩溃,也不是近似地址。

测试全部离线:页面内容是自己拼的,不连外网。
"""
from __future__ import annotations

import re
from email.message import Message

import pytest
from yt_dlp.extractor.common import InfoExtractor

from app.core.i18n import MESSAGES
from app.media import extractors, ytdlp
from app.media.extractors import errors


class _Claimed(Exception):
    """假 extractor 拿到 URL 之后表示「归我,而且我处理完了」。"""


@pytest.fixture
def site():
    from app.media.extractors import missav

    return missav


# ---------------- 离线 fixture:标准 Dean Edwards packer ----------------


#: 标准 packer 的外壳。与真实页面里那一层**结构相同**,但内容全是测试自己写的:
#: 没有真实 uuid、没有真实页面正文,也不依赖 `/tmp` 里的任何样本。
_PACKER_HEAD = (
    "eval(function(p,a,c,k,e,d){e=function(c){return c.toString(36)};"
    "if(!''.replace(/^/,String)){while(c--){d[c.toString(a)]=k[c]||c.toString(a)}"
    "k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};"
    "while(c--){if(k[c]){p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c])}}"
    "return p}("
)


def _base_n(number: int, base: int) -> str:
    """packer 用的 base-n 记号(与 yt-dlp 的 `encode_base_n` 同一张表)。"""
    table = "0123456789abcdefghijklmnopqrstuvwxyz"
    if not number:
        return table[0]
    out = ""
    while number:
        out = table[number % base] + out
        number //= base
    return out


def _packed(decoded: str) -> str:
    """把一个标准 packer 块编码出来 —— 这就是 yt-dlp `decode_packed_codes` 的逆操作。

    只编码测试自己写的句子。真实页面里引号是 `\\'` 转义过的,这里也照做:解码之后的文本因此带着
    `\\'`,正好覆盖「解码结果里引号是转义的」这条真实形状。
    """
    words = sorted(set(re.findall(r"\b\w+\b", decoded)))
    table = {word: _base_n(index, 36) for index, word in enumerate(words)}
    payload = re.sub(r"\b\w+\b", lambda match: table[match.group(0)], decoded)
    payload = payload.replace("\\", "\\\\").replace("'", "\\'")
    symbols = "|".join(words)
    return _PACKER_HEAD + f"'{payload}',36,{len(words)},'{symbols}'.split('|'),0,{{}}))"


#: 测试里的媒体地址全部指向一个**不存在的**域名,不会被误当成任何真实站点。
_FIXTURE_CDN = "https://media.example.test/offline-fixture"
_MASTER = f"{_FIXTURE_CDN}/playlist.m3u8"
_720 = f"{_FIXTURE_CDN}/720p/video.m3u8"
_1080 = f"{_FIXTURE_CDN}/1080p/video.m3u8"


def _media_script(master: str | None = _MASTER, h720: str | None = _720, h1080: str | None = _1080) -> str:
    """一块含 `source` / `source842` / `source1280` 的 packed 脚本。"""
    parts = []
    if master is not None:
        parts.append(f"source='{master}';")
    if h720 is not None:
        parts.append(f"source842='{h720}';")
    if h1080 is not None:
        parts.append(f"source1280='{h1080}';")
    return _packed("".join(parts))


def _whitelist_script() -> str:
    """第二块脚本:真实页面里的 host 白名单 / 跳转脚本 —— 能解开,但**一个媒体地址都没有**。"""
    return _packed(
        "hosts=['missav123.com','missav.live'];"
        "if(location.hostname!=='missav123.com'){location.href='https://missav123.com/';}"
    )


def _page(
    *scripts: str,
    title: str | None = "Fixture title - MissAV",
    og_title: str | None = None,
    og_image: str | None = None,
) -> str:
    head = []
    if title is not None:
        head.append(f"<title>{title}</title>")
    if og_title is not None:
        head.append(f'<meta property="og:title" content="{og_title}">')
    if og_image is not None:
        head.append(f'<meta property="og:image" content="{og_image}">')
    return "<!doctype html><html><head>" + "".join(head) + "</head><body>" + "".join(scripts) + "</body></html>"


class _FakeResponse:
    """`_request_webpage` 的最小替身:按上限读字节、带一个可解码的 headers。"""

    def __init__(self, body: bytes, charset: str | None = None) -> None:
        self._body = body
        self._offset = 0
        self.headers = Message()
        if charset:
            self.headers["Content-Type"] = f"text/html; charset={charset}"

    def read(self, amount: int | None = None) -> bytes:
        if amount is None:
            chunk = self._body[self._offset:]
        else:
            chunk = self._body[self._offset:self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        pass


def _serve_page(monkeypatch: pytest.MonkeyPatch, site, page: str):
    """把页面喂给 extractor,不经过网络。返回实际收到的请求头。"""
    seen: dict[str, object] = {}

    def fake_request(self, url, video_id, note=None, headers=None, fatal=True):
        seen["headers"] = dict(headers or {})
        seen["url"] = url
        return _FakeResponse(page.encode("utf-8"))

    monkeypatch.setattr(site.MissAVIE, "_request_webpage", fake_request)
    return seen


def _parse(site, monkeypatch: pytest.MonkeyPatch, page: str, url: str = "https://missav123.com/cn/ssis-001"):
    monkeypatch.setattr(site.MissAVIE, "_fetch_page", lambda self, url, video_id, host: page)
    return site.MissAVIE()._real_extract(url)


def _stub_master(monkeypatch: pytest.MonkeyPatch, site) -> dict[str, object]:
    """把 `_extract_m3u8_formats_and_subtitles` 换成记录参数、返回一档 360p 的桩。"""
    calls: dict[str, object] = {}

    def fake(self, m3u8_url, video_id, ext=None, entry_protocol=None, headers=None, **kwargs):
        calls.update({"url": m3u8_url, "video_id": video_id, "ext": ext, "entry_protocol": entry_protocol})
        return (
            [{
                "format_id": "hls-360",
                "url": m3u8_url,
                "height": 360,
                "ext": "mp4",
                "protocol": entry_protocol,
                "http_headers": dict(headers or {}),
            }],
            {"en": [{"url": "https://media.example.test/offline-fixture/sub.vtt"}]},
        )

    monkeypatch.setattr(site.MissAVIE, "_extract_m3u8_formats_and_subtitles", fake)
    return calls


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


def test_missav_is_registered_only_after_it_can_parse(site) -> None:
    """解析写完了,才登记。登记之后 `url-support` 与真正下载走同一个适配器。"""
    assert extractors.CUSTOM_EXTRACTORS == (site.MissAVIE,)
    assert ytdlp.matching_extractor("https://missav123.com/cn/ssis-001") == "missav"
    assert ytdlp.matching_extractor("https://missav.live/en/ssis-001") == "missav"


def test_url_support_api_says_supported_for_a_detail_page() -> None:
    """`/api/assets/url-support` 对详情页说「支持」—— 这是登记之后必须成立的对外承诺。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    response = client.get(
        "/api/assets/url-support",
        params={"workspace_id": workspace_id, "url": "https://missav123.com/cn/ssis-001"},
    )
    assert response.status_code == 200
    assert response.json() == {"supported": True, "extractor": "missav"}

    # 被 Cloudflare 拦下的域名不认领:说支持、然后必然失败,比说不知道更糟。
    blocked = client.get(
        "/api/assets/url-support",
        params={"workspace_id": workspace_id, "url": "https://missav.ai/cn/ssis-001"},
    )
    assert blocked.json() == {"supported": False, "extractor": ""}


# ---------------- ② 认领与拒绝 ----------------


@pytest.mark.parametrize("host", ["missav123.com", "missav.live"])
@pytest.mark.parametrize(
    "path",
    [
        "/en/ssis-001",
        "/ja/abc-123",
        "/en/fc2-ppv-1234567",
        "/cn/send-154-uncensored-leak",
        "/dm178/cn/pondo-100524_001",
    ],
)
def test_each_working_mirror_detail_page_is_claimed(site, host: str, path: str) -> None:
    """两个**实测可用**镜像的详情页各命中。域名是代码配置事实,不保证永远可用。"""
    url = f"https://{host}{path}"
    assert site.claims(url) is True
    assert site.MissAVIE.suitable(url) is True
    assert site.video_code(url) == path.rsplit("/", 1)[-1].lower()


def test_detail_page_routing_prefix_and_trailing_slash_are_accepted(site) -> None:
    """详情页常见的两种写法:带 `dm<数字>` 路由前缀、末尾多一个斜杠。

    它们不改变「这是哪一条」,所以认领不该因为它们而漏掉。
    """
    assert site.claims("https://missav123.com/dm12/en/ssis-001")
    assert site.claims("https://missav123.com/en/ssis-001/")
    assert site.claims("https://missav.live/ssis-001")
    assert site.video_code("https://missav123.com/dm12/en/SSIS-001/") == "ssis-001"


@pytest.mark.parametrize(
    "url",
    [
        # 被 Cloudflare managed challenge 拦死的域名:认领会让我们接管一个必然 403 的地址。
        "https://missav.ai/cn/ssis-001",
        "https://missav.ws/cn/ssis-001",
        # 占位页,不是镜像。
        "https://missav.com/cn/ssis-001",
        # 分类 / 索引页:路径段是栏目名,不是某一条视频。
        "https://missav123.com/en/categories",
        "https://missav123.com/en/categories/ssis",
        "https://missav123.com/en/genres/VR",
        "https://missav123.com/en/actresses/abc",
        "https://missav123.com/en/makers",
        # 搜索页:路径是 search,不是查询串。
        "https://missav123.com/en/search/ssis-001",
        "https://missav123.com/search?q=ssis-001",
        # 相似域名:精确 hostname,不是字符串包含。子域、后缀、前缀、别家 TLD 都不算。
        "https://missav123.com.evil.example/en/ssis-001",
        "https://www.missav123.com/en/ssis-001",
        "https://notmissav123.com/en/ssis-001",
        "https://missav123.com.example.com/en/ssis-001",
        "https://notmissav.live/en/ssis-001",
        "https://missav.live.example.com/en/ssis-001",
        "https://missav.example/en/ssis-001",
        "https://missav.tv/en/ssis-001",
        # 别的站点。
        "https://example.com/en/ssis-001",
        "https://vimeo.com/76979871",
        # 不是详情页的路径形状。
        "https://missav123.com/",
        "https://missav123.com/en",
        "https://missav123.com/en/ssis-001/extra",
        "https://missav123.com/en/../ssis-001",
        "https://missav123.com/en/ssis-001%2Fextra",
        # scheme / 端口 / 凭据:不认。
        "ftp://missav123.com/en/ssis-001",
        "https://missav123.com:8443/en/ssis-001",
        "https://user:pass@missav123.com/en/ssis-001",
    ],
)
def test_non_detail_pages_lookalikes_and_blocked_hosts_are_rejected(site, url: str) -> None:
    assert site.claims(url) is False
    assert site.MissAVIE.suitable(url) is False
    assert site.video_code(url) is None


@pytest.mark.parametrize(
    "code",
    [
        # 服务器真实接受的四种形状:数字段之后还可以有字母,代码里也可以有下划线。
        "ssis-001",
        "fc2-ppv-4993717",
        "send-154-uncensored-leak",
        "pondo-100524_001",
    ],
)
def test_real_video_code_shapes_are_accepted(site, code: str) -> None:
    url = f"https://missav123.com/cn/{code}"
    assert site.claims(url) is True
    assert site.video_code(url) == code


@pytest.mark.parametrize(
    "segment",
    [
        # 不是视频代码:没有连字符、没有三位数字、或者只是栏目名。
        "fc2",
        "chinese-subtitle",
        "uncensored-leak",
        "4k-videos",
        "today-hot",
    ],
)
def test_index_words_and_short_shapes_are_not_taken_for_video_codes(site, segment: str) -> None:
    url = f"https://missav123.com/cn/{segment}"
    assert site.claims(url) is False
    assert site.video_code(url) is None


# ---------------- ③ 页面解析:packed 块 -> 媒体地址 -> formats ----------------


def test_packed_page_yields_three_addresses_and_extra_formats(
    site, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一次解出 master / 720p / 1080p;master 交给 yt-dlp 的 HLS 解析器,另两档是额外 format。

    每一档都带 `Referer` 与浏览器 UA:取流少了 Referer 会 403(实测),这不是可选的装饰。
    """
    calls = _stub_master(monkeypatch, site)
    info = _parse(site, monkeypatch, _page(_media_script()))

    assert calls["url"] == _MASTER
    assert calls["entry_protocol"] == "m3u8_native"
    assert calls["video_id"] == "ssis-001"

    assert info["id"] == "ssis-001"
    assert info["title"] == "Fixture title - MissAV"
    assert info["webpage_url"] == "https://missav123.com/cn/ssis-001"

    formats = info["formats"]
    assert [height for height in sorted(format_["height"] for format_ in formats)] == [360, 720, 1080]
    extras = {format_["height"]: format_ for format_ in formats if format_["format_id"] != "hls-360"}
    assert extras[720]["url"] == _720
    assert extras[720]["ext"] == "mp4"
    assert extras[720]["protocol"] == "m3u8_native"
    assert extras[1080]["url"] == _1080
    assert extras[1080]["ext"] == "mp4"
    assert extras[1080]["protocol"] == "m3u8_native"

    for format_ in formats:
        headers = format_["http_headers"]
        assert headers["Referer"] == "https://missav123.com/"
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert "Chrome/" in headers["User-Agent"]


def test_page_request_carries_browser_ua_and_referer(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """页面请求同样要浏览器 UA 与本站 Referer —— 少了 UA 是 403 challenge,少了 Referer 也是。"""
    seen = _serve_page(monkeypatch, site, _page(_media_script()))
    _stub_master(monkeypatch, site)
    site.MissAVIE()._real_extract("https://missav123.com/cn/ssis-001")

    assert seen["url"] == "https://missav123.com/cn/ssis-001"
    assert seen["headers"]["Referer"] == "https://missav123.com/"
    assert seen["headers"]["User-Agent"].startswith("Mozilla/5.0")


def test_live_mirror_uses_its_own_referer(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """媒体地址的 Referer 必须是**当前那一个镜像**,不是写死的 123。"""
    _stub_master(monkeypatch, site)
    info = _parse(site, monkeypatch, _page(_media_script()), url="https://missav.live/en/ssis-001")

    assert info["webpage_url"] == "https://missav.live/en/ssis-001"
    for format_ in info["formats"]:
        assert format_["http_headers"]["Referer"] == "https://missav.live/"


def test_query_on_a_media_address_is_kept_verbatim(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """现在的地址没有 query,但解析**不能写死**「没有 query」—— 签名串一旦被截掉就是 403。"""
    address_with_query = f"{_720}?token=fixture-token&expires=1"
    _stub_master(monkeypatch, site)
    info = _parse(site, monkeypatch, _page(_media_script(h720=address_with_query)))

    extra = next(format_ for format_ in info["formats"] if format_["height"] == 720)
    assert extra["url"] == address_with_query


def test_second_packed_block_without_media_is_ignored(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """页面里有两块 packed 脚本;第二块是白名单/跳转脚本,解出来没有 `.m3u8`,不该冒充媒体地址。"""
    calls = _stub_master(monkeypatch, site)
    info = _parse(site, monkeypatch, _page(_media_script(), _whitelist_script()))

    assert calls["url"] == _MASTER
    assert [format_["height"] for format_ in info["formats"]] == [360, 720, 1080]
    assert all("whitelist" not in format_["url"] for format_ in info["formats"])


def test_undecodable_block_is_skipped_without_crashing(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """解不动的块只跳过它自己;后面的好块照样能解出地址。"""
    broken = "eval(function(p,a,c,k,e,d){throw new Error('broken m3u8')}('x'.split('|')))"
    _stub_master(monkeypatch, site)
    info = _parse(site, monkeypatch, _page(broken, _media_script()))

    assert [format_["height"] for format_ in info["formats"]] == [360, 720, 1080]


def test_missing_title_is_left_empty_not_invented(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """拿不到标题就留空,不编一个 —— 编出来的名字会跟着素材入库。"""
    _stub_master(monkeypatch, site)
    info = _parse(site, monkeypatch, _page(_media_script(), title=None))
    assert info["title"] == ""


def test_og_title_and_image_are_used_when_present(site, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_master(monkeypatch, site)
    page = _page(
        _media_script(),
        title=None,
        og_title="OG fixture title",
        og_image="https://media.example.test/offline-fixture/cover.jpg",
    )
    info = _parse(site, monkeypatch, page)

    assert info["title"] == "OG fixture title"
    assert info["thumbnail"] == "https://media.example.test/offline-fixture/cover.jpg"


# ---------------- ④ 坏页面:明确错误,不是崩溃、不是近似 ----------------


def test_page_without_packed_blocks_raises_a_clear_parse_error(site, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(errors.SiteAdapterError) as caught:
        _parse(site, monkeypatch, "<html><body>nothing here</body></html>")
    assert caught.value.key == "urlImportErr_siteParseFailed"


def test_page_with_packed_blocks_but_no_media_address_raises(site, monkeypatch: pytest.MonkeyPatch) -> None:
    no_media = _packed("source='https://media.example.test/offline-fixture/not-a-playlist';")
    with pytest.raises(errors.SiteAdapterError) as caught:
        _parse(site, monkeypatch, _page(no_media))
    assert caught.value.key == "urlImportErr_siteParseFailed"


def test_all_packed_blocks_undecodable_raises_a_distinct_error(site, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = "eval(function(p,a,c,k,e,d){throw new Error('broken m3u8')}('x'.split('|')))"
    with pytest.raises(errors.SiteAdapterError) as caught:
        _parse(site, monkeypatch, _page(broken))
    assert caught.value.key == "urlImportErr_siteScriptUndecodable"


def test_oversized_page_raises_a_distinct_error(site, monkeypatch: pytest.MonkeyPatch) -> None:
    """页面超过上限就停,不把整页读进内存、更不继续找地址。"""
    oversized = (site.MAX_PAGE_BYTES + 1) * b"x"

    def fake_request(self, url, video_id, note=None, headers=None, fatal=True):
        return _FakeResponse(oversized)

    monkeypatch.setattr(site.MissAVIE, "_request_webpage", fake_request)

    with pytest.raises(errors.SiteAdapterError) as caught:
        site.MissAVIE()._real_extract("https://missav123.com/cn/ssis-001")
    assert caught.value.key == "urlImportErr_sitePageTooLarge"
    assert caught.value.params["site"] == site.SITE_NAME


@pytest.mark.parametrize(
    "key",
    [
        "urlImportErr_siteParseFailed",
        "urlImportErr_siteScriptUndecodable",
        "urlImportErr_sitePageTooLarge",
    ],
)
def test_parse_errors_have_localized_messages_and_survive_classify(key: str) -> None:
    """适配器层不 import `media/ytdlp`;带 key 的错误由 `ytdlp.classify` 翻成给用户看的那句话。"""
    assert set(MESSAGES[key]) >= {"zh", "en"}
    error = errors.SiteAdapterError(key, site="MissAV", max_mb=8)
    assert ytdlp.classify(error).key == key


def test_site_adapter_pending_error_path_is_kept_for_future_adapters() -> None:
    """`SiteAdapterPending` 留着:别的适配器以后还会先认领、后写解析。"""
    pending = errors.SiteAdapterPending("Example")
    assert ytdlp.classify(pending).key == "urlImportErr_sitePending"
    assert ytdlp.classify(pending).params == {"site": "Example"}


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
