"""MissAV 的站点适配器骨架:**只认领,不解析**。

## 这一版能确定的事

- URL 的 scheme、hostname、path 都是看得见的:http(s)、镜像域名之一、视频详情页的路径形状。
  这些可以现在就写对,而且值得写对 —— 认错的代价是接管一个本来能下的链接,或者把一个下载
  失败说成「这个站还没支持」。
- **精确 hostname,不是字符串包含。** `missav.ws.evil.example`、`notmissav.ws`、`www.missav.ws`
  都不是同一个站;用 `"missav" in url` 判断会把它们全收进来。
- 分类页、搜索页、演员/片商索引页**明确拒绝**:它们也是同一个站,但页面上没有「这一条视频」。
  拒的是路径段本身(见 `_INDEX_SEGMENTS`),不是靠查询串猜。

## 这一版不能确定的事:页面里媒体地址长什么样

**没有写任何解析正则。** 真实页面的 `packed` 脚本、主 `source` 段长什么样,还没拿到样本;
猜一个正则的后果不是「解析失败」,而是解析出一个**看起来像**的地址 —— 下载时 403,或者下回来
一段不是视频的东西,而报错出现在离真正原因很远的地方。

所以认领之后、解析实现之前,唯一的回答是一句明确的「还没支持这个站」:带文案 key
(`urlImportErr_sitePending`)的 `YtdlpError`,出口按请求语言翻。**绝不返回近似地址。**

## 什么时候接进导入链路

`extractors/__init__.py` 的 `CUSTOM_EXTRACTORS` 现在是空的。等第二阶段能从真实页面里取出
媒体地址,把这个类加进去(一行),`/api/assets/url-support` 与下载会同时认到它。
在那之前登记它,只会让「支持」和「还没支持」这两句话同时出现在用户面前。

## 镜像域名

`MIRROR_HOSTS` 是**代码配置事实,不保证可用**:这类站点的域名会换。要加/换镜像,改这一处,
并把 `test_media_extractors.py` 的认领用例一起改 —— 不把它写进文档再让代码去读,是因为
域名不是一个部署配置项,而是「这个适配器认得谁」的定义。
"""
from __future__ import annotations

from typing import NoReturn
from urllib.parse import SplitResult, urlsplit

from yt_dlp.extractor.common import InfoExtractor

#: 站点的显示名。进错误文案与日志。
SITE_NAME = "MissAV"

#: 认这些 hostname(精确匹配,小写)。**配置事实,不保证可用**;换域名只改这一处。
MIRROR_HOSTS: tuple[str, ...] = (
    "missav.com",
    "missav.ws",
    "missav.ai",
    "missav.live",
)

#: 详情页可能带的语言前缀。认得出就认,认不出也不影响 `/ssis-001` 这种没有前缀的写法。
_LOCALES = frozenset({
    "en", "ja", "zh", "cn", "tw", "ko", "de", "fr", "es", "pt", "it", "ru", "th", "vi", "id", "ar",
    "hi", "tr", "nl", "pl", "sv", "cs",
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
    """视频代码的形状:`ssis-001`、`fc2-ppv-1234567`、`123456-789`。

    只做字符级的保守判断,不猜站点的编号规则:
    ASCII 字母数字与连字符,至少两段,最后一段是纯数字。`4k-videos` 这种栏目名会因为最后
    一段不是数字而被拒;`new` / `search` 这种没有连字符的也进不来。
    """
    if not 3 <= len(segment) <= 96:
        return False
    if segment.startswith("-") or segment.endswith("-") or "--" in segment:
        return False
    if not all(char.isascii() and (char.isalnum() or char == "-") for char in segment):
        return False
    parts = segment.split("-")
    return len(parts) >= 2 and parts[-1].isdigit()


def video_code(url: str) -> str | None:
    """这个 URL 是哪一条视频的详情页;不是就返回 `None`。

    返回的是站点自己的代码(小写),不是页面里的媒体地址 —— 媒体地址要等真实样本才能解析,
    这一版不碰。
    """
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


class MissAVIE(InfoExtractor):
    """yt-dlp 的适配器外壳:认领归 `video_code`,解析还没写。

    等第二阶段实现 `_real_extract`(从真实页面里取媒体地址与必需请求头)之后,把这个类加进
    `extractors.CUSTOM_EXTRACTORS`;工厂会自动让它先于 yt-dlp 默认被问到。
    """

    IE_NAME = "missav"
    #: 认领走我们自己的 URL parser,不注册 yt-dlp 的 `_VALID_URL` 正则。
    _VALID_URL = False

    @classmethod
    def suitable(cls, url: str) -> bool:
        return claims(url)

    def _real_extract(self, url: str) -> NoReturn:
        #: 认领了,但页面解析还没实现。**不返回近似地址** —— 说清是哪一步没做。
        raise _pending()


def _pending():
    """「已经认出这是 MissAV 的页面,但解析还没接入」。

    带的是 `SiteAdapterPending`,不是 `YtdlpError`:适配器层不该反向 import `media/ytdlp`
    (会形成包级循环)。`ytdlp.classify` 认得这个类型,把它翻成带 key 的那句话。
    """
    from app.media.extractors import SiteAdapterPending

    return SiteAdapterPending(SITE_NAME)
