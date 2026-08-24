"""下载源上那些文件**实际**有多大。

此前每个模型的体积都是写死在目录里的一个数(`expected_bytes`)。那是当初照着文件清单抄下来的
快照,而它同时充当三样东西:卡片上给用户看的「1.5 GB」、进度条的分母、以及「装好了没有」的
判据。三样都会随上游改一次文件而失准 —— F5 走 ModelScope 实际是
1,348,435,761(检查点)+ 13,800(vocab)+ 54,365,991(声码器)= **1.40 GB**,而写死的是 1.5 GB,
于是进度条走到 93% 就完成了。

所以体积从源上问。问不到就退回那个写死的估算,并**说清楚这是估算** —— 一个猜出来的数字
装成实测值,比承认不知道更糟。

两个源都能按文件给出字节数(实测):

- HuggingFace:``/api/models/{repo}?blobs=true`` → ``siblings[].size``
- ModelScope:``/api/v1/models/{repo}/repo/files?Recursive=True`` → ``Data.Files[].Size``
"""
from __future__ import annotations

import fnmatch
import logging
import threading
import time
from typing import Sequence

import httpx

logger = logging.getLogger(__name__)

#: 模型文件几乎不变,所以可以缓存很久。真更新了,下一次冷启动或这个 TTL 到了自然会重问。
_TTL_SECONDS = 24 * 3600
#: 问不到时也记一笔,时长短得多 —— 不记的话每次列卡片都要重新等一遍超时。
_FAILURE_TTL_SECONDS = 300
#: 这是**可选信息**:拿不到就用估算继续。所以给的时间很短,不能让它拖住下载的开始。
_TIMEOUT = 6.0

_HOSTS = {
    "hf": "https://huggingface.co",
    "hf-mirror": "https://hf-mirror.com",
}

_cache: dict[tuple[str, str], tuple[float, dict[str, int] | None]] = {}
_lock = threading.Lock()
_refreshing: set[tuple[str, str]] = set()


def _fresh(key: tuple[str, str]) -> dict[str, int] | None | object:
    """缓存里还新鲜的那份。没有(或过期)返回 `_MISS`,以便和"问过了但源上没有"区分开。"""
    with _lock:
        hit = _cache.get(key)
    if hit is None:
        return _MISS
    stamped, files = hit
    ttl = _TTL_SECONDS if files is not None else _FAILURE_TTL_SECONDS
    return files if time.monotonic() - stamped < ttl else _MISS


_MISS = object()


def _fetch(source: str, repo: str) -> dict[str, int] | None:
    """问一次源,拿到 `{文件路径: 字节数}`。问不到返回 None(**不是空字典**——那是"仓库是空的")。"""
    try:
        if source == "modelscope":
            url = f"https://modelscope.cn/api/v1/models/{repo}/repo/files"
            response = httpx.get(url, params={"Recursive": "True"}, timeout=_TIMEOUT,
                                 follow_redirects=True)
            response.raise_for_status()
            entries = ((response.json().get("Data") or {}).get("Files")) or []
            # 目录项的 Size 是 0,混进来只会稀释判断;按有没有 Size 过滤不行(空文件也是 0),
            # 所以看 Type —— 没有 Type 时退回"路径不是目录项"这个弱判据。
            return {
                str(item.get("Path") or ""): int(item.get("Size") or 0)
                for item in entries
                if str(item.get("Type") or "blob").lower() != "tree" and item.get("Path")
            }
        host = _HOSTS.get(source)
        if host is None:
            return None
        response = httpx.get(f"{host}/api/models/{repo}", params={"blobs": "true"},
                             timeout=_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        siblings = response.json().get("siblings") or []
        return {
            str(item.get("rfilename") or ""): int(item.get("size") or 0)
            for item in siblings
            if item.get("rfilename")
        }
    except Exception as exc:  # noqa: BLE001 — 源不可达只是"问不到大小",不是错误
        logger.debug("问不到 %s 上 %s 的文件大小:%s", source, repo, exc)
        return None


def _store(key: tuple[str, str], files: dict[str, int] | None) -> None:
    with _lock:
        _cache[key] = (time.monotonic(), files)


def files_for(source: str, repo: str) -> dict[str, int] | None:
    """`{文件路径: 字节数}`。**会阻塞**去问源(超时 6 秒),拿不到返回 None。

    用在"用户已经在等"的地方(下载正要开始)。列卡片那种路径用 `cached_files`。
    """
    key = (source, repo)
    hit = _fresh(key)
    if hit is not _MISS:
        return hit  # type: ignore[return-value]
    files = _fetch(source, repo)
    _store(key, files)
    return files


def cached_files(source: str, repo: str) -> dict[str, int] | None:
    """**只看缓存,绝不在调用方线程里发请求**;缺了就在后台去问,并返回 None。

    列模型卡片是每开一次设置页都要跑的路径,而问源要走网络。同一个教训吃过一次:对话启动
    顺手查了一下模型目录,端点不可达时每句话都先卡满超时(见 ai/model_catalog.cached_models)。
    """
    key = (source, repo)
    hit = _fresh(key)
    if hit is not _MISS:
        return hit  # type: ignore[return-value]
    _refresh_soon(key)
    return None


def _refresh_soon(key: tuple[str, str]) -> None:
    with _lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run() -> None:
        try:
            _store(key, _fetch(*key))
        finally:
            with _lock:
                _refreshing.discard(key)

    threading.Thread(target=run, daemon=True, name="remote-size").start()


def total_bytes(files: dict[str, int] | None, patterns: Sequence[str] = ()) -> int | None:
    """这些文件里匹配 `patterns` 的总字节。`patterns` 为空表示**整个仓库**。

    匹配用 fnmatch:下载那一侧(snapshot_download 的 allow_patterns)用的就是这套通配。
    """
    if files is None:
        return None
    if not patterns:
        return sum(files.values())
    total = 0
    for path, size in files.items():
        if any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            total += size
    return total


def clear_cache() -> None:
    """测试用;生产不需要 —— TTL 到了自然刷新。"""
    with _lock:
        _cache.clear()
        _refreshing.clear()
