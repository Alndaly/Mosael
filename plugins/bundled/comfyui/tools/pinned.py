"""钉死版本的压缩包:下载、按 sha256 校验、安全地解开(ADR 0041)。

补装 pysssss(选目录那一种)和「让 Mosael 装」的 ComfyUI 源码、pysssss 都走这里:

- **下载**走宿主给这个连接的代理(urllib 缺省就读那几个环境变量);GitHub 上的地址前面可以接一个**镜像前缀**(宿主在「管理 →
  下载源」里配,经输入交进来)。镜像、代理都换不了内容:sha256 对不上就不用,半截的不留下;
- **解开**:先解到旁边一个临时目录,全部解完再改名 —— 半截的不留在目标位置。只收普通文件和目录:链接、绝对路径、`..`
  一概不收;个数、总大小有上限(只防一个不对的下载)。压缩包里那一层顶目录(`ComfyUI-0.39.0/`)去掉。
"""

from __future__ import annotations

import errno
import hashlib
import http.client
import os
import shutil
import tarfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib import request

from lines import ComfyError, say

#: 一次读多少字节(顺带看一眼取消了没有、报一次进度)。
CHUNK = 256 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 120
#: 这几个站的地址才接镜像前缀:钉死的压缩包都在 GitHub 上(codeload 是它下压缩包的那个站)。
GITHUB_HOSTS = ("https://codeload.github.com/", "https://github.com/")


class Cancelled(Exception):
    """宿主建了取消文件:停下手上的事,半截的不留下。"""


@dataclass(frozen=True)
class Archive:
    """一个钉死的压缩包。`size` 是它大约多大 —— codeload 现打包、不给 Content-Length,进度按它估;下载的上限也按它定。"""

    name: str
    url: str
    sha256: str
    size: int
    max_members: int
    max_unpacked: int

    @property
    def max_bytes(self) -> int:
        """下载最多读多少字节:比钉死的大一截就不对了(sha256 也对不上),不必读完一个没完没了的流。"""
        return self.size * 2 + 1024 * 1024


def cancelled() -> bool:
    """宿主要停了:它建了那个取消文件(MOSAEL_PLUGIN_CANCEL_FILE,见宿主的 runtime.stream_tool)。"""
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "")
    return bool(path) and os.path.exists(path)


def never() -> bool:
    return False


def source_url(url: str, mirror: str) -> str:
    """真正去下的地址:GitHub 上的地址前面接上镜像前缀(`https://镜像/` + 原地址,常见的 GitHub 加速都这么用);别的不动。"""
    prefix = (mirror or "").strip()
    if not prefix or not url.startswith(GITHUB_HOSTS):
        return url
    return (prefix if prefix.endswith("/") else f"{prefix}/") + url


def download(archive: Archive, target: Path, locale: str, *, mirror: str = "",
             is_cancelled: Callable[[], bool] = never, on_bytes: Callable[[int, int], None] | None = None) -> Path:
    """下到 `target`:先写 `<target>.part`,边下边算 sha256,对上了才改名成 `target`。对不上、断了、取消了,`.part` 都删掉。
    `on_bytes(已下, 总共)`:总共是响应头给的长度,没给就按钉死的大小估。"""
    url = source_url(archive.url, mirror)
    part = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        with request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, open(part, "wb") as out:  # noqa: S310 — 钉死的地址(可接镜像前缀)
            length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            total = int(length) if length and length.isdigit() else archive.size
            if on_bytes is not None:
                on_bytes(0, total)
            while True:
                if is_cancelled():
                    raise Cancelled
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > archive.max_bytes:
                    raise ComfyError(say(locale, f"下载到的 {archive.name} 大得不对,没有用它",
                                         f"The downloaded {archive.name} is far too big; it wasn't used"))
                digest.update(chunk)
                out.write(chunk)
                if on_bytes is not None:
                    on_bytes(written, max(total, written))
    except OSError as exc:
        part.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise ComfyError(say(locale, f"磁盘满了,{archive.name} 没下完。清出空间再试",
                                 f"The disk is full, so {archive.name} didn't finish downloading. Free up space and try again")) from exc
        reason = getattr(exc, "reason", None) or exc
        hint_zh = "GitHub 慢或连不上时,可以在「管理 → 下载源」里填一个 GitHub 镜像前缀,或者在设置里配代理" \
            if url.startswith(GITHUB_HOSTS) or mirror else "检查网络后再试"
        hint_en = "If GitHub is slow or unreachable, set a GitHub mirror prefix under Admin → Download sources, or set a proxy " \
                  "in Settings" if url.startswith(GITHUB_HOSTS) or mirror else "Check the network and try again"
        raise ComfyError(say(locale, f"下载 {archive.name} 失败:{reason}。{hint_zh}\n{url}",
                             f"Downloading {archive.name} failed: {reason}. {hint_en}\n{url}")) from exc
    except http.client.HTTPException as exc:  # 读到一半断了(IncompleteRead 这类)
        part.unlink(missing_ok=True)
        raise ComfyError(say(locale, f"下载 {archive.name} 时断了:{exc!r}。再试一次\n{url}",
                             f"Downloading {archive.name} broke off: {exc!r}. Try again\n{url}")) from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    got = digest.hexdigest()
    if got != archive.sha256:
        part.unlink(missing_ok=True)
        raise ComfyError(say(
            locale,
            f"下载到的 {archive.name} 和钉死的版本对不上(sha256 {got[:12]}…,应为 {archive.sha256[:12]}…),没有用它。"
            f"走的是镜像或代理的话,它给了别的内容\n{url}",
            f"The downloaded {archive.name} doesn't match the pinned version (sha256 {got[:12]}…, expected "
            f"{archive.sha256[:12]}…), so it wasn't used. If it came through a mirror or proxy, that served different content\n{url}",
        ))
    part.replace(target)
    return target


def unpack(path: Path, target: Path, archive: Archive, locale: str, *,
           is_cancelled: Callable[[], bool] = never) -> None:
    """把压缩包解进 `target`(去掉顶上那一层目录)。先解到旁边的临时目录,全部解完再改名;`target` 已经在了就不动它,报错。"""
    staging = target.parent / f".mosael-{uuid.uuid4().hex[:8]}"
    total = 0
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            members = tar.getmembers()
            if len(members) > archive.max_members:
                raise ValueError(f"{len(members)} > {archive.max_members}")
            for member in members:
                if is_cancelled():
                    raise Cancelled
                parts = PurePosixPath(member.name).parts
                if member.name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                    raise ValueError(member.name)
                inner = parts[1:]
                if not inner:
                    continue
                destination = staging.joinpath(*inner)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue  # 链接、设备文件:钉死的那几个包里没有,有就不收
                total += member.size
                if total > archive.max_unpacked:
                    raise ValueError(f"> {archive.max_unpacked} bytes")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    continue
                with source, open(destination, "wb") as out:
                    shutil.copyfileobj(source, out)
        if target.exists():
            raise ValueError(f"{target} exists")
        staging.replace(target)
    except (tarfile.TarError, ValueError, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ComfyError(say(locale, f"{archive.name} 的压缩包解不开,没有装:{exc}",
                             f"The {archive.name} archive couldn't be unpacked; nothing was installed: {exc}")) from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


__all__ = ["Archive", "Cancelled", "GITHUB_HOSTS", "cancelled", "download", "never", "source_url", "unpack"]
