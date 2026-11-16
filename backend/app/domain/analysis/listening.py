"""听素材(ADR 0103):过素材的读闸,取文件,按 (文件, 窗口, 期望, 测量版本) 缓存报告和频谱图。

测量本身在 `app.media.listening`(不认识数据库);这里只管「谁能听、听哪个文件、算过的别再算」。
住在分析域:和看图 / 看视频同一类「理解一份素材」的事,素材域不该回头认识分析(见 tests/test_import_layering)。

缓存放在素材自己的目录里(`listening/<键>.json|.png`),跟着素材一起删;键里带文件大小和修改时间,
素材文件被替换(裁剪、重新生成)后自然失效。
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Asset, User
from app.media.listening import MEASURE_VERSION, listen
from app.media.listening.compare import compare
from app.media.listening.decode import ListeningError
from app.media.listening.findings import Expect
from app.media.listening.spectrogram import spectrogram_png
from app.media.paths import resolve_key
from app.domain.permissions import require_asset

AUDIBLE_KINDS = frozenset({"audio", "video"})
MAX_CLIPS = 4


def listen_to_assets(
    db: Session,
    user: User,
    asset_ids: list[str],
    *,
    start: float = 0.0,
    end: float | None = None,
    expect: Expect = "any",
    with_spectrograms: bool = True,
) -> dict[str, Any]:
    """听 1–4 段素材。返回每段的报告(带素材 id 和名字)、两段以上时的比较,以及每段一张频谱图(PNG 的 base64)。"""
    if not asset_ids or len(asset_ids) > MAX_CLIPS:
        raise ListeningError("listenErr_tooMany", max=MAX_CLIPS)
    assets = [_audible(db, user, asset_id) for asset_id in dict.fromkeys(asset_ids)]
    reports = [
        #: `requested` 是这次问的窗口(不是量到的实际长度):界面拿它去取同一份缓存的频谱图。
        {"asset_id": asset.id, "name": asset.name, "requested": {"start": start, "end": end},
         **report_of(asset, start=start, end=end, expect=expect)}
        for asset in assets
    ]
    images = (
        [{"asset_id": asset.id, "view": asset.name, "mime_type": "image/png",
          "data": base64.b64encode(spectrogram_of(asset, start=start, end=end)).decode()} for asset in assets]
        if with_spectrograms else []
    )
    return {"listening": reports, "comparison": compare(reports) if len(reports) > 1 else [], "images": images}


def spectrogram_for(db: Session, user: User, asset_id: str, *, start: float = 0.0, end: float | None = None) -> bytes:
    """界面卡片上那张图:和交给模型的是同一份缓存。"""
    return spectrogram_of(_audible(db, user, asset_id), start=start, end=end)


def report_of(asset: Asset, *, start: float, end: float | None, expect: Expect) -> dict[str, Any]:
    cached = _cache_path(asset, "json", start, end, expect)
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    report = listen(_source(asset), start=start, end=end, expect=expect)
    _write(cached, json.dumps(report, ensure_ascii=False).encode())
    return report


def spectrogram_of(asset: Asset, *, start: float, end: float | None) -> bytes:
    cached = _cache_path(asset, "png", start, end, "")
    if cached.is_file():
        return cached.read_bytes()
    png = spectrogram_png(_source(asset), start=start, end=end)
    _write(cached, png)
    return png


def _audible(db: Session, user: User, asset_id: str) -> Asset:
    asset = require_asset(db, user, asset_id)
    if asset.kind not in AUDIBLE_KINDS or not asset.file_key:
        raise ListeningError("listenErr_notAudible", name=asset.name)
    return asset


def _source(asset: Asset) -> Path:
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise ListeningError("listenErr_decode")
    return path


def _cache_path(asset: Asset, suffix: str, start: float, end: float | None, expect: str) -> Path:
    source = _source(asset)
    stat = source.stat()
    key = f"{asset.file_key}|{stat.st_size}|{stat.st_mtime_ns}|{start:.3f}|{end}|{expect}|{MEASURE_VERSION}"
    return source.parent / "listening" / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.{suffix}"


def _write(path: Path, data: bytes) -> None:
    """先写临时文件再换名:两路同时听同一段时,谁也读不到写了一半的缓存。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    temporary.write_bytes(data)
    temporary.replace(path)
