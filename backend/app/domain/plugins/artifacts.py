"""插件产出**文件**的那条路。

插件协议是 JSON over stdio(见 runtime 的说明):进出都是 JSON 对象。于是一个插件能告诉你
「这个网盘目录里有哪些文件」,却没办法把一个 2GB 的 mp4 交给素材库 —— 想搬字节只能 base64
塞进 JSON,而输出上限是 1MB。

所以给成功响应加一种约定形状。插件有两种交法:

    {"artifact": {"path": "已经下好的文件"}}          # 它自己下完了
    {"artifact": {"url": "...", "headers": {...}}}   # 它只换到了下载凭据

**第二种才是重点**。百度网盘的 dlink 就是这个形状:带时效、要带特定请求头才下得动。让插件
负责**换取凭据**、后端负责**搬字节**,进度、取消、重试、失败隔离全都复用现成的任务机制,
插件自己一行都不用写。反过来让插件自己下的话,每个插件都要再实现一遍这些,而它们会各实现
各的。

入库统一走 `register_file_asset` —— 上传、本机注册、渲染产出、AI 生成、从链接导入用的都是
它。这里只是又一个「字节从哪来」,后面的探测、缩略图、波形、建记录完全一样。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.http_retry import RetryingClient
from app.db.models import Asset

logger = logging.getLogger(__name__)

#: 插件写产出文件的地方。目录由后端建、用完就删,路径经环境变量告诉插件。
SCRATCH_ENV = "OPEN_STUDIO_PLUGIN_OUTPUT_DIR"

#: 一份产出最大多少。不是怕慢,是怕**一个跑飞的插件把磁盘写满** —— 那时候整个应用都动不了,
#: 而现象和插件毫无关系(渲染失败、数据库写不进去)。
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024

DOWNLOAD_TIMEOUT_SECONDS = 300.0


class ArtifactError(RuntimeError):
    """产出交接失败。消息面向用户,可以直接显示。"""


def make_scratch_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="open-studio-plugin-out-"))


def cleanup_scratch_dir(path: Path | None) -> None:
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def _resolve_local(spec: dict[str, Any], scratch: Path) -> Path:
    raw = str(spec.get("path") or "").strip()
    if not raw:
        raise ArtifactError("插件产出缺少 path")
    path = Path(raw)
    if not path.is_absolute():
        path = scratch / path
    path = path.resolve()
    # **必须落在给它的暂存目录里**。插件本来就以用户身份运行、读得到用户读得到的一切,
    # 所以这不挡提权;它挡的是「随手交出一个别处的文件」—— 比如把 ~/.ssh/id_rsa 收进素材库,
    # 而素材库里的东西是能被发布出去的。限定目录还让清理变成一件确定的事。
    if not str(path).startswith(str(scratch.resolve()) + "/"):
        raise ArtifactError(f"插件产出必须写在 {SCRATCH_ENV} 指定的目录里")
    if not path.is_file():
        raise ArtifactError("插件产出文件不存在")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ArtifactError("插件产出超过大小上限")
    return path


def _download(spec: dict[str, Any], scratch: Path) -> Path:
    url = str(spec.get("url") or "").strip()
    if not url:
        raise ArtifactError("插件产出缺少 url")
    if not url.startswith(("http://", "https://")):
        raise ArtifactError("插件产出的 url 只能是 http/https")
    headers = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
    name = str(spec.get("filename") or "").strip() or "download"
    target = scratch / Path(name).name
    written = 0
    try:
        with RetryingClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, headers=headers, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        written += len(chunk)
                        if written > MAX_ARTIFACT_BYTES:
                            raise ArtifactError("插件产出超过大小上限")
                        handle.write(chunk)
    except httpx.HTTPError as exc:
        raise ArtifactError(f"下载插件产出失败:{exc}") from exc
    return target


def register(
    db: Session,
    spec: dict[str, Any],
    scratch: Path,
    *,
    workspace_id: str,
    project_id: str | None,
    fallback_name: str,
) -> Asset:
    """把一份产出收进素材库。两种交法在这里合流,入库那一步只有一条。"""
    from app.domain.assets import register_file_asset

    if spec.get("url"):
        path = _download(spec, scratch)
    else:
        path = _resolve_local(spec, scratch)
    name = str(spec.get("filename") or "").strip() or path.name or fallback_name
    return register_file_asset(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        source_path=path,
        name=name,
        source="plugin",
    )


__all__ = [
    "ArtifactError",
    "MAX_ARTIFACT_BYTES",
    "SCRATCH_ENV",
    "cleanup_scratch_dir",
    "make_scratch_dir",
    "register",
]
