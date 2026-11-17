"""从视频素材里抽出一条纯音频,存成新的音频素材。原视频不动。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import AUDIO, derived
from app.media.paths import resolve_key


class AudioExtractError(LocalizedError, ValueError):
    """抽不出音轨。带文案 key,按请求方语言翻。"""


def extract_audio_asset(db: Session, asset: Asset) -> Asset:
    """把视频里的声音拷成一份新的 m4a;音轨已经是 AAC 时直接拷贝,否则转一次。"""
    if asset.kind != "video":
        raise AudioExtractError("audioErr_extractNeedsVideo")
    if not asset.file_key:
        raise AudioExtractError("audioErr_noLocalFile")
    source = resolve_key(asset.file_key)
    if not source.is_file():
        raise AudioExtractError("audioErr_fileMissing")

    with tempfile.TemporaryDirectory(prefix="mosael-audio-") as tmp:
        target = Path(tmp) / f"{source.stem}.m4a"
        #: 先 `-c:a copy`:多数视频的声音本来就是 AAC,抽轨只是换容器,不该重编码。
        #: 有些容器 / 编解码器组合不能直接放进 m4a,这时才退回 AAC 转码。
        copied = _run(source, target, ["-c:a", "copy"])
        if not copied:
            _run(source, target, ["-c:a", "aac", "-b:a", "192k"])
        if not target.is_file() or target.stat().st_size == 0:
            raise AudioExtractError("audioErr_empty")

        made = register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=asset.project_id,
            source_path=target,
            name=f"{asset.name} · 音轨",
            source="generated",
            derived_from=derived(AUDIO, asset.id),
        )
    return made


def _run(source: Path, target: Path, codec: list[str]) -> bool:
    try:
        result = run_logged(
            [settings.ffmpeg, "-y", "-v", "error", "-i", str(source), "-vn", *codec, "-f", "mp4", str(target)],
            capture_output=True,
            text=True,
            timeout=900,
            what="抽取音轨",
        )
    except Exception as exc:
        raise AudioExtractError("audioErr_extract", detail=str(exc)) from exc
    if result.returncode != 0:
        return False
    return target.is_file() and target.stat().st_size > 0


__all__ = ["AudioExtractError", "extract_audio_asset"]
