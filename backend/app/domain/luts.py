"""3D LUT (.cube) import + validation.

A .cube file is a plain-text 3D lookup table: a `LUT_3D_SIZE N` header plus
N³ rows of three floats. We validate the header and a plausible row count so a
bad upload is rejected here rather than blowing up ffmpeg mid-export."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.models import Lut, new_id
from app.media.paths import lut_dir, lut_key

MAX_LUT_BYTES = 32 * 1024 * 1024  # generous: a 64³ cube is ~5 MB


class LutError(ValueError):
    """Raised when an uploaded file is not a usable .cube LUT."""


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
            raise LutError("这是 1D LUT,导出仅支持 3D LUT(.cube)")
        if upper.startswith("LUT_3D_SIZE"):
            parts = line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                raise LutError(".cube 的 LUT_3D_SIZE 无效")
            size = int(parts[1])
            continue
        # A data row is three numbers; keywords (TITLE/DOMAIN_*) are skipped.
        first = line.split()[0]
        if first[0].isdigit() or first[0] in "+-.":
            data_rows += 1
    if size is None:
        raise LutError("不是有效的 .cube 文件(缺少 LUT_3D_SIZE)")
    if not (2 <= size <= 256):
        raise LutError(f"LUT_3D_SIZE={size} 超出支持范围 [2, 256]")
    if data_rows < size ** 3:
        raise LutError(f"数据行不足:期望 {size ** 3} 行,实际 {data_rows} 行")
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
        raise LutError("只支持 .cube 3D LUT 文件")
    raw = upload.file.read()
    if len(raw) > MAX_LUT_BYTES:
        raise LutError("LUT 文件过大(上限 32MB)")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise LutError(".cube 必须是 UTF-8 文本") from exc
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
