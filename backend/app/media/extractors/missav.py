"""MissAV 的站点适配器:认领 + 页面解析。

## 认领(URL 层)

- 只认**精确 hostname**:`MIRROR_HOSTS` 是代码配置事实,不保证永远可用。
- 分类页、搜索页、演员/片商索引页拒绝;它们也是同一个站,但页面上没有「这一条视频」。
  拒的是路径段本身(见 `_INDEX_SEGMENTS`),不靠查询串猜。
- 视频代码的形状比「最后一段是数字」宽:服务器真实接受 `send-154-uncensored-leak`(数字段后有字母)
  与 `pondo-100524_001`(含下划线)。仍然拒绝 `fc2`、`chinese-subtitle`、`uncensored-leak`、
  `4k-videos`、`today-hot` 这类栏目名/短形状。

## 页面(实测 2026-10-19,来源:只读探测报告的脱敏样本)

- **必需浏览器 UA**:不带 UA 是 Cloudflare managed challenge(403)。Cookie 不需要;Referer 建议带。
- 页面里**没有字面 `.m3u8`**:地址在 Dean Edwards packer 块里。第 1 块一次 decode 就给出
  `source` / `source842` / `source1280`;第 2 块是四层嵌套的 host 白名单/跳转脚本,**不含媒体地址** ——
  所以只从解出的文本里取带 `.m3u8` 的地址,不猜、不拼。
- 媒体地址**取流必需一个本站 Referer**(`Referer: https://example.com/` 会 403);Origin、Cookie
  都不需要。地址目前没有 query、没有签名,但解析**不写死这一点** —— 签名串被截掉就是 403。
- `#EXT-X-TOKEN` 不塞进 URL:实测不带它也返回 206。分片是相对 URI、TS 伪装成 `.jpeg`
  (`content-type: image/jpeg`,首字节 `0x47`)—— 交给 yt-dlp 的 HLS 下载器,不自己判 content-type。

## 镜像域名

`missav123.com`(默认 `/cn/`)、`missav.live`(默认 `/en/`)实测可用,123 优先。
`missav.ai` / `missav.ws` 实测被 Cloudflare managed challenge 拦死(403),**不登记**:认领一个必然
403 的域名,只会把「不支持」变成一句更远的「取不到」。等有浏览器会话(能过 challenge)再加。
`missav.com` 是占位页,不是镜像。

## 坏页面

页面超过 `MAX_PAGE_BYTES`、没有 packed 块、packed 块一个都解不开、解出来没有媒体地址 —— 各给一条
明确的 `SiteAdapterError`(带文案 key)。**绝不返回近似地址**:猜一个「看起来像」的地址,下载时
403 或下回一段不是视频的东西,而报错出现在离真正原因很远的地方。
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import decode_packed_codes

from app.media.extractors.errors import SiteAdapterError

logger = logging.getLogger(__name__)

#: 站点的显示名。进错误文案与日志。
SITE_NAME = "MissAV"

#: 认这些 hostname(精确匹配,小写)。**配置事实,不保证可用**;换域名只改这一处。
#:
#: `missav.ai` / `missav.ws` 实测被 Cloudflare managed challenge 拦死(403),不放进来:
#: 认领了只会让导入走进一个必然失败的地址。等有能过 challenge 的浏览器会话再议。
MIRROR_HOSTS: tuple[str, ...] = (
    "missav123.com",
    "missav.live",
)

#: 详情页可能带的语言前缀。认得出就认,认不出也不影响 `/ssis-001` 这种没有前缀的写法。
_LOCALES = frozenset({
    "en", "ja", "zh", "cn", "tw", "ko", "de", "fr", "es", "pt", "it", "ru", "th", "vi", "id", "ar",
    "hi", "tr", "nl", "pl", "sv", "cs", "ms", "fil",
})

#: 这些路径段后面跟的不是「一条视频」:分类、搜索、演员、片商、索引页。
#: 只按**整段相等**拒(不按包含),`ssis-001-release` 这种代码不会被误伤。
_INDEX_SEGMENTS = frozenset({
    "about", "account", "actress", "actresses", "api", "assets", "best", "categories", "category",
    "channel", "channels", "contact", "dmca", "favorites", "feed", "genre", "genres", "history",
    "label", "labels", "login", "maker", "makers", "new", "playlist", "playlists", "popular",
    "premium", "privacy", "random", "ranking", "register", "release", "releases", "rss", "search",
    "series", "sitemap", "static", "studio", "studios", "tag", "tags", "terms", "top", "uncensored",
    "updates", "video", "videos",
})

#: 页面请求与取流共用的浏览器 UA。**必需**:不带 UA 的页面请求会落进 Cloudflare challenge(403)。
#: 取流同样用它 —— 站点按浏览器身份发流,拿库的默认 UA 反而不像真的播放器。
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

#: 页面体积上限。详情页实测几十 KB;超过这个数说明拿到的不是详情页(挑战页、错误页、被塞了别的东西),
#: 不把整页读进内存再解析。
MAX_PAGE_BYTES = 8 * 1024 * 1024

#: 按块读页面时每块的大小。
_PAGE_READ_CHUNK = 64 * 1024

#: 标准 Dean Edwards packer 的调用头。用正则是因为页面里可能夹着空白与换行。
_PACKED_START_RE = re.compile(
    r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)"
)

#: 一个 packed 块的结尾标记。`decode_packed_codes` 自己只认到 `.split('|')`。
_PACKED_END = ".split('|')"

#: `source` / `source842` / `source1280` 的赋值。引号在真实解码结果里是 `\'`(转义的),这里两种都收。
#: **地址捕获到引号为止**,所以 query 会原样保留;是否真的是 `.m3u8` 由 `_media_addresses` 看 path 判。
_ADDRESS_RE = re.compile(r"source(842|1280)?\s*=\s*\\?'(https://[^'\\]+)\\?'")

#: 额外的清晰度档:`source842` / `source1280` 是 720p / 1080p 的直连地址,不是 master 里的变体。
_EXTRA_FORMATS: tuple[tuple[str, str, int], ...] = (
    ("source842", "720p", 720),
    ("source1280", "1080p", 1080),
)

_TITLE_RE = re.compile(r"(?is)<title\b[^>]*>(.*?)</title>")
_META_RE = re.compile(r"(?is)<meta\b([^>]*)>")
_ATTR_RE = re.compile(r"""([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def _split(url: str) -> SplitResult | None:
    """这个 URL 能不能按「这个站的页面」来读。只做结构判断,不猜站点内容。"""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    # 带凭据的 URL 不认:地址里塞账号密码,不该被当成「某个人的视频页」。
    if parts.username or parts.password:
        return None
    if (parts.hostname or "").lower() not in MIRROR_HOSTS:
        return None
    try:
        port = parts.port
    except ValueError:  # 端口不是数字
        return None
    # 只认默认端口。非默认端口上的同名 host 不一定是同一个站(也可能是本机反代)。
    if port not in (None, 80, 443):
        return None
    path = parts.path
    if not path.startswith("/") or "//" in path or "\\" in path or "%" in path:
        return None
    return parts


def _is_route_prefix(segment: str) -> bool:
    """`dm12` 这种详情页路由前缀(不是视频代码)。"""
    return len(segment) > 2 and segment[:2].lower() == "dm" and segment[2:].isdigit()


def _is_video_code(segment: str) -> bool:
    """视频代码的形状:`ssis-001`、`fc2-ppv-1234567`、`send-154-uncensored-leak`、`pondo-100524_001`。

    只做字符级的保守判断,不猜站点的编号规则:

    - 字符集 `[a-z0-9_]`(大小写不敏感);
    - 至少两段(`-` 分隔);
    - **至少一段含 3 个以上数字** —— 这是「它是一条编号」与「它是栏目名」的分界:
      `chinese-subtitle` / `uncensored-leak` / `4k-videos` / `today-hot` 都没有这样的数字段。
    """
    if not 3 <= len(segment) <= 96:
        return False
    if segment.startswith(("-", "_")) or segment.endswith(("-", "_")) or "--" in segment or "__" in segment:
        return False
    if not all(char.isascii() and (char.isalnum() or char in "-_") for char in segment):
        return False
    parts = segment.split("-")
    if len(parts) < 2:
        return False
    return any(sum(char.isdigit() for char in part) >= 3 for part in parts)


def video_code(url: str) -> str | None:
    """这个 URL 是哪一条视频的详情页;不是就返回 `None`(小写的站点代码)。"""
    parts = _split(url)
    if parts is None:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if not 1 <= len(segments) <= 3:
        return None
    if any(segment.lower() in _INDEX_SEGMENTS for segment in segments):
        return None

    index = 0
    if _is_route_prefix(segments[index]):
        index += 1
    # 语言前缀是**可选**的:详情页可能写成 /en/ssis-001,也可能只有 /ssis-001。
    if index < len(segments) - 1:
        if segments[index].lower() not in _LOCALES:
            return None
        index += 1
    if index != len(segments) - 1:
        return None

    code = segments[index]
    return code.lower() if _is_video_code(code) else None


def claims(url: str) -> bool:
    """这个 URL 是不是本站的视频详情页。**只看结构,不猜页面内容。**"""
    return video_code(url) is not None


def _request_headers(host: str) -> dict[str, str]:
    """页面与取流都需要的两个头。UA 少了是 403 challenge,Referer 少了媒体 403。"""
    return {
        "User-Agent": _BROWSER_USER_AGENT,
        "Referer": f"https://{host}/",
    }


def _detail_page(url: str, code: str) -> str:
    """稳定详情页:去掉 `dm<数字>` 路由前缀、查询串与尾斜杠,保留语言前缀。"""
    parts = _split(url)
    host = (parts.hostname or "").lower() if parts is not None else ""
    segments = [segment for segment in (parts.path.split("/") if parts is not None else []) if segment]
    if segments and _is_route_prefix(segments[0]):
        segments = segments[1:]
    if segments and segments[-1].lower() == code:
        segments = segments[:-1]
    return "https://" + host + "/" + "/".join([*segments, code])


def _packed_blocks(page: str) -> list[str]:
    """页面里每一个完整的 packed 块。

    **坏块不能吞掉后面的好块。** 真实页面里两块脚本并存;如果第一块的结尾标记缺失,
    直接 `find` 到第二块的结尾就会把两块粘成一个解不开的块。所以发现「下一个块的起点在本次
    结尾之前」时,跳过这一块、从下一块重新开始。
    """
    blocks: list[str] = []
    position = 0
    while (start := _PACKED_START_RE.search(page, position)) is not None:
        end = page.find(_PACKED_END, start.end())
        if end < 0:
            position = start.end()
            continue
        later = _PACKED_START_RE.search(page, start.end())
        if later is not None and later.start() < end:
            position = later.start()
            continue
        end += len(_PACKED_END)
        blocks.append(page[start.start():end])
        position = end
    return blocks


def _decode_blocks(blocks: list[str]) -> list[str]:
    """逐个解;解不动的那一块只跳过它自己,不拖垮整页。"""
    decoded: list[str] = []
    for block in blocks:
        try:
            decoded.append(decode_packed_codes(block))
        except Exception:  # noqa: BLE001 — 一块脚本的格式坏了,不该让整条导入失败
            logger.debug("MissAV: skipping a packed block that could not be decoded", exc_info=True)
    return decoded


def _looks_like_media_script(block: str) -> bool:
    """这一块**可能**含媒体地址吗。

    真实页面的第二块是四层嵌套的 host 白名单/跳转脚本,解一层也只会得到更多脚本 —— 逐块 `decode`
    它没有意义。packer 的符号表是明文,所以 `source` / `m3u8` 这两个词在原始块里就看得见;两块都
    没有的,直接跳过。**只是省一层解码,不据此猜地址。**
    """
    return "source" in block or "m3u8" in block


def _media_addresses(decoded: str) -> dict[str, str]:
    """解出的文本里 `source` / `source842` / `source1280` 的地址。

    只收 path 以 `.m3u8` 结尾的 `https://` 地址;query 原样保留。同一个键出现多次时取第一个。
    """
    found: dict[str, str] = {}
    for match in _ADDRESS_RE.finditer(decoded):
        key = f"source{match.group(1)}" if match.group(1) else "source"
        address = match.group(2)
        try:
            path = urlsplit(address).path
        except ValueError:
            continue
        if not path.lower().endswith(".m3u8"):
            continue
        found.setdefault(key, address)
    return found


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _meta_content(page: str, name: str) -> str:
    """`<meta property|name="<name>" content="...">` 的 content,属性顺序不限。"""
    for match in _META_RE.finditer(page):
        attributes: dict[str, str] = {}
        for attr in _ATTR_RE.finditer(match.group(1)):
            key = attr.group(1).lower()
            value = next((group for group in attr.groups()[1:] if group is not None), "")
            attributes.setdefault(key, value)
        if name in (attributes.get("property", "").lower(), attributes.get("name", "").lower()):
            return _clean(attributes.get("content"))
    return ""


def _title(page: str) -> str:
    """`<title>` 或 `og:title`;都拿不到就空着 —— 编一个名字会跟着素材入库。"""
    match = _TITLE_RE.search(page)
    title = _clean(match.group(1)) if match else ""
    return title or _meta_content(page, "og:title")


def _thumbnail(page: str, host: str) -> str:
    image = _meta_content(page, "og:image")
    return urljoin(f"https://{host}/", image) if image else ""


class MissAVIE(InfoExtractor):
    """yt-dlp 的适配器:认领归 `video_code`,解析走 `_real_extract`。

    已登记进 `extractors.CUSTOM_EXTRACTORS`:工厂与 `/api/assets/url-support` 从同一份集合出发,
    所以「说支持」与「真去下载」走的是同一个适配器。
    """

    IE_NAME = "missav"
    #: 认领走我们自己的 URL parser,不注册 yt-dlp 的 `_VALID_URL` 正则。
    _VALID_URL = False

    @classmethod
    def suitable(cls, url: str) -> bool:
        return claims(url)

    def _fetch_page(self, url: str, video_id: str, host: str) -> str:
        """取详情页,但**先按上限读字节再解码**。

        不用 `_download_webpage` 是因为它把整页读进内存之后才交回来 —— 遇到一个异常大的响应
        (挑战页、错误页)时,限制已经来不及了。这里读满 `MAX_PAGE_BYTES + 1` 就停。
        """
        headers = _request_headers(host)
        response = self._request_webpage(url, video_id, note="Downloading page", headers=headers, fatal=True)
        if response is False:  # pragma: no cover - fatal=True 时不会走到
            raise SiteAdapterError("urlImportErr_siteParseFailed", site=SITE_NAME)
        try:
            chunks: list[bytes] = []
            total = 0
            while total <= MAX_PAGE_BYTES:
                chunk = response.read(min(_PAGE_READ_CHUNK, MAX_PAGE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        finally:
            response.close()

        body = b"".join(chunks)
        if len(body) > MAX_PAGE_BYTES:
            raise SiteAdapterError(
                "urlImportErr_sitePageTooLarge",
                site=SITE_NAME,
                max_mb=MAX_PAGE_BYTES // (1024 * 1024),
            )
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            return body.decode(charset, errors="replace").lstrip("\ufeff")
        except LookupError:  # 站点报了一个不认识的 charset
            return body.decode("utf-8", errors="replace").lstrip("\ufeff")

    def _real_extract(self, url: str) -> dict[str, Any]:
        code = video_code(url)
        if code is None:
            # 认领与解析的分界:被工厂问到时 suitable() 已经答过是详情页;这里只做兜底。
            raise SiteAdapterError("urlImportErr_unsupported")
        parts = _split(url)
        host = (parts.hostname or "").lower() if parts is not None else ""

        page = self._fetch_page(url, code, host)
        blocks = _packed_blocks(page)
        #: 只解**可能含媒体地址**的块:第二块是 host 白名单/跳转脚本,解它没有意义。
        media_blocks = [block for block in blocks if _looks_like_media_script(block)]
        if not media_blocks:
            raise SiteAdapterError("urlImportErr_siteParseFailed", site=SITE_NAME)
        decoded = _decode_blocks(media_blocks)
        if not decoded:
            raise SiteAdapterError("urlImportErr_siteScriptUndecodable", site=SITE_NAME)

        addresses: dict[str, str] = {}
        for text in decoded:
            for key, address in _media_addresses(text).items():
                addresses.setdefault(key, address)
        if not addresses:
            raise SiteAdapterError("urlImportErr_siteParseFailed", site=SITE_NAME)

        headers = _request_headers(host)
        formats: list[dict[str, Any]] = []
        subtitles: dict[str, Any] = {}
        master = addresses.get("source")
        if master:
            master_formats, master_subtitles = self._extract_m3u8_formats_and_subtitles(
                master, code, "mp4", entry_protocol="m3u8_native", headers=dict(headers),
            )
            formats.extend(master_formats)
            subtitles.update(master_subtitles)

        #: 720p / 1080p 是页面直接给的整档地址,不在 master 的变体列表里 —— 作为额外 format 留给用户选。
        for key, note, height in _EXTRA_FORMATS:
            address = addresses.get(key)
            if not address:
                continue
            formats.append({
                "format_id": f"hls-{note}",
                "url": address,
                "ext": "mp4",
                "protocol": "m3u8_native",
                "height": height,
                "format_note": note,
                "http_headers": dict(headers),
            })

        if not formats:
            # 地址有、但 master 解析不出任何格式:仍然是「取不到」,不是「返回一个空清单」。
            raise SiteAdapterError("urlImportErr_siteParseFailed", site=SITE_NAME)

        #: **每一档**都要带 Referer 与 UA。master 解析出来的 format 也补一遍 —— 取流时漏了就是 403。
        for format_ in formats:
            format_headers = dict(format_.get("http_headers") or {})
            format_headers.update(headers)
            format_["http_headers"] = format_headers

        info: dict[str, Any] = {
            "id": code,
            "title": _title(page),
            "webpage_url": _detail_page(url, code),
            "formats": formats,
            "http_headers": headers,
        }
        if subtitles:
            info["subtitles"] = subtitles
        thumbnail = _thumbnail(page, host)
        if thumbnail:
            info["thumbnail"] = thumbnail
        return info
