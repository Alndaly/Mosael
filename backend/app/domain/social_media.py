"""自媒体数据:认链接、把各平台取回来的作品 / 评论整理成同一个形状、算运营指标。

分析类官方模板(templates_analysis)的两条取数路 —— TikHub 插件和内嵌浏览器 —— 交回来的东西长得完全不一样:

- TikHub 走 MCP,回的是它**自己裁过的投影**,字段名跟着平台走(抖音 `statistics.digg_count`、
  B 站 `play` / `created`、小红书 `liked_count`),投影的形状还会随服务端升级变;
- 浏览器那一路是页面文字经模型整理出来的 JSON,数字常常是「1.2万」这种写法,发布时间可能缺。

所以这里**不写死路径**,而是按「这个值通常叫什么」在每一项里找(别名表,浅的优先),数字和时间按常见写法
宽容地解析。找不到的字段就是缺,缺了照样算 —— 指标只在有数据的那几条上算,并且说清哪几项缺了,
而不是拿 0 冒充数据。算术交给代码,不交给模型:三十条作品的发布间隔中位数、按小时分布,模型心算是会错的。
"""

from __future__ import annotations

import html
import json
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from app.core.i18n import get_current_locale, t

# --------------------------------------------------------------------------------------
# 链接
# --------------------------------------------------------------------------------------

#: 平台的规范名 → 人会怎么写它。规范名和 TikHub 插件连接的平台取值一致(douyin / xiaohongshu / bilibili …)。
PLATFORM_ALIASES: dict[str, tuple[str, ...]] = {
    "douyin": ("douyin", "抖音", "dy"),
    "xiaohongshu": ("xiaohongshu", "小红书", "xhs", "rednote", "红书"),
    "bilibili": ("bilibili", "b站", "哔哩哔哩", "bili", "b"),
    "kuaishou": ("kuaishou", "快手", "ks"),
    "tiktok": ("tiktok", "tt"),
    "weibo": ("weibo", "微博"),
    "youtube": ("youtube", "油管", "yt"),
}

#: 认平台用的域名(后缀匹配)。
_HOSTS: dict[str, tuple[str, ...]] = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "kuaishou": ("kuaishou.com", "chenzhongtech.com"),
    "tiktok": ("tiktok.com",),
    "weibo": ("weibo.com", "weibo.cn"),
    "youtube": ("youtube.com", "youtu.be"),
}

#: App 里「分享」复制出来的是短链。短链里没有作品 / 账号的编号,要跟一次跳转才知道指向哪儿。
#: **只请求这几个域名**:跳转链上一旦出现别的主机就停 —— 这一步不是通用的抓网页。
SHORT_LINK_HOSTS = ("v.douyin.com", "xhslink.com", "b23.tv", "v.kuaishou.com", "vm.tiktok.com", "vt.tiktok.com")

ACCOUNT = "account"
VIDEO = "video"

#: 从链接里抠编号:(平台, 种类, 正则)。按顺序试,第一条命中的说了算。
_ID_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("douyin", ACCOUNT, r"(?:douyin\.com/user/|/share/user/|sec_uid=)(MS4wLj[\w-]+)"),
    ("douyin", VIDEO, r"(?:douyin\.com/(?:video|note)/|/share/(?:video|note)/|modal_id=|aweme_id=)(\d{8,})"),
    ("xiaohongshu", ACCOUNT, r"xiaohongshu\.com/user/profile/([0-9a-f]{24})"),
    ("xiaohongshu", VIDEO, r"xiaohongshu\.com/(?:explore|discovery/item|note)/([0-9a-f]{24})"),
    ("bilibili", ACCOUNT, r"space\.bilibili\.com/(\d+)"),
    ("bilibili", VIDEO, r"(BV[0-9A-Za-z]{10})"),
    ("kuaishou", ACCOUNT, r"kuaishou\.com/profile/([\w-]+)"),
    ("kuaishou", VIDEO, r"kuaishou\.com/(?:short-video|fw/photo)/([\w-]+)"),
    ("tiktok", VIDEO, r"tiktok\.com/@[\w.-]+/video/(\d+)"),
    ("tiktok", ACCOUNT, r"tiktok\.com/@([\w.-]+)"),
)

_URL_RE = re.compile(r"https?://[^\s\"'<>，。！？、；（）【】《》()\[\]{}]+", re.IGNORECASE)
#: 没带 http 的链接(「www.douyin.com/user/…」「space.bilibili.com/123」)。
_BARE_URL_RE = re.compile(r"(?<![\w.])((?:[\w-]+\.)+(?:com|cn|tv|be)/[^\s\"'<>，。！？、；（）【】《》()\[\]{}]*)", re.IGNORECASE)


@dataclass(frozen=True)
class SocialLink:
    platform: str
    kind: str
    id: str
    url: str


def platform_of(text: str) -> str:
    """「抖音」「XHS」「B站」→ 规范名;认不出是空串。"""
    lowered = str(text or "").strip().lower()
    if not lowered or lowered == "auto":
        return ""
    for name, aliases in PLATFORM_ALIASES.items():
        if lowered in aliases:
            return name
    return ""


def _host_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for name, hosts in _HOSTS.items():
        if any(host == one or host.endswith("." + one) for one in hosts):
            return name
    return ""


def _first_url(text: str) -> str:
    """分享口令里的那条链接(「7.43 复制打开抖音,看看【某某的作品】… https://v.douyin.com/xx/ …」)。"""
    found = _URL_RE.search(text)
    if found:
        return found.group(0).rstrip(".,;:!?)")
    bare = _BARE_URL_RE.search(text)
    return f"https://{bare.group(1).rstrip('.,;:!?)')}" if bare else ""


def _is_short_link(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in SHORT_LINK_HOSTS


def resolve_short_link(url: str) -> str:
    """跟短链的跳转,直到落到一个不是短链的地址。取不到(断网、被拦)就原样交回 —— 浏览器那一路照样能打开短链,
    TikHub 的几个工具也收分享链接;没跟成功只是少了一个编号。"""
    import httpx

    current = url
    try:
        with httpx.Client(timeout=8, follow_redirects=False, headers={"User-Agent": _MOBILE_UA}) as client:
            for _ in range(5):
                if not _is_short_link(current):
                    break
                response = client.get(current)
                location = response.headers.get("location") if response.is_redirect else None
                if not location:
                    break
                current = urljoin(current, location)
    except Exception:  # noqa: BLE001 — 跟不到跳转只是少一个编号,不是这一步的失败
        return url
    return current


_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def _ids_in(url: str) -> tuple[str, str, str]:
    """(平台, 种类, 编号);抠不出来是空串。"""
    for platform, kind, pattern in _ID_PATTERNS:
        found = re.search(pattern, url)
        if found:
            return platform, kind, found.group(1)
    return "", "", ""


def _from_bare_id(text: str, platform: str, expect: str) -> SocialLink | None:
    """只给了一个编号(没有链接):按平台和期望的种类拼出主页 / 作品链接。"""
    value = text.strip().lstrip("@")
    if platform == "douyin" and value.startswith("MS4wLj"):
        return SocialLink("douyin", ACCOUNT, value, f"https://www.douyin.com/user/{value}")
    if platform == "douyin" and value.isdigit():
        return SocialLink("douyin", VIDEO, value, f"https://www.douyin.com/video/{value}")
    if platform == "bilibili" and re.fullmatch(r"BV[0-9A-Za-z]{10}", value):
        return SocialLink("bilibili", VIDEO, value, f"https://www.bilibili.com/video/{value}")
    if platform == "bilibili" and value.isdigit():
        return SocialLink("bilibili", ACCOUNT, value, f"https://space.bilibili.com/{value}")
    if platform == "xiaohongshu" and re.fullmatch(r"[0-9a-f]{24}", value):
        if expect == VIDEO:
            return SocialLink("xiaohongshu", VIDEO, value, f"https://www.xiaohongshu.com/explore/{value}")
        return SocialLink("xiaohongshu", ACCOUNT, value, f"https://www.xiaohongshu.com/user/profile/{value}")
    return None


def parse_link(
    text: str, *, platform: str = "", expect: str = "", resolve: Callable[[str], str] | None = None
) -> SocialLink:
    """一段用户贴进来的东西(链接、分享口令、编号)→ 平台、种类、编号、能打开的链接。

    `platform` 是用户说的平台(可空,空就按域名认);`expect` 是模板要的种类(account / video),
    只在光给编号、分不出是主页还是作品时用。认不出平台时 platform 为空 —— 调用方据此决定走不走得通。
    """
    raw = str(text or "").strip()
    hinted = platform_of(platform)
    url = _first_url(raw)
    if not url:
        bare = _from_bare_id(raw, hinted, expect) if hinted else None
        return bare or SocialLink(hinted, "", "", "")
    if _is_short_link(url):
        url = (resolve or resolve_short_link)(url)
    found_platform, kind, found_id = _ids_in(url)
    return SocialLink(hinted or found_platform or _host_platform(url), kind, found_id, url)


# --------------------------------------------------------------------------------------
# 数字、时间
# --------------------------------------------------------------------------------------

_UNITS = {"万": 1e4, "w": 1e4, "亿": 1e8, "k": 1e3, "千": 1e3, "m": 1e6}


def parse_count(value: Any) -> float | None:
    """「1.2万」「3.5w」「12k」「1,234」「10万+」→ 数;不是数就 None。布尔不算数。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value and value >= 0 else None
    text = str(value).strip().lower().replace(",", "").replace("+", "").replace(" ", "")
    if not text:
        return None
    found = re.fullmatch(r"(\d+(?:\.\d+)?)(万|w|亿|k|千|m)?", text)
    if not found:
        return None
    return float(found.group(1)) * _UNITS.get(found.group(2) or "", 1.0)


def parse_seconds(value: Any, unit: str = "auto") -> float | None:
    """时长 → 秒。「03:21」「1:02:03」按钟表读;数字按 unit(milliseconds / seconds),auto 时超过十小时的当毫秒。"""
    if isinstance(value, str) and ":" in value:
        parts = value.strip().split(":")
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return None
        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number
        return seconds
    number = parse_count(value)
    if number is None or number <= 0:
        return None
    if unit == "milliseconds" or (unit == "auto" and number > 36_000):
        return number / 1000
    return number


def parse_time(value: Any, offset_hours: float = 8.0) -> datetime | None:
    """发布时间 → 带时区的时刻。认时间戳(秒 / 毫秒)和常见的日期写法;没写时区的按 offset_hours 那个时区读。"""
    if isinstance(value, bool) or value is None or value == "":
        return None
    tz = timezone(timedelta(hours=offset_hours))
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}(?:\.\d+)?", value.strip())):
        stamp = float(value)
        if stamp > 1e12:
            stamp /= 1000
        if stamp < 1e9:
            return None
        return datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(tz)
    text = str(value).strip().replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
    text = re.sub(r"\s+", " ", text)
    #: 「2026-9-3」补成「2026-09-03」:fromisoformat 只认补过零的写法。
    text = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


# --------------------------------------------------------------------------------------
# 在一堆 JSON 里找东西
# --------------------------------------------------------------------------------------

#: 规范字段 → 各平台、各接口里通常叫什么。**顺序就是偏好**(同样浅的时候先认前面的)。
POST_FIELDS: dict[str, tuple[str, ...]] = {
    "id": ("aweme_id", "note_id", "bvid", "bv_id", "photo_id", "item_id", "id", "aid"),
    "title": ("title", "display_title", "desc", "caption", "content", "description"),
    "published_at": ("published_at", "create_time", "publish_time", "created", "pubdate", "ctime", "time",
                     "timestamp", "last_update_time"),
    "duration": ("duration_seconds", "duration_ms", "duration", "length", "video_duration"),
    "views": ("views", "play_count", "view_count", "play", "view", "vv", "read_count"),
    "likes": ("likes", "digg_count", "like_count", "liked_count", "like", "liked"),
    "comments": ("comments", "comment_count", "comments_count", "comment", "reply"),
    "collects": ("collects", "collect_count", "collected_count", "favorite", "favorites", "fav_count"),
    "shares": ("shares", "share_count", "shared_count", "share", "forward_count"),
    "url": ("url", "share_url", "link", "arcurl"),
    "pinned": ("pinned", "is_top", "sticky"),
}
COUNT_FIELDS = ("views", "likes", "comments", "collects", "shares")

COMMENT_FIELDS: dict[str, tuple[str, ...]] = {
    "text": ("text", "content", "message", "comment"),
    "likes": ("likes", "digg_count", "like_count", "like", "liked_count"),
    "replies": ("replies", "reply_comment_total", "reply_count", "sub_comment_count", "rcount"),
    "author": ("author", "nickname", "uname", "user_name", "name"),
    "published_at": ("published_at", "create_time", "ctime", "time"),
}

ACCOUNT_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("name", "nickname", "uname", "user_name", "nick_name"),
    "handle": ("handle", "unique_id", "short_id", "red_id", "mid", "uid"),
    "bio": ("bio", "signature", "sign", "desc", "description"),
    "followers": ("followers", "follower_count", "fans", "fans_count", "mplatform_followers_count", "follower"),
    "following": ("following", "following_count", "follows", "attention"),
    "likes_total": ("likes_total", "total_favorited", "liked_count", "interaction", "likes"),
    "posts_total": ("posts_total", "aweme_count", "notes", "note_count", "video_count", "archive_count"),
}

#: 一个对象像不像一条作品 / 一条评论:带着这一类的编号,或者(连同下一层)至少有两个这一类的字段。
#: 编号分开列:抖音作品自己也带点赞数,只按「有点赞、有文字」认的话,一条作品也像一条评论。
_POST_IDS = {"aweme_id", "note_id", "bvid"}
_POST_MARKERS = {"digg_count", "liked_count", "play", "statistics", "interact_info", "title", "desc", "display_title",
                 "likes", "views", "create_time", "published_at"}
_COMMENT_IDS = {"cid", "rpid", "comment_id"}
_COMMENT_MARKERS = {"text", "content", "message", "like_count", "digg_count", "like", "likes", "sub_comment_count",
                    "reply_comment_total", "rcount", "author"}

_MAX_NODES = 20_000


def _decoded(value: Any, depth: int = 0) -> Any:
    """一段写成文字的 JSON 解开(FastMCP 把非对象返回值包成 `{"result": "<JSON 文本>"}`)。"""
    if depth < 3 and isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return _decoded(json.loads(stripped), depth + 1)
            except ValueError:
                return value
    return value


def _walk(value: Any) -> list[Any]:
    """广度优先列出所有对象和列表(浅的在前)。写成文字的 JSON 顺手解开。"""
    out: list[Any] = []
    queue = [_decoded(value)]
    while queue and len(out) < _MAX_NODES:
        current = queue.pop(0)
        if isinstance(current, dict):
            out.append(current)
            queue.extend(_decoded(one) for one in current.values() if isinstance(one, (dict, list, str)))
        elif isinstance(current, list):
            out.append(current)
            queue.extend(_decoded(one) for one in current if isinstance(one, (dict, list, str)))
        #: 解不开的文字(普通的标题、简介)不往下走。
    return out


def _looks_like(item: Any, kind: str) -> bool:
    if not isinstance(item, dict):
        return False
    ids, markers = (_COMMENT_IDS, _COMMENT_MARKERS) if kind == "comments" else (_POST_IDS, _POST_MARKERS)
    keys = set(item)
    for nested in item.values():
        if isinstance(nested, dict):
            keys |= set(nested)
    return bool(set(item) & ids) or len(keys & markers) >= 2


def find_items(data: Any, *, kind: str) -> list[dict[str, Any]]:
    """数据里那一串作品(或评论)。是一串就取最像的那一串;只有一条(作品详情)就把那一条当一串。"""
    best: list[dict[str, Any]] = []
    best_score = 0.0
    single: dict[str, Any] | None = None
    for node in _walk(data):
        if isinstance(node, list):
            items = [one for one in (_decoded(x) for x in node) if isinstance(one, dict)]
            hits = sum(1 for one in items if _looks_like(one, kind))
            if hits and hits >= len(items) / 2 and hits > best_score:
                best, best_score = items, hits
        elif single is None and _looks_like(node, kind):
            single = node
    if best:
        return best
    return [single] if single is not None else []


def _leaves(item: dict[str, Any], max_depth: int = 4) -> dict[str, tuple[int, Any]]:
    """一项里所有的标量值:键 → (多深, 值)。同名的取最浅的那个。"""
    found: dict[str, tuple[int, Any]] = {}
    queue: list[tuple[int, Any]] = [(0, item)]
    while queue:
        depth, current = queue.pop(0)
        if not isinstance(current, dict):
            continue
        for key, value in current.items():
            value = _decoded(value)
            if isinstance(value, dict):
                if depth < max_depth:
                    queue.append((depth + 1, value))
            elif not isinstance(value, list) and key not in found:
                found[str(key)] = (depth, value)
    return found


def _pick(leaves: dict[str, tuple[int, Any]], aliases: tuple[str, ...], accept: Callable[[Any], bool]) -> tuple[str, Any]:
    """按别名取一个值:最浅的优先,一样浅的按别名的先后。返回 (命中的键, 值);没有就 ("", None)。"""
    best: tuple[int, int, str, Any] | None = None
    for order, alias in enumerate(aliases):
        hit = leaves.get(alias)
        if hit is None or not accept(hit[1]):
            continue
        candidate = (hit[0], order, alias, hit[1])
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return (best[2], best[3]) if best else ("", None)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_count(value: Any) -> bool:
    return parse_count(value) is not None


def normalize_post(item: dict[str, Any], *, duration_unit: str = "auto", offset_hours: float = 8.0) -> dict[str, Any]:
    leaves = _leaves(item)
    out: dict[str, Any] = {}
    _, raw_id = _pick(leaves, POST_FIELDS["id"], lambda v: _is_text(v) or isinstance(v, int) and not isinstance(v, bool))
    out["id"] = str(raw_id) if raw_id is not None else ""
    _, title = _pick(leaves, POST_FIELDS["title"], _is_text)
    out["title"] = str(title or "").strip()
    _, published = _pick(leaves, POST_FIELDS["published_at"], lambda v: parse_time(v, offset_hours) is not None)
    when = parse_time(published, offset_hours) if published is not None else None
    out["published_at"] = when.isoformat(timespec="minutes") if when else None
    key, duration = _pick(leaves, POST_FIELDS["duration"], lambda v: parse_seconds(v) is not None)
    unit = {"duration_ms": "milliseconds", "duration_seconds": "seconds"}.get(key, duration_unit)
    out["duration_seconds"] = round(parse_seconds(duration, unit), 1) if duration is not None else None
    for field in COUNT_FIELDS:
        _, count = _pick(leaves, POST_FIELDS[field], _is_count)
        out[field] = int(parse_count(count)) if count is not None else None
    #: 抖音网页接口的播放数一律是 0(平台不公开)—— 有点赞却没有播放,说明这个数是"不给",不是"没人看"。
    if out["views"] == 0 and (out["likes"] or 0) > 0:
        out["views"] = None
    _, url = _pick(leaves, POST_FIELDS["url"], lambda v: _is_text(v) and str(v).startswith("http"))
    out["url"] = str(url or "")
    _, pinned = _pick(leaves, POST_FIELDS["pinned"], lambda v: v not in (None, ""))
    out["pinned"] = str(pinned).strip().lower() in ("1", "true", "yes") if pinned is not None else False
    #: 互动以点赞为主体:点赞都没有(B 站主页列表只给播放和评论)时不凑一个只含评论数的「互动」,
    #: 那会让互动率低得离谱、头部作品排错。
    known = [out[field] for field in ("likes", "comments", "collects", "shares") if out[field] is not None]
    out["interactions"] = sum(known) if out["likes"] is not None else None
    out["engagement_rate"] = (
        round(out["interactions"] / out["views"], 4) if out["interactions"] is not None and out["views"] else None
    )
    return out


def normalize_comment(item: dict[str, Any], *, offset_hours: float = 8.0, html_escaped: bool = False) -> dict[str, Any]:
    """一条评论 → 统一的形状。`html_escaped`:这份数据的文字做过 HTML 转义(B 站评论接口交回的原文就是,
    「'」写成 &#39;),解**一次** —— 用户自己打的「&#39;」那几个字接口交回 &amp;#39;,解一次才是他写的原样。
    没转义的来源(抖音、小红书、页面上读到的文字)不能解:用户写的「&lt;3」就是这四个字。"""
    leaves = _leaves(item)
    _, text = _pick(leaves, COMMENT_FIELDS["text"], _is_text)
    _, likes = _pick(leaves, COMMENT_FIELDS["likes"], _is_count)
    _, replies = _pick(leaves, COMMENT_FIELDS["replies"], _is_count)
    _, author = _pick(leaves, COMMENT_FIELDS["author"], _is_text)
    _, published = _pick(leaves, COMMENT_FIELDS["published_at"], lambda v: parse_time(v, offset_hours) is not None)
    when = parse_time(published, offset_hours) if published is not None else None
    original = html.unescape if html_escaped else str
    return {
        "text": original(str(text or "")).strip(),
        "likes": int(parse_count(likes)) if likes is not None else None,
        "replies": int(parse_count(replies)) if replies is not None else None,
        "author": original(str(author or "")).strip(),
        "published_at": when.isoformat(timespec="minutes") if when else None,
    }


def normalize_account(data: Any) -> dict[str, Any]:
    """账号资料:找最像「用户」的那个对象,按别名取几项。什么都没给就是空对象。"""
    data = _decoded(data)
    if not isinstance(data, (dict, list)):
        return {}
    candidates = [node for node in _walk(data) if isinstance(node, dict)]
    best: dict[str, Any] = {}
    best_hits = 0
    for node in candidates:
        leaves = _leaves(node, max_depth=1)
        hits = sum(1 for aliases in ACCOUNT_FIELDS.values() if any(alias in leaves for alias in aliases))
        if hits > best_hits:
            best, best_hits = node, hits
    if not best:
        return {}
    leaves = _leaves(best, max_depth=2)
    out: dict[str, Any] = {}
    for field, aliases in ACCOUNT_FIELDS.items():
        if field in ("followers", "following", "likes_total", "posts_total"):
            _, value = _pick(leaves, aliases, _is_count)
            out[field] = int(parse_count(value)) if value is not None else None
        else:
            _, value = _pick(leaves, aliases, lambda v: _is_text(v) or isinstance(v, int) and not isinstance(v, bool))
            out[field] = str(value).strip() if value is not None else ""
    return out


# --------------------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------------------

#: 少于这么多条带时间的作品,不谈「最近变好 / 变差」—— 两三条的对比只是噪声。
TREND_MIN_POSTS = 6
#: 最近一半比之前一半高出 / 低于这个倍数,才算信号。
TREND_UP, TREND_DOWN = 1.3, 0.7
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
#: 时段:凌晨 0–6、上午 6–12、下午 12–18、晚上 18–24。
_DAYPARTS = (("night", 0, 6), ("morning", 6, 12), ("afternoon", 12, 18), ("evening", 18, 24))
_DURATION_BUCKETS = (("lt15", 0, 15), ("s15to60", 15, 60), ("m1to3", 60, 180), ("m3to10", 180, 600), ("gt10", 600, 1e12))


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _mean(values: list[float]) -> float | None:
    return float(statistics.fmean(values)) if values else None


def post_stats(posts: list[dict[str, Any]], *, account: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """一串规范化过的作品(新的在前)→ 运营指标。每一项都只在有数据的作品上算,缺的写 None。"""
    account = account or {}
    timed = sorted((p for p in posts if p.get("published_at")), key=lambda p: p["published_at"])
    times = [datetime.fromisoformat(p["published_at"]) for p in timed]
    stats: dict[str, Any] = {"count": len(posts), "with_time": len(times)}

    if times:
        reference = now or datetime.now(times[-1].tzinfo)
        span = max((times[-1] - times[0]).total_seconds() / 86400, 0.0)
        gaps = [(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:])]
        stats.update(
            first_post=times[0].date().isoformat(),
            last_post=times[-1].date().isoformat(),
            span_days=round(span, 1),
            days_since_last=round(max((reference - times[-1]).total_seconds() / 86400, 0.0), 1),
            posts_per_week=round(len(times) / max(span, 1.0) * 7, 2) if len(times) >= 2 else None,
            median_gap_days=round(_median(gaps), 1) if gaps else None,
            longest_gap_days=round(max(gaps), 1) if gaps else None,
            weekdays={day: sum(1 for one in times if one.weekday() == index) for index, day in enumerate(_WEEKDAYS)},
            dayparts={name: sum(1 for one in times if low <= one.hour < high) for name, low, high in _DAYPARTS},
            top_hours=_top_hours(times),
        )

    for field in (*COUNT_FIELDS, "interactions"):
        values = [float(p[field]) for p in posts if p.get(field) is not None]
        stats[field] = {
            "known": len(values),
            "total": int(sum(values)) if values else None,
            "mean": round(_mean(values), 1) if values else None,
            "median": round(_median(values), 1) if values else None,
        }
    rates = [p["engagement_rate"] for p in posts if p.get("engagement_rate") is not None]
    stats["engagement_rate"] = round(_median(rates), 4) if rates else None
    followers = account.get("followers")
    mean_interactions = stats["interactions"]["mean"]
    stats["interactions_per_follower"] = (
        round(mean_interactions / followers, 4) if followers and mean_interactions is not None else None
    )

    durations = [p["duration_seconds"] for p in posts if p.get("duration_seconds")]
    stats["duration"] = {
        "known": len(durations),
        "median_seconds": round(_median(durations), 1) if durations else None,
        "buckets": {name: sum(1 for one in durations if low <= one < high) for name, low, high in _DURATION_BUCKETS},
    }

    #: 头部作品按互动排;整批都没有互动数(只有播放)时按播放排。
    rank_by = "interactions" if any(p.get("interactions") is not None for p in posts) else "views"
    ranked = sorted((p for p in posts if p.get(rank_by) is not None), key=lambda p: -p[rank_by])
    stats["top"] = [_brief_post(p) for p in ranked[:5]]
    stats["bottom"] = [_brief_post(p) for p in ranked[-3:]] if len(ranked) > 5 else []
    stats["trend"] = _trend(timed)
    stats["missing"] = [field for field in ("published_at", "duration_seconds", *COUNT_FIELDS)
                        if not any(p.get(field) is not None for p in posts)]
    return stats


def _top_hours(times: list[datetime]) -> list[int]:
    """发得最多的三个钟点(同样多的取早的)。"""
    counts = {hour: sum(1 for one in times if one.hour == hour) for hour in range(24)}
    busiest = sorted((hour for hour, count in counts.items() if count), key=lambda hour: (-counts[hour], hour))
    return busiest[:3]


def _brief_post(post: dict[str, Any]) -> dict[str, Any]:
    return {key: post.get(key) for key in ("title", "published_at", "interactions", "likes", "views", "url")}


def _trend(timed: list[dict[str, Any]]) -> dict[str, Any]:
    """最近一半 vs 之前一半:互动中位数之比、发布频率之比。不够条数就不下结论。"""
    if len(timed) < TREND_MIN_POSTS:
        return {"signal": "insufficient", "interactions_ratio": None, "frequency_ratio": None}
    half = len(timed) // 2
    older, recent = timed[:half], timed[half:]
    older_mid = _median([float(p["interactions"]) for p in older if p.get("interactions") is not None])
    recent_mid = _median([float(p["interactions"]) for p in recent if p.get("interactions") is not None])
    ratio = round(recent_mid / older_mid, 2) if older_mid and recent_mid is not None else None

    def per_week(chunk: list[dict[str, Any]]) -> float | None:
        stamps = [datetime.fromisoformat(p["published_at"]) for p in chunk]
        span = (stamps[-1] - stamps[0]).total_seconds() / 86400
        return len(stamps) / max(span, 1.0) * 7 if len(stamps) >= 2 else None

    older_freq, recent_freq = per_week(older), per_week(recent)
    frequency = round(recent_freq / older_freq, 2) if older_freq and recent_freq is not None else None
    if ratio is None:
        signal = "insufficient"
    elif ratio >= TREND_UP:
        signal = "growing"
    elif ratio <= TREND_DOWN:
        signal = "declining"
    else:
        signal = "steady"
    return {"signal": signal, "interactions_ratio": ratio, "frequency_ratio": frequency}


def comment_stats(comments: list[dict[str, Any]]) -> dict[str, Any]:
    likes = [float(c["likes"]) for c in comments if c.get("likes") is not None]
    ranked = sorted(comments, key=lambda c: -(c.get("likes") or 0))
    return {
        "count": len(comments),
        "likes_total": int(sum(likes)) if likes else None,
        "top": [{"text": c["text"], "likes": c.get("likes")} for c in ranked[:10]],
        "missing": [field for field in ("likes", "published_at") if not any(c.get(field) is not None for c in comments)],
    }


# --------------------------------------------------------------------------------------
# 给人(和模型)读的两段文字
# --------------------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and value >= 10_000:
        return f"{value:,}"
    return str(value)


def _cell(text: Any, limit: int = 40) -> str:
    one = re.sub(r"\s+", " ", str(text or "")).replace("|", "/").strip()
    return one if len(one) <= limit else one[: limit - 1] + "…"


class _Writer:
    """按一种语言写行:标签和值之间的冒号、列表里的分隔符都跟着语言走(中文全角、英文半角)。"""

    def __init__(self, locale: str | None) -> None:
        self.lang = locale or get_current_locale()
        self.lines: list[str] = []

    def say(self, key: str, **params: Any) -> str:
        return t(f"social_{key}", self.lang, **params)

    def joined(self, parts: list[str]) -> str:
        return t("punct_listSep", self.lang).join(parts) or "—"

    def item(self, label_key: str, value: Any, *, indent: str = "") -> None:
        self.lines.append(indent + "- " + self.say("kv", label=self.say(label_key), value=value))

    def text(self, line: str) -> None:
        self.lines.append(line)

    def done(self) -> str:
        return "\n".join(self.lines)


def posts_summary(stats: dict[str, Any], account: dict[str, Any], *, locale: str | None = None) -> str:
    """指标的文字版(Markdown):给写报告的模型读,也原样附在笔记后面。"""
    out = _Writer(locale)
    if any(value not in (None, "") for value in account.values()):
        out.text(f"### {out.say('accountHeading')}")
        for field in ACCOUNT_FIELDS:
            value = account.get(field)
            if value not in (None, ""):
                out.item("account_" + field, _fmt(value))
    out.text(f"### {out.say('statsHeading')}")
    out.item("count", stats["count"])
    if stats["count"] == 0:
        out.text(f"- {out.say('noPosts')}")
        return out.done()
    if stats.get("with_time"):
        out.item("range", out.say("rangeValue", first=stats["first_post"], last=stats["last_post"],
                                  days=_fmt(stats["span_days"])))
        out.item("daysSinceLast", _fmt(stats["days_since_last"]))
        out.item("perWeek", _fmt(stats["posts_per_week"]))
        out.item("medianGap", _fmt(stats["median_gap_days"]))
        out.item("longestGap", _fmt(stats["longest_gap_days"]))
        out.item("weekdays", out.joined([f"{out.say('weekday_' + day)} {count}" for day, count in stats["weekdays"].items()]))
        out.item("dayparts", out.joined([f"{out.say('daypart_' + name)} {count}" for name, count in stats["dayparts"].items()]))
        out.item("topHours", out.joined([f"{hour}:00" for hour in stats["top_hours"]]))
    else:
        out.text(f"- {out.say('noTimes')}")
    for field in (*COUNT_FIELDS, "interactions"):
        one = stats[field]
        if one["known"]:
            out.item("metric_" + field, out.say("metricLine", mean=_fmt(one["mean"]), median=_fmt(one["median"]),
                                                total=_fmt(one["total"]), known=one["known"]))
    if stats.get("engagement_rate") is not None:
        out.item("engagementRate", f"{stats['engagement_rate']:.2%}")
    if stats.get("interactions_per_follower") is not None:
        out.item("perFollower", f"{stats['interactions_per_follower']:.2%}")
    duration = stats["duration"]
    if duration["known"]:
        buckets = out.joined([f"{out.say('duration_' + name)} {count}" for name, count in duration["buckets"].items() if count])
        out.item("duration", out.say("durationValue", median=_fmt(duration["median_seconds"]), buckets=buckets))
    trend = stats["trend"]
    signal = out.say("signal_" + trend["signal"])
    if trend["interactions_ratio"] is not None:
        signal = out.say("trendValue", signal=signal, interactions=_fmt(trend["interactions_ratio"]),
                         frequency=_fmt(trend["frequency_ratio"]))
    out.item("trend", signal)
    if stats["top"]:
        out.text(f"- {out.say('top')}")
        for index, one in enumerate(stats["top"], start=1):
            out.text(f"  {index}. " + out.say("topValue", title=_cell(one["title"], 60) or "—",
                                              interactions=_fmt(one["interactions"]), views=_fmt(one["views"]),
                                              when=(one["published_at"] or "—").replace("T", " ")[:16]))
    if stats["missing"]:
        out.item("missing", out.joined([out.say("field_" + field) for field in stats["missing"]]))
    return out.done()


def posts_table(posts: list[dict[str, Any]], *, locale: str | None = None) -> str:
    lang = locale or get_current_locale()
    columns = ("published_at", "title", "duration_seconds", *COUNT_FIELDS)
    header = "| " + " | ".join(t(f"social_field_{column}", lang) for column in columns) + " |"
    rows = [header, "|" + "---|" * len(columns)]
    for post in posts:
        cells = [
            (post.get("published_at") or "—").replace("T", " ")[:16],
            _cell(post.get("title")) or "—",
            _fmt(post.get("duration_seconds")),
            *(_fmt(post.get(field)) for field in COUNT_FIELDS),
        ]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def comments_summary(stats: dict[str, Any], *, locale: str | None = None) -> str:
    out = _Writer(locale)
    out.text(f"### {out.say('commentsHeading')}")
    out.item("commentCount", stats["count"])
    if stats["count"] == 0:
        out.text(f"- {out.say('noComments')}")
        return out.done()
    if stats["likes_total"] is not None:
        out.item("commentLikes", _fmt(stats["likes_total"]))
    out.text(f"- {out.say('topComments')}")
    for index, one in enumerate(stats["top"], start=1):
        out.text(f"  {index}. {_cell(one['text'], 120)}(👍 {_fmt(one['likes'])})")
    return out.done()


def comments_table(comments: list[dict[str, Any]]) -> str:
    """一行一条:赞数在前,模型读得快。"""
    return "\n".join(f"- 👍{_fmt(one.get('likes'))} {_cell(one.get('text'), 200)}" for one in comments if one.get("text"))


__all__ = [
    "ACCOUNT", "VIDEO", "PLATFORM_ALIASES", "SHORT_LINK_HOSTS", "SocialLink",
    "comment_stats", "comments_summary", "comments_table", "find_items", "normalize_account", "normalize_comment",
    "normalize_post", "parse_count", "parse_link", "parse_seconds", "parse_time", "platform_of", "post_stats",
    "posts_summary", "posts_table", "resolve_short_link",
]
