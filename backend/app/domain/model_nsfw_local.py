"""本机识别模型预览图是不是 NSFW(ADR 0038 §9 的第四种依据,「本地识别怎么带」那一节)。

**看的是手上最原样的那一张**,不是缩略图:那台服务器上的预览图有原文件(ComfyUI-Custom-Scripts 经 `/pysssss/view` 原样
交出,见 Source)就看原文件;没有就看宿主缓存里取回来的原样(Civitai 的示例图;ComfyUI 预览接口现转的 WebP);视频看
无损解出来的第一帧。沙盒实测:Big Buck Bunny 的兔脸特写,原 PNG 0.47、ComfyUI 转出来的 WebP 0.69、宿主再缩一次的
缩略图 0.78 —— 有损压缩一层层把一张卡通特写推过了 0.5。

结果按**缓存里那份原样的内容 SHA-256** 记在磁盘上(`<数据目录>/nsfw-classifier/scores-<版本>-original.json`)—— 同一张图
换了名字、换了连接都不再算;换了模型版本是另一个文件。此前按缩略图记的那一份(`scores-<版本>.json`)看的是有损的那张,
读的时候删掉、重新算。

**列模型库不等它**:列的时候,缓存里有结果的带上(一条 `local` 依据:NSFW 的可能、过没过 0.5);原样已经取回来了、还没
识别的排进队里,一个后台线程一张一张地算(全进程同时只算一张),下次列出就有。卡片第一次露面(缩略图刚缩出来)也排进去。
权重没下(见 ai/runtime/nsfw_models)就什么都不做;识别不出(图坏了)就不说话 —— 不当成「安全」。

**只是提示**:排在手动标记之下(model_library.nsfw_verdict),图、模型、结果都不出这台电脑。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.ai.runtime import nsfw_models
from app.domain import model_previews

logger = logging.getLogger(__name__)

#: 过了这个就算「是」(模型自己的分界)
THRESHOLD = 0.5
#: 磁盘上最多记多少条结果(一条几十字节;超了丢最早记的)
MAX_SCORES = 50_000
#: 攒够几条写一次盘(队列空了也写)
_FLUSH_EVERY = 20

@dataclass(frozen=True)
class Source:
    """要识别的那一张:宿主缓存里取回来的原样(`original`,图或视频,`kind` 是它的类型),结果按它的内容记;那台服务器上
    同一张图的原文件(`lossless`,有就看它,经这个连接的出站 `route` 去取,取不到退回缓存里那份)。"""

    original: Path
    kind: str
    instance_id: str = ""
    lossless: model_previews.Media | None = None
    route: Any = None


_lock = threading.Lock()
#: 缓存里那份原样内容的 SHA-256 → NSFW 的可能(0–1)。第一次用到时从盘上读
_scores: dict[str, float] | None = None
#: 识别不出的(图坏了):这次进程里不再排
_unreadable: set[str] = set()
#: 排着队的(内容哈希, 那一张)和它们的哈希(不重复排)
_queue: deque[tuple[str, Source]] = deque()
_queued: set[str] = set()
#: 原样文件 → (修改时间, 大小, 内容哈希):列一次几百个文件,不必每次都把它们读一遍
_digests: dict[str, tuple[int, int, str]] = {}
#: 读进内存的权重(第一次识别时读,二十来 MB)
_weights: dict[str, Any] | None = None
_worker: threading.Thread | None = None
_dirty = 0


def scores_path() -> Path:
    return nsfw_models.root() / f"scores-{nsfw_models.REVISION[:12]}-original.json"


def _loaded() -> dict[str, float]:
    """拿着 `_lock` 调。第一次读的时候删掉别的结果文件:按缩略图记的老的那一份、换掉的模型版本的。"""
    global _scores
    if _scores is None:
        for stale in nsfw_models.root().glob("scores-*.json"):
            if stale != scores_path():
                stale.unlink(missing_ok=True)
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


def signal(source: Source | None) -> dict[str, Any] | None:
    """列模型库时调:这一张的本机识别结果(一条 NSFW 依据),还没有就是 None。权重下好了、还没算过的排进队里。"""
    if source is None:
        return None
    digest = _digest(source.original)
    if digest is None:
        return None
    with _lock:
        score = _loaded().get(digest)
    if score is not None:
        return {"source": "local", "nsfw": score >= THRESHOLD, "score": round(score, 4)}
    _enqueue(digest, source)
    return None


def offer(source: Source) -> None:
    """卡片第一次露面(缩略图刚缩出来):权重下好了就排进队里,不等下一次列。"""
    if nsfw_models.ready():
        digest = _digest(source.original)
        if digest is not None:
            _enqueue(digest, source)


def _enqueue(digest: str, source: Source) -> None:
    global _worker
    if not nsfw_models.ready():
        return
    with _lock:
        if digest in _queued or digest in _unreadable or digest in _loaded():
            return
        _queue.append((digest, source))
        _queued.add(digest)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="model-nsfw-local")
            _worker.start()


def status() -> dict[str, int]:
    """排着队的、算过的各有几张(界面上「本机识别」那一行说进度用)。"""
    with _lock:
        return {"pending": len(_queued), "scored": len(_loaded())}


def _image(source: Source) -> Image.Image:
    """要看的那一张:有原文件先取原文件(取不到、不是图就退回缓存里那份);视频无损解出第一帧。读不懂就抛。"""
    if source.lossless is not None:
        try:
            fetched = model_previews.fetch_media(source.instance_id, source.route, source.lossless.url,
                                                 source.lossless.headers)
        except model_previews.PreviewNotNow:
            fetched = None
        if fetched is not None and fetched[1].startswith("image/"):
            image = Image.open(io.BytesIO(fetched[0]))
            image.load()
            return image
    data = source.original.read_bytes()
    if source.kind.startswith("video/"):
        frame = model_previews.first_frame(data)
        if frame is None:
            raise OSError("no first frame")
        return frame
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _probability(image: Image.Image) -> float:
    """一张图是 NSFW 的可能。拿不到权重就抛。"""
    global _weights
    from app.ai.runtime import nsfw_vit

    if _weights is None:
        _weights = nsfw_vit.load(nsfw_models.weights_path())
    return nsfw_vit.nsfw_probability(_weights, image)


def _work() -> None:
    """后台的那一个线程:一张一张地算,攒够几条写一次盘;队列空了写完就走(下次有新的再起一个)。"""
    global _dirty, _worker
    while True:
        with _lock:
            if not _queue:
                _worker = None  # 之后排进来的另起一个线程(这个只剩写盘)
                break
            digest, source = _queue.popleft()
        try:
            with _image(source) as image:
                score: float | None = _probability(image)
        except Exception as exc:  # noqa: BLE001 — 一张图读不懂不该停下整个队列;不说话,不当成「安全」
            logger.info("本机识别没认出这张预览图(%s):%s", source.original.name, exc)
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
