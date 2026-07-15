from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.models import Asset, new_id
from app.media.paths import asset_dir, asset_key
from app.media.probe import guess_kind, probe_media
from app.media.thumbnails import generate_thumbnail


def register_file_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    source_path: Path,
    name: str,
    source: str = "exported",
) -> Asset:
    """Copy an existing local file into asset storage and register it."""
    asset_id = new_id()
    target_dir = asset_dir(workspace_id, asset_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source_path.name
    shutil.copy2(source_path, target)

    kind = guess_kind(target)
    media_info = probe_media(target)
    if generate_thumbnail(target, kind, target_dir) is not None:
        media_info = {**media_info, "has_thumbnail": True}
    asset = Asset(
        id=asset_id,
        workspace_id=workspace_id,
        project_id=project_id,
        kind=kind,
        source=source,
        name=name,
        original_filename=source_path.name,
        file_key=asset_key(workspace_id, asset_id, source_path.name),
        media_info=media_info,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def import_uploaded_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    upload: UploadFile,
    name: str | None = None,
) -> Asset:
    asset_id = new_id()
    original = Path(upload.filename or "upload.bin").name
    target_dir = asset_dir(workspace_id, asset_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / original
    with target.open("wb") as out:
        shutil.copyfileobj(upload.file, out)

    kind = guess_kind(target, upload.content_type)
    media_info = probe_media(target)
    if generate_thumbnail(target, kind, target_dir) is not None:
        media_info = {**media_info, "has_thumbnail": True}
    asset = Asset(
        id=asset_id,
        workspace_id=workspace_id,
        project_id=project_id,
        kind=kind,
        source="imported",
        name=(name or original).strip() or original,
        original_filename=original,
        file_key=asset_key(workspace_id, asset_id, original),
        media_info=media_info,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset

