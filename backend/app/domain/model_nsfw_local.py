"""本机识别模型预览图是不是 NSFW(ADR 0038 §9 的第四种依据,「本地识别怎么带」那一节)。

**识别的是宿主已经缩好的缩略图**(长边 512 的 WebP,视频是它的第一帧;见 model_previews),不碰原图。结果按**缩略图内容的
SHA-256** 记在磁盘上(`<数据目录>/nsfw-classifier/scores-<版本>.json`)—— 同一张图换了名字、换了连接都不再算;换了模型版本
是另一个文件。

**列模型库不等它**:列的时候,缓存里有结果的带上(一条 `local` 依据:NSFW 的可能、过没过 0.5);缩略图已经有了、还没识别
的排进队里,一个后台线程一张一张地算(全进程同时只算一张),下次列出就有。缩略图是新缩出来的(卡片第一次露面)也排进去。
权重没下(见 ai/runtime/nsfw_models)就什么都不做;识别不出(图坏了)就不说话 —— 不当成「安全」。

**只是提示**:排在手动标记之下(model_library.nsfw_verdict),图、模型、结果都不出这台电脑。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image

from app.ai.runtime import nsfw_models

logger = logging.getLogger(__name__)

#: 过了这个就算「是」(模型自己的分界)
THRESHOLD = 0.5
#: 磁盘上最多记多少条结果(一条几十字节;超了丢最早记的)
MAX_SCORES = 50_000
#: 攒够几条写一次盘(队列空了也写)
_FLUSH_EVERY = 20

_lock = threading.Lock()
#: 缩略图内容的 SHA-256 → NSFW 的可能(0–1)。第一次用到时从盘上读
_scores: dict[str, float] | None = None
#: 识别不出的(图坏了):这次进程里不再排
_unreadable: set[str] = set()
#: 排着队的(内容哈希, 缩略图文件)和它们的哈希(不重复排)
_queue: deque[tuple[str, Path]] = deque()
_queued: set[str] = set()
#: 缩略图文件 → (修改时间, 大小, 内容哈希):列一次几百个文件,不必每次都把它们读一遍
_digests: dict[str, tuple[int, int, str]] = {}
#: 读进内存的权重(第一次识别时读,二十来 MB)
_weights: dict[str, Any] | None = None
_worker: threading.Thread | None = None
_dirty = 0


def scores_path() -> Path:
    return nsfw_models.root() / f"scores-{nsfw_models.REVISION[:12]}.json"


def _loaded() -> dict[str, float]:
    """拿着 `_lock` 调。"""
    global _scores
    if _scores is None:
        try:
            raw = json.loads(scores_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        _scores = {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))} if isinstance(raw, dict) else {}
    return _scores


def _digest(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path)
    with _lock:
        known = _digests.get(key)
    if known and known[0] == stat.st_mtime_ns and known[1] == stat.st_size:
        return known[2]
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    with _lock:
        _digests[key] = (stat.st_mtime_ns, stat.st_size, digest)
    return digest


def signal(thumbnail: Path | None) -> dict[str, Any] | None:
    """列模型库时调:这张缩略图的本机识别结果(一条 NSFW 依据),还没有就是 None。权重下好了、还没算过的排进队里。"""
    if thumbnail is None:
        return None
    digest = _digest(thumbnail)
    if digest is None:
        return None
    with _lock:
        score = _loaded().get(digest)
    if score is not None:
        return {"source": "local", "nsfw": score >= THRESHOLD, "score": round(score, 4)}
    _enqueue(digest, thumbnail)
    return None


def offer(thumbnail: Path) -> None:
    """一张缩略图刚缩出来:权重下好了就排进队里(卡片第一次露面时就开始算,不等下一次列)。"""
    if nsfw_models.ready():
        digest = _digest(thumbnail)
        if digest is not None:
            _enqueue(digest, thumbnail)


def _enqueue(digest: str, thumbnail: Path) -> None:
    global _worker
    if not nsfw_models.ready():
        return
    with _lock:
        if digest in _queued or digest in _unreadable or digest in _loaded():
            return
        _queue.append((digest, thumbnail))
        _queued.add(digest)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="model-nsfw-local")
            _worker.start()


def status() -> dict[str, int]:
    """排着队的、算过的各有几张(界面上「本机识别」那一行说进度用)。"""
    with _lock:
        return {"pending": len(_queued), "scored": len(_loaded())}


def _probability(thumbnail: Path) -> float:
    """一张缩略图是 NSFW 的可能。拿不到权重、图读不懂就抛。"""
    global _weights
    from app.ai.runtime import nsfw_vit

    if _weights is None:
        _weights = nsfw_vit.load(nsfw_models.weights_path())
    with Image.open(thumbnail) as image:
        image.load()
        return nsfw_vit.nsfw_probability(_weights, image)


def _work() -> None:
    """后台的那一个线程:一张一张地算,攒够几条写一次盘;队列空了写完就走(下次有新的再起一个)。"""
    global _dirty, _worker
    while True:
        with _lock:
            if not _queue:
                _worker = None  # 之后排进来的另起一个线程(这个只剩写盘)
                break
            digest, thumbnail = _queue.popleft()
        try:
            score: float | None = _probability(thumbnail)
        except Exception as exc:  # noqa: BLE001 — 一张图读不懂不该停下整个队列;不说话,不当成「安全」
            logger.info("本机识别没认出这张预览图(%s):%s", thumbnail.name, exc)
            score = None
        with _lock:
            _queued.discard(digest)
            if score is None:
                _unreadable.add(digest)
                continue
            _loaded()[digest] = score
            _dirty += 1
            flush = _dirty >= _FLUSH_EVERY
        if flush:
            _flush()
    _flush()


def _flush() -> None:
    """记着的结果写回盘上(临时文件再换上去);超了上限丢最早记的。"""
    global _dirty
    with _lock:
        if not _dirty or _scores is None:
            return
        while len(_scores) > MAX_SCORES:
            _scores.pop(next(iter(_scores)))
        snapshot = json.dumps(_scores, separators=(",", ":"))
        _dirty = 0
    target = scores_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.{os.getpid()}.part")
        partial.write_text(snapshot, encoding="utf-8")
        partial.replace(target)
    except OSError:
        logger.info("本机识别的结果没写下")


def wait_idle(timeout: float = 10.0) -> bool:
    """等队列空、线程走完(测试和核对用)。"""
    with _lock:
        worker = _worker
    if worker is not None:
        worker.join(timeout)
        return not worker.is_alive()
    return True


def forget() -> None:
    """忘掉内存里的(测试用它模拟重启):结果、哈希、读进来的权重;排着的丢掉。"""
    global _scores, _weights, _dirty
    wait_idle()
    with _lock:
        _scores = None
        _weights = None
        _dirty = 0
        _queue.clear()
        _queued.clear()
        _unreadable.clear()
        _digests.clear()
