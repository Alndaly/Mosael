"""从内嵌浏览器**下载**下来的文件进素材库:用户在会话窗口里点了下载链接,或浏览器自动化点开了一个下载。

此前这两种都弹 Mosael 窗口的系统保存框:人在跟前还好,自动化里它就一直挂着,动作却报成功,文件也不知道
去了哪。现在 Electron 那一侧不弹框、先存到临时目录,下完再交到这里入库 —— 用户点的走用户自己的会话
(`POST /api/assets/web-download`),自动化触发的走执行器通道,带着是哪次运行、哪个节点触发的
(`POST /api/browser/worker/actions/{id}/artifact`,见 api/routes/browser_worker)。

闸和截图那条一样收在这里:大小上限(边收边数,不先整个读进内存)、只收素材库认得的类型(看扩展名;入库时
照常探测、出缩略图,见 assets.importer)、文件名只取文件名本身并清掉怪字符(带路径的写不出临时目录,更写不出
素材目录)。出处字段与截图同一套(见 web_capture.remember_web_source):
`source_url` 是下载地址本身 —— 它确实是「这份文件从哪个地址下下来的」。
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.web_capture import RunOrigin, WebCaptureError, WebSource, remember_run_origin, remember_web_source
from app.media.probe import AUDIO_EXTENSIONS, DOCUMENT_EXTENSIONS

#: 单个下载文件的上限(2 GiB)。两个小时的 1080p 录像在这个量级;再大的不该经「点一下链接」进素材库。
#: Electron 那一侧下载之前按同一个数先拦(electron/publish/downloadRules.ts 的 MAX_DOWNLOAD_BYTES,
#: 两边由 contracts/shared-constants.json 钉住)。
MAX_DOWNLOAD_BYTES = 2_147_483_648

PAGE_DOWNLOAD = "page_download"

_VIDEO = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".flv", ".wmv", ".mpg", ".mpeg", ".3gp"}
_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".heic", ".heif", ".tif", ".tiff"}
#: 下载能收的扩展名:素材库认得的那几类。Electron 那一侧有同一份(downloadRules.ts 的 DOWNLOAD_SUFFIXES,
#: downloadRules.test.ts 对着这里比)。
DOWNLOAD_SUFFIXES = frozenset(_VIDEO | _IMAGE | AUDIO_EXTENSIONS | DOCUMENT_EXTENSIONS)

_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")


def safe_filename(name: str) -> str:
    """下载文件叫什么:只取文件名本身,清掉路径分隔与控制字符,太长就截(保留扩展名)。"""
    base = Path(str(name or "").replace("\\", "/")).name
    base = _UNSAFE.sub("_", base).strip(" .") or "download"
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        return base[:120]
    return f"{stem[:110] or 'download'}.{suffix[:10]}"


def check_download_name(name: str) -> str:
    """清过的文件名;不是素材库认得的类型就拒(415)。"""
    cleaned = safe_filename(name)
    if Path(cleaned).suffix.lower() not in DOWNLOAD_SUFFIXES:
        raise WebCaptureError("webDownloadErr_type", status=415, name=cleaned)
    return cleaned


def save_capped(stream: BinaryIO, target: Path, limit: int | None = None) -> int:
    """把字节流存到 `target`,超过上限立刻停并删掉半截文件(413)。返回字节数。"""
    cap = MAX_DOWNLOAD_BYTES if limit is None else limit
    total = 0
    try:
        with target.open("wb") as out:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > cap:
                    raise WebCaptureError("webDownloadErr_tooLarge", status=413, max_gb=round(cap / 1024**3, 1))
                out.write(chunk)
    except WebCaptureError:
        target.unlink(missing_ok=True)
        raise
    return total


def register_web_download(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    stream: BinaryIO,
    filename: str,
    source: WebSource,
    origin: RunOrigin | None = None,
) -> Asset:
    """一份下载下来的文件入库,带着出处(哪一页、下载地址、什么时候;自动化里还有哪次运行 / 哪个节点)。"""
    name = check_download_name(filename)
    workdir = Path(tempfile.mkdtemp(prefix="mosael-web-download-"))
    try:
        path = workdir / name
        save_capped(stream, path)
        if path.stat().st_size == 0:
            raise WebCaptureError("webDownloadErr_empty", name=name)
        asset = register_file_asset(
            db, workspace_id=workspace_id, project_id=project_id, source_path=path, name=name, source="downloaded",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    remember_web_source(asset, source)
    if origin is not None:
        remember_run_origin(asset, origin)
    return asset
