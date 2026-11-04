"""从一段视频素材里取一帧,存成一份新素材。时间线那边的「取播放头这一帧」见 domain/render.grab_sequence_frame。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import FRAME, derived
from app.media.paths import resolve_key
from app.media.probe import probe_picture_seconds
from app.media.still import grab_frame


class AssetFrameError(LocalizedError, ValueError):
    """这份素材取不了帧。api 回 400。"""


def last_frame_time(asset: Asset) -> float:
    """这段视频最后一帧在第几秒。留一帧半的余量:取帧的时间点压在片尾上时 ffmpeg 什么都取不到。"""
    info = asset.media_info or {}
    duration = float(info.get("duration") or 0)
    if not duration:
        raise AssetFrameError("assetErr_frameNoDuration")
    picture = probe_picture_seconds(resolve_key(asset.file_key)) if asset.file_key else None
    return max(0.0, min(duration, picture or duration) - 1.5 / float(info.get("fps") or 24))


def save_frame_as_asset(db: Session, asset: Asset, at: float, *, project_id: str | None) -> Asset:
    """取 `at` 秒处那一帧,存成新的一份(原素材不动)。`project_id` 没给就放进原素材所在的项目。
    取不出来抛 media.still.StillError。"""
    if asset.kind != "video":
        raise AssetFrameError("assetErr_framesOnlyFromVideo")
    with tempfile.TemporaryDirectory(prefix="mosael-still-") as tmp:
        target = Path(tmp) / "frame.jpg"
        grab_frame(resolve_key(asset.file_key), at, target)
        return register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=project_id or asset.project_id,
            source_path=target,
            #: 名字带上时间 —— 从同一段片子取三帧,光看「xxx 的帧」分不出哪张是哪张。
            name=f"{asset.name} · {at:.1f}s",
            source="generated",
            derived_from=derived(FRAME, asset.id),
        )
