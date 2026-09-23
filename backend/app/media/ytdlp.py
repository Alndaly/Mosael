"""从链接取素材:探一次有什么,再下选中的那些。

**分两步是刻意的。** 一个链接可能是一条视频,也可能是一整个播放列表 / 频道 —— 几百条、几十 GB。
直接「粘链接就下」在单条时很顺手,在播放列表上就是一次没人要的批量下载。所以先探测(只读元数据,
不碰媒体流),把清单摆给用户勾。

**音频 / 视频是下载时才分的岔**,不是两套流程:同一个条目,选视频就取最好的画面 + 声音并合流,
选音频就只取声轨。用户想要的往往是后者(拿人声去转写、做配乐),而按视频下完再自己抽轨,是把
几百 MB 的下载和一次转码强加给他。

这里只管**字节**:落到临时目录、返回文件路径。入库(探测时长、缩略图、波形、建记录)交给
`domain/assets.register_file_asset` —— 那是所有素材共用的唯一一条入库路径。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: 探测时最多列多少条。频道链接能有上万条,全列出来对界面和用户都没有意义 ——
#: 而且 yt-dlp 要为此翻很多页。想要更多的,让他把链接换成更具体的那一个。
MAX_ENTRIES = 200

#: 浅层条目缺标题时,同时补几条的元数据。补一条约 0.6 s(实测 B 站分 P),200 条串行要两分钟;
#: 开太多又容易被站点当成刷接口(B 站回 412)。
RESOLVE_WORKERS = 6

#: 下载单条的超时。长视频 + 慢网络是常态,给得宽;超时不是"下得慢",是"这条再也不会回来"。
DOWNLOAD_TIMEOUT_SECONDS = 60 * 60

#: YouTube 拿哪个客户端的身份去取流 —— **带不带登录态,答案不一样**。
#:
#: 不带 cookie 时默认客户端会被 403(实测:同一条视频不带参数直接 `HTTP Error 403`),换成
#: android 立刻 5 MB/s 下完;代价是 android 只返回低清格式(那条 4K 视频只给到 360p)。
#:
#: **带 cookie 时必须换回 web 系**:cookie 是浏览器会话的凭据,android 客户端不认它 ——
#: 两者放一起,YouTube 干脆不返回任何格式,报的是「Requested format is not available」
#: (用户选了 YouTube 登录身份之后撞到的正是这个)。而 web 客户端一旦有了登录态,403 也就
#: 不再发生 —— 那个限制本来就是冲着匿名请求来的。
#:
#: 这是**会过期的经验值**:站点在变,yt-dlp 也在追。写成列表是因为 yt-dlp 会按顺序依次试。
_YOUTUBE_CLIENTS_ANONYMOUS = ["android", "web_safari", "web"]


def _youtube_extractor_args(cookie_file: Path | None) -> dict[str, Any]:
    """有登录态时**不指定客户端** —— 交给 yt-dlp 自己挑。

    实测很反直觉:同一份 cookie,写死 `web_safari/web/mweb` 只拿到 360p,而什么都不写反而拿到
    33 个格式、最高 1440p。yt-dlp 的默认策略本来就在按站点当下的情况轮换客户端,而我们写死的
    那串是为「匿名会被 403」这一个具体问题准备的经验值 —— 把它套到有登录态的情形上,等于用
    一个旧结论覆盖掉它一直在更新的判断。

    所以只在匿名时干预:那时不干预就是 403,干预才有得下(代价是只有低清)。
    """
    if cookie_file is not None:
        return {}
    return {"youtube": {"player_client": _YOUTUBE_CLIENTS_ANONYMOUS}}


#: YouTube 现在给流加了 JS 挑战(n-challenge)。**解不开,格式就整个被剥掉** —— yt-dlp 那时
#: 报的是 `Only images are available`,而调用方看到的是「没有可用格式」,完全看不出真因。
#:
#: 解它需要两样:一个 JS 运行时(deno / node,机器上有就行),以及 yt-dlp 官方的求解脚本 ——
#: 后者不随包分发,要按需从 yt-dlp 自己的 GitHub 仓库取一次。这一行就是允许它去取。
#:
#: **这是一次「下载并执行远程代码」**,所以说清楚:来源是 yt-dlp 官方仓库、它自己把这个开关
#: 标为推荐,而这个应用本来就在 Electron 里跑网页 JS,安全边界没有因此变宽。不开的代价是
#: YouTube 只剩 360p(实测),也就是这个功能对它基本不可用。
#: 机器上没有 JS 运行时时,yt-dlp 自己会退回低清那条路 —— 不会失败,只是画质上不去。
_REMOTE_COMPONENTS = ["ejs:github"]


class YtdlpError(RuntimeError):
    """取不到的原因,带文案 key(见 core/i18n 的 `urlImportErr_*`)。

    领域里不拼句子:出口(路由)按请求方的语言翻 `key` + `params`;`str(exc)` 是缺省语言的那句,
    给日志和任务失败清单用。原因怎么分见 `classify`。
    """

    def __init__(self, key: str, **params: object) -> None:
        from app.core.i18n import DEFAULT_LOCALE, t

        self.key = key
        self.params = params
        super().__init__(t(key, DEFAULT_LOCALE, **params))


@lru_cache(maxsize=1)
def extractor_classes() -> tuple[type[Any], ...]:
    """Return yt-dlp's current site-specific extractor registry.

    The generic extractor deliberately stays outside this list: it accepts almost every HTTP
    URL, so treating it as proof of support would make an ordinary article look like a video.
    Generic pages are still usable in the extension when an actual HTML video is present.
    """
    from yt_dlp.extractor import gen_extractor_classes

    return tuple(extractor for extractor in gen_extractor_classes() if extractor.IE_NAME != "generic")


def matching_extractor(url: str) -> str | None:
    """Identify a URL without making a network request.

    yt-dlp owns the URL patterns. Keeping a second domain catalogue in Mosael would always
    lag behind upgrades and was the reason the browser extension only covered three sites.
    """
    candidate = url.strip()
    if not candidate.lower().startswith(("http://", "https://")):
        return None
    for extractor in extractor_classes():
        try:
            if extractor.suitable(candidate):
                return str(extractor.IE_NAME)
        except Exception:  # noqa: BLE001 — one broken third-party regex must not break the registry
            logger.debug("yt-dlp extractor %s rejected URL matching", extractor.IE_NAME, exc_info=True)
    return None


@dataclass(frozen=True)
class RemoteEntry:
    """探测结果里的一条。`url` 是**这一条自己的**地址,不是用户粘的那个。"""

    id: str
    url: str
    title: str
    duration: float | None
    uploader: str
    thumbnail: str
    #: 这一条**实际拿得到**的画质高度,从高到低。空 = 还不知道(播放列表只做浅层探测)。
    #: 有它才谈得上"选像素":否则用户选了 1080p、下回来一个 360p,而没人告诉他为什么。
    heights: tuple[int, ...] = ()


@dataclass(frozen=True)
class RemoteListing:
    """一次探测的结果:标题 + 条目。单条视频也是一个只有一条的清单 —— 界面因此只需要一种形状。"""

    title: str
    is_playlist: bool
    entries: list[RemoteEntry]
    #: 清单被 MAX_ENTRIES 截断了吗。**要说出来** —— 否则用户以为这就是全部,
    #: 勾完发现少了一半。
    truncated: bool
    #: 这一批是从第几条开始的(1 起)。界面据此说"第 201–400 条",而不是让人以为总共这么多。
    start: int = 1


def _heights(raw: dict[str, Any]) -> tuple[int, ...]:
    """这条视频有哪几档画质。浅层探测(播放列表)拿不到 formats,那时就是空的 —— **空表示未知,
    不表示没有**,所以界面在空的时候给通用档位,而不是说"只有这几档"。"""
    seen = {
        int(fmt["height"])
        for fmt in (raw.get("formats") or [])
        if isinstance(fmt, dict) and isinstance(fmt.get("height"), (int, float)) and fmt["height"]
    }
    return tuple(sorted(seen, reverse=True))


def _entry(raw: dict[str, Any], fallback_url: str, *, within: str = "") -> RemoteEntry:
    """`within`:这一条所在列表的标题。条目标题以它开头时去掉这段 —— 列表标题已经在表头,
    而 B 站分 P 的标题是「合集标题 p02 分P名」:合集标题动辄七八十个字,整段照搬的话每行
    截断后只剩同一段开头,真正区分各条的分 P 名全被挤到看不见的地方。"""
    video_id = str(raw.get("id") or "")
    url = str(raw.get("webpage_url") or raw.get("url") or "")
    # extract_flat 的条目常常只给 id;拼回标准地址,下载那一步才有东西可用。
    if not url.startswith("http") and video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
    title = str(raw.get("title") or "").strip()
    if within and title.startswith(within):
        title = title[len(within):].strip(" -–—_|:：·") or title
    duration = raw.get("duration")
    return RemoteEntry(
        id=video_id,
        url=url or fallback_url,
        title=title or video_id or "未命名",
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        uploader=str(raw.get("uploader") or raw.get("channel") or ""),
        thumbnail=str(raw.get("thumbnail") or ""),
        heights=_heights(raw),
    )


def _fill_untitled(yt_dlp: Any, options: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """浅层条目没带标题的,逐条补一次元数据。

    有些站点的播放列表只给每条一个地址:B 站多 P 视频的浅层条目就只有
    `{"_type": "url", "url": ".../BV…?p=2"}` —— 没有 id、没有标题,分 P 名明明在它自己取到的
    分 P 表里,却没放进条目。界面于是列出 N 行「未命名」,下载下来的素材也分不出谁是谁。

    补的方式与站点无关:对那一条再问一次 yt-dlp,`process=False` 只跑站点解析、不挑格式、
    不碰媒体流。有标题的条目(YouTube 列表等)一条也不多问,所以这一步只在需要时才花时间。
    某条补不上就原样留着 —— 列表照样能用,只是那一条没名字,不该因为它让整次探测失败。
    """
    missing = [index for index, raw in enumerate(entries) if not raw.get("title") and raw.get("url")]
    if not missing:
        return entries

    def resolve(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(str(raw["url"]), download=False, process=False)
        except Exception:  # noqa: BLE001 — 补不上的那一条保持原样,不拖垮整份清单
            logger.debug("yt-dlp 补不上条目 %s 的元数据", raw.get("url"), exc_info=True)
            return raw
        return {**raw, **info} if isinstance(info, dict) else raw

    filled = list(entries)
    with ThreadPoolExecutor(max_workers=min(RESOLVE_WORKERS, len(missing))) as pool:
        for index, info in zip(missing, pool.map(resolve, [entries[index] for index in missing])):
            filled[index] = info
    return filled


def probe(url: str, *, cookie_file: Path | None = None, start: int = 1) -> RemoteListing:
    """这个链接后面有什么。**只读元数据,不下载任何媒体流。**

    `cookie_file`:借一份登录态过来(见 domain/assets/from_url)。会员视频、私享列表、需要登录
    才看得到的频道,不带它就只能看到"不可用"。

    `start`:从列表的第几条开始(1 起)。频道能有上万条,而一次探 200 条已经要翻好几页 ——
    与其把上限提高到让人等三分钟,不如让他往后翻:**第 201 条之后的内容并非取不到,只是要
    再问一次**。
    """
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # 播放列表里的条目只取浅层信息:逐条展开要为每条发一次请求,一个 50 条的列表能探好几分钟,
        # 而这一步的全部意义就是"快速看看有什么"。
        "extract_flat": "in_playlist",
        "playlist_items": f"{max(1, start)}-{max(1, start) + MAX_ENTRIES - 1}",
        "extractor_args": _youtube_extractor_args(cookie_file),
        "remote_components": _REMOTE_COMPONENTS,
    }
    if cookie_file is not None:
        options["cookiefile"] = str(cookie_file)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 — yt-dlp 的异常层次很深,对调用方只有"取不到"
        raise classify(exc) from exc
    if not info:
        raise YtdlpError("urlImportErr_noMedia")

    entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
    if entries:
        title = str(info.get("title") or "")
        return RemoteListing(
            title=title,
            is_playlist=True,
            entries=[_entry(raw, url, within=title) for raw in _fill_untitled(yt_dlp, options, entries)],
            truncated=len(entries) >= MAX_ENTRIES,
            start=max(1, start),
        )
    return RemoteListing(
        title=str(info.get("title") or ""),
        is_playlist=False,
        entries=[_entry(info, url)],
        truncated=False,
    )


def download(
    url: str,
    *,
    kind: str,
    target_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
    cookie_file: Path | None = None,
    max_height: int = 0,
) -> Path:
    """把一条下到 `target_dir`,返回落地的文件路径。

    `kind`:`"video"` 取画面 + 声音并合流,`"audio"` 只取声轨。**不做二次转码** —— 直接要
    对应的流,省掉一次全片重编码(那既慢又掉画质)。容器交给 yt-dlp 按流选,ffmpeg 只在需要
    合并音视频轨时介入。

    `max_height`:画质上限(0 = 不限)。**上限而不是精确值** —— 同一个播放列表里每条能给的
    画质并不一样,要求"正好 1080p"会让没有这一档的那些直接失败;要"不超过 1080p"则每条都
    取它自己能给的最好的那一档。4K 素材动辄几个 GB,而多数剪辑只需要 1080p。
    """
    import yt_dlp

    target_dir.mkdir(parents=True, exist_ok=True)

    def hook(status: dict[str, Any]) -> None:
        if on_progress is None:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            fraction = (done / total) if total else 0.0
            on_progress(min(0.95, fraction), str(status.get("_percent_str") or "").strip())
        elif status.get("status") == "finished":
            # 100% 之后还有合流 / 后处理,别让进度条停在那儿假装已经好了。
            on_progress(0.97, "")

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,  # 用户勾的是具体条目;这里再展开一次列表就是重复下载
        "outtmpl": str(target_dir / "%(title).120B [%(id)s].%(ext)s"),
        "progress_hooks": [hook],
        "socket_timeout": 30,
        "retries": 3,
        "extractor_args": _youtube_extractor_args(cookie_file),
        "remote_components": _REMOTE_COMPONENTS,
    }
    if cookie_file is not None:
        options["cookiefile"] = str(cookie_file)
    if kind == "audio":
        options["format"] = "bestaudio/best"
    else:
        limit = f"[height<={max_height}]" if max_height > 0 else ""
        # 三段回退:分离流合流 → 带上限的单文件 → 兜底。缺了后两段的话,只有单文件格式的站点
        # (以及只剩低清的 YouTube)会直接"没有可用格式"。
        options["format"] = f"bestvideo{limit}+bestaudio/best{limit}/best"
        # 合流容器固定 mp4:时间线和导出链路对它最熟,而 webm 在某些解码路径上要另做转码。
        options["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as exc:  # noqa: BLE001
        raise classify(exc) from exc

    if path.is_file():
        return path
    # 后处理换过扩展名(合流、抽音轨)时 prepare_filename 给的是原名。按 id 找回真正落地的那个。
    stem = path.stem
    for candidate in sorted(target_dir.glob(f"{glob_escape(stem)}.*")):
        if candidate.is_file():
            return candidate
    raise YtdlpError("urlImportErr_fileMissing")


def glob_escape(text: str) -> str:
    """把标题里的 `[` `]` `*` `?` 转义掉 —— 视频标题里这些字符很常见,不转义就匹配不到自己。"""
    return "".join("[" + char + "]" if char in "[]*?" else char for char in text)


#: 各类原因在 yt-dlp 报错原文里的说法(小写)。**顺序就是判定顺序**,先中先得:
#: 「Private video. Sign in if you've been granted access」同时带着「private」和「sign in」,
#: 它首先是一条私密内容,登录只是有权限的人才有用的补救。
_REASONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("urlImportErr_unsupported", ("unsupported url", "is not a valid url")),
    ("urlImportErr_unavailable", ("private video", "this video is private", "is private")),
    (
        "urlImportErr_loginRequired",
        (
            "sign in", "log in", "login required", "registered users", "--cookies", "not a bot",
            "members-only", "members only", "premium", "requires payment", "purchase", "subscription",
        ),
    ),
    (
        "urlImportErr_geoBlocked",
        ("geo restrict", "available in your country", "available from your location", "ip address is blocked"),
    ),
    ("urlImportErr_notFound", ("http error 404", "http error 410")),
    ("urlImportErr_unavailable", ("unavailable", "removed", "deleted", "does not exist", "taken down")),
    ("urlImportErr_forbidden", ("http error 403", "http error 412", "forbidden", "precondition failed")),
    ("urlImportErr_formatMismatch", ("requested format is not available",)),
    ("urlImportErr_drm", ("drm protected",)),
    ("urlImportErr_noMedia", ("no video formats", "no formats found", "no video", "no media", "only images are available")),
    ("urlImportErr_mergeFailed", ("ffmpeg exited", "postprocessing: conversion failed")),
    (
        "urlImportErr_network",
        (
            "timed out", "timeout", "connection refused", "connection reset", "connection aborted",
            "unable to connect", "failed to resolve", "name or service not known", "nodename nor servname",
            "temporary failure in name resolution", "network is unreachable", "remote end closed",
            "ssl:", "proxy error", "cannot connect to proxy",
        ),
    ),
)


def _causes(exc: BaseException) -> list[BaseException]:
    """yt-dlp 把真正的原因包了好几层:`DownloadError.exc_info` → `ExtractorError.cause` → `HTTPError`。
    只看最外层的话,类型永远是 DownloadError,原文里也只剩一句转述。"""
    chain: list[BaseException] = []
    pending: list[object] = [exc]
    while pending:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or any(current is seen for seen in chain):
            continue
        chain.append(current)
        exc_info = getattr(current, "exc_info", None)
        if isinstance(exc_info, tuple) and len(exc_info) > 1:
            pending.append(exc_info[1])
        pending.extend((getattr(current, "cause", None), current.__cause__, current.__context__))
    return chain


def classify(exc: BaseException) -> YtdlpError:
    """把 yt-dlp 的报错归成一个原因 —— 每个原因对应一句能照着做的话。

    **「不支持」和「没有」必须分开。** 站点不认识(没有专门的解析器、通用解析器在页面里也没找到
    视频)时 yt-dlp 抛 `UnsupportedError`;站点认识但这一条确实没有媒体流时报的是
    「No video formats found」。两者曾共用一句「这个链接里没有可下载的视频」,于是不支持的网站
    被说成里面没有视频,而要登录、被删除、被地区限制的那些又各自落进别的桶或兜底。

    先按**异常类型**判(不受措辞改动影响),再按原文里的说法判。认不出来的给原文最后一行 ——
    yt-dlp 把结论放在最后,而它总比一句空泛的「失败了」有用。
    """
    from yt_dlp.networking.exceptions import HTTPError, TransportError
    from yt_dlp.utils import GeoRestrictedError, UnsupportedError

    chain = _causes(exc)
    if any(isinstance(cause, UnsupportedError) for cause in chain):
        return YtdlpError("urlImportErr_unsupported")
    if any(isinstance(cause, GeoRestrictedError) for cause in chain):
        return YtdlpError("urlImportErr_geoBlocked")
    text = "\n".join(str(cause) for cause in chain).lower()
    for key, phrases in _REASONS:
        if any(phrase in text for phrase in phrases):
            return YtdlpError(key)
    statuses = {cause.status for cause in chain if isinstance(cause, HTTPError)}
    if statuses & {404, 410}:
        return YtdlpError("urlImportErr_notFound")
    if statuses & {401, 403, 412}:
        return YtdlpError("urlImportErr_forbidden")
    if any(isinstance(cause, TransportError) for cause in chain):
        return YtdlpError("urlImportErr_network")
    raw = str(exc)
    last = next((line.strip() for line in reversed(raw.splitlines()) if line.strip()), raw)
    return YtdlpError("urlImportErr_other", detail=last[:300])
