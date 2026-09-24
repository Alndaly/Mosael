"""3D LUT (.cube) import + validation.

A .cube file is a plain-text 3D lookup table: a `LUT_3D_SIZE N` header plus
N³ rows of three floats. We validate the header and a plausible row count so a
bad upload is rejected here rather than blowing up ffmpeg mid-export."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Lut, new_id
from app.media.paths import lut_dir, lut_key

MAX_LUT_BYTES = 32 * 1024 * 1024  # generous: a 64³ cube is ~5 MB


class LutError(LocalizedError, ValueError):
    """Raised when an uploaded file is not a usable .cube LUT. 带文案 key(`lutErr_*`)。"""


def parse_cube_size(text: str) -> int:
    """Return the LUT_3D_SIZE declared in a .cube file, or raise LutError.

    Only 3D LUTs are supported (lut3d); a 1D LUT (LUT_1D_SIZE) is rejected."""
    size: int | None = None
    data_rows = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith("LUT_1D_SIZE"):
            raise LutError("lutErr_oneD")
        if upper.startswith("LUT_3D_SIZE"):
            parts = line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                raise LutError("lutErr_badSize")
            size = int(parts[1])
            continue
        # A data row is three numbers; keywords (TITLE/DOMAIN_*) are skipped.
        first = line.split()[0]
        if first[0].isdigit() or first[0] in "+-.":
            data_rows += 1
    if size is None:
        raise LutError("lutErr_noSize")
    if not (2 <= size <= 256):
        raise LutError("lutErr_sizeOutOfRange", size=size)
    if data_rows < size ** 3:
        raise LutError("lutErr_tooFewRows", expected=size ** 3, actual=data_rows)
    return size


def import_uploaded_lut(
    db: Session,
    *,
    workspace_id: str,
    upload: UploadFile,
    name: str | None = None,
) -> Lut:
    original = Path(upload.filename or "lut.cube").name
    if not original.lower().endswith(".cube"):
        raise LutError("lutErr_badType")
    # Bounded read: reading the whole body and THEN checking the cap means an oversized
    # upload exhausts memory before the limit meant to prevent that ever runs. One byte
    # over is enough to know it is over.
    raw = upload.file.read(MAX_LUT_BYTES + 1)
    if len(raw) > MAX_LUT_BYTES:
        raise LutError("lutErr_tooLarge")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise LutError("lutErr_notUtf8") from exc
    parse_cube_size(text)  # validates or raises

    lut_id = new_id()
    target_dir = lut_dir(workspace_id, lut_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / original
    target.write_bytes(raw)

    lut = Lut(
        id=lut_id,
        workspace_id=workspace_id,
        name=(name or original).strip() or original,
        original_filename=original,
        file_key=lut_key(workspace_id, lut_id, original),
        size=len(raw),
    )
    db.add(lut)
    db.commit()
    db.refresh(lut)
    return lut


def delete_lut_files(lut: Lut) -> None:
    from app.media.paths import resolve_key

    if lut.file_key:
        directory = resolve_key(lut.file_key).parent
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
