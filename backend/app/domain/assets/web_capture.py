"""从内嵌浏览器存进素材库的东西:截屏(可见区域 / 整页长图 / 框选)和页面上的图片。

**出处记在 media_info 里**,和「从链接导入」记 `source_url` 是同一个地方(见 source_url.remember_asset_source):

- `source_page_url` / `source_page_title`:从哪一页来的;
- `captured_at`:截取的那一刻(不是上传的那一刻 —— 框选可能停了一会儿才框完);
- `capture`:怎么来的(见 CAPTURE_KINDS);
- 页面图片另记 `source_url`:**图片自己的地址**。截图不记它 —— 截图不是「从某个地址下载来的那份文件」,
  记了就会被当成直链交给模型供应商去下载(见 providers.contracts.direct_media_url),对面拿到的是原图而不是截图。

lineage / derived_from 不适用:它们说的是「从库里哪几份素材做出来的」,而这里的来处是一个网页。

**这条入口收的是客户端交来的字节**,所以四道闸都在这里:只收图片(看文件头,不信客户端报的类型)、大小上限、
文件名由服务端定(客户端给的名字一律不用,落盘目录就是这份素材自己的目录)、出处里的地址只认 http(s)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import import_binary_asset
from app.domain.assets.source_url import remember_asset_source

#: 单个文件上限。整页长图(上限 15000 CSS 像素高,高分屏两倍)量化前能有二三十 MB;再大就不是一张截图了。
#: Electron 那一侧取页面图片用的是同一个数(electron/publish/pageImages.ts 的 MAX_IMAGE_BYTES)。
MAX_CAPTURE_BYTES = 40 * 1024 * 1024

#: 怎么来的。截图三种对应顶栏「截屏」的三个选项;page_image 是「采集页面图片」;page_video 是「下载页面里的视频」
#: (那一条走从链接导入的任务,见 from_url,出处字段与这里同一套)。
CAPTURE_KINDS = ("screenshot_visible", "screenshot_full", "screenshot_region", "page_image")
PAGE_VIDEO = "page_video"
#: 「截图」节点截的(自动化会话里那一页):可见区域、整页长图、某个元素。框选要人拖,节点里没有。
NODE_SCREENSHOT_KINDS = ("screenshot_visible", "screenshot_full", "screenshot_element")

#: 认得的图片格式 → 落盘扩展名。和 electron/publish/pageToolsCore.sniffImage 认的是同一组。
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}

_MAX_URL = 2000
_MAX_TITLE = 300


class WebCaptureError(LocalizedError, ValueError):
    """这份截图 / 图片不收。`status` 是给接口出口的状态码。"""

    def __init__(self, key: str, *, status: int = 422, **params: object) -> None:
        super().__init__(key, **params)
        self.status = status


@dataclass(frozen=True)
class WebSource:
    """一份网页素材的出处。"""

    page_url: str
    page_title: str
    captured_at: datetime
    capture: str
    #: 页面图片自己的地址;截图为空。
    source_url: str = ""


@dataclass(frozen=True)
class RunOrigin:
    """浏览器自动化里是谁触发的:哪次运行(工作流任务)、哪个节点、哪个浏览器会话。不是工作流(智能体)时为空串。"""

    run_id: str = ""
    node_id: str = ""
    browser_session_id: str = ""


def remember_run_origin(asset: Asset, origin: RunOrigin) -> None:
    """自动化里存进来的素材,出处再记上是哪次运行 / 哪个节点触发的(空的不写)。"""
    extra = {
        "source_run_id": origin.run_id,
        "source_node_id": origin.node_id,
        "source_browser_session_id": origin.browser_session_id,
    }
    asset.media_info = {**(asset.media_info or {}), **{key: value for key, value in extra.items() if value}}


def web_source(
    *, page_url: str, page_title: str, captured_at: str, capture: str, source_url: str = "", allowed: tuple[str, ...] = CAPTURE_KINDS,
) -> WebSource:
    """把客户端报来的出处收成一个 WebSource;哪一格不像样就拒(不替它猜)。"""
    if capture not in allowed:
        raise WebCaptureError("webCaptureErr_kind", kind=capture[:40])
    page_url = page_url.strip()
    if not _is_http(page_url):
        raise WebCaptureError("webCaptureErr_pageUrl")
    source_url = source_url.strip()
    if source_url and not _is_http(source_url):
        raise WebCaptureError("webCaptureErr_sourceUrl")
    try:
        moment = datetime.fromisoformat(captured_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise WebCaptureError("webCaptureErr_capturedAt") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return WebSource(
        page_url=page_url,
        page_title=page_title.strip()[:_MAX_TITLE],
        captured_at=moment.astimezone(timezone.utc),
        capture=capture,
        source_url=source_url,
    )


def _is_http(url: str) -> bool:
    if not url or len(url) > _MAX_URL:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def sniff_image(data: bytes) -> str | None:
    """看文件头认图片格式;不是认得的图片返回 None。SVG 不收:它是能带脚本的文档,不是位图。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def read_capped(stream: BinaryIO) -> bytes:
    """读上传的字节,超过上限立刻停 —— 不先把一个几 GB 的东西整个读进内存再说它太大。"""
    chunks: list[bytes] = []
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_CAPTURE_BYTES:
            raise WebCaptureError("webCaptureErr_tooLarge", status=413, max_mb=MAX_CAPTURE_BYTES // (1024 * 1024))
        chunks.append(chunk)
    return b"".join(chunks)


def remember_web_source(asset: Asset, source: WebSource) -> None:
    """把出处写进 media_info(合并,不替换:media_info 还承载尺寸、缩略图、代理等旗标)。"""
    if source.source_url:
        remember_asset_source(asset, source.source_url)
    asset.media_info = {
        **(asset.media_info or {}),
        "source_page_url": source.page_url,
        "source_page_title": source.page_title,
        "captured_at": source.captured_at.isoformat(),
        "capture": source.capture,
    }


def register_web_capture(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    data: bytes,
    source: WebSource,
    name: str | None = None,
) -> Asset:
    """一张截图 / 页面图片入库,带着出处。走所有素材共用的那条入库路径(探测、缩略图、建记录)。"""
    if len(data) > MAX_CAPTURE_BYTES:
        raise WebCaptureError("webCaptureErr_tooLarge", status=413, max_mb=MAX_CAPTURE_BYTES // (1024 * 1024))
    mime = sniff_image(data)
    if mime is None:
        raise WebCaptureError("webCaptureErr_notImage", status=415)
    prefix = "image" if source.capture == "page_image" else "screenshot"
    #: 文件名完全由这里定:客户端给的名字可能带路径、可能撞名,素材名(name)才是给人看的那个。
    filename = f"{prefix}-{source.captured_at.strftime('%Y%m%d-%H%M%S')}{_EXTENSIONS[mime]}"
    asset = import_binary_asset(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        data=data,
        original=filename,
        content_type=mime,
        source="captured",
        name=(name or "").strip()[:200] or None,
    )
    remember_web_source(asset, source)
    return asset
