"""Subtitle font upload.

A font is stored per workspace and identified by the family name read out of its own `name`
table — not by its filename. That matters because the two consumers look it up differently:
the preview injects an @font-face whose `font-family` we choose, while export hands libass a
directory and a family name to match. Deriving both from the file's real family keeps the
burn-in identical to what you previewed."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.models import Font, new_id
from app.media.paths import font_dir, font_key

logger = logging.getLogger(__name__)

MAX_FONT_BYTES = 32 * 1024 * 1024
# woff/woff2 are deliberately absent: the browser reads them but libass/fontconfig does not,
# so accepting one would preview correctly and then silently export in a fallback face.
ALLOWED_FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc")


class FontError(ValueError):
    """Raised when an uploaded file is not a usable font."""


def read_font_family(path: Path, fallback: str) -> str:
    """The font's own family name, or `fallback` (the filename stem) if it can't be read.

    Prefers the typographic family (nameID 16) over the legacy family (1), since for a weighted
    family the legacy record says "Foo Light" where libass wants "Foo"."""
    try:
        from fontTools.ttLib import TTFont

        # Open the file here rather than handing TTFont a path: a mid-constructor failure on a
        # bogus upload otherwise leaves TTFont's own handle to the GC, and on Windows the still
        # open file blocks deletion. The with-block closes it either way.
        with open(path, "rb") as fh:
            font = TTFont(fh, fontNumber=0, lazy=True)
            try:
                names = font["name"].names
                for name_id in (16, 1, 4):
                    for record in names:
                        if record.nameID != name_id:
                            continue
                        value = record.toUnicode().strip()
                        if value:
                            return value
            finally:
                font.close()
    except Exception as exc:  # noqa: BLE001 — any malformed font falls back to the filename
        logger.warning("Could not read family name from %s: %s", path, exc)
    return fallback.rsplit(".", 1)[0] or "Custom Font"


def import_uploaded_font(db: Session, *, workspace_id: str, upload: UploadFile) -> Font:
    original = Path(upload.filename or "font.ttf").name
    if not original.lower().endswith(ALLOWED_FONT_SUFFIXES):
        raise FontError("只支持 .ttf / .otf / .ttc 字体文件(woff 无法用于导出)")
    raw = upload.file.read()
    if len(raw) > MAX_FONT_BYTES:
        raise FontError("字体文件过大(上限 32MB)")
    if not raw:
        raise FontError("字体文件为空")

    font_id = new_id()
    target_dir = font_dir(workspace_id, font_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / original
    target.write_bytes(raw)

    family = read_font_family(target, original)
    if not _is_readable_font(target):
        shutil.rmtree(target_dir, ignore_errors=True)
        raise FontError("无法解析该字体文件,请确认它没有损坏")

    font = Font(
        id=font_id,
        workspace_id=workspace_id,
        family=family,
        original_filename=original,
        file_key=font_key(workspace_id, font_id, original),
        size=len(raw),
    )
    db.add(font)
    db.commit()
    db.refresh(font)
    return font


def _is_readable_font(path: Path) -> bool:
    """Reject a file that only *looks* like a font. Without this the upload succeeds and the
    failure surfaces much later, as a silently wrong typeface in an exported video."""
    try:
        from fontTools.ttLib import TTFont

        with open(path, "rb") as fh:
            TTFont(fh, fontNumber=0, lazy=True).close()
        return True
    except ImportError:
        return True  # no fontTools available: accept and let the renderer decide
    except Exception:  # noqa: BLE001
        return False


def delete_font_files(font: Font) -> None:
    from app.media.paths import resolve_key

    if font.file_key:
        directory = resolve_key(font.file_key).parent
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
