from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, new_id
from app.media.paths import asset_dir, asset_key, resolve_key
from app.media.probe import guess_kind, probe_media, remux_in_place
from app.domain.assets.proxies import start_proxy_job
from app.media.thumbnails import generate_thumbnail, thumbnail_path
from app.media.waveform import generate_waveform, waveform_path


def _probe_with_duration_repair(target: Path, kind: str) -> dict:
    """探测媒体信息;时长缺失的音视频(MediaRecorder 直录 webm 的已知形态)
    先无损 remux 补容器头再重探,后续缩略图/波形/剪辑都依赖时长。"""
    media_info = probe_media(target)
    if kind != "image" and media_info.get("duration") is None and remux_in_place(target):
        media_info = probe_media(target)
    return media_info


def reconcile_broken_media_info(db: Session) -> int:
    """启动兜底:修复 remux 修复上线前导入的坏素材(摄像头/录音直录 webm,
    media_info 缺 duration)。remux 是 `-c copy` 的 I/O 级操作,坏素材通常
    也只有零星几条,同步跑完即可;顺带补缺失的缩略图/波形。"""
    repaired = 0
    for asset in db.scalars(select(Asset).where(Asset.kind.in_(("audio", "video")))):
        info = asset.media_info or {}
        if info.get("duration") is not None or not asset.file_key:
            continue
        source = resolve_key(asset.file_key)
        if not source.is_file():
            continue
        if not remux_in_place(source):
            continue
        probed = probe_media(source)
        if probed.get("duration") is None:
            continue
        directory = source.parent
        extras: dict = {}
        if not thumbnail_path(directory).is_file() and generate_thumbnail(source, asset.kind, directory) is not None:
            extras["has_thumbnail"] = True
        if not waveform_path(directory).is_file() and generate_waveform(source, asset.kind, directory) is not None:
            extras["has_waveform"] = True
        # 合并而不是替换:media_info 还承载 proxy 状态等旗标。
        asset.media_info = {**info, **probed, **extras}
        repaired += 1
    if repaired:
        db.commit()
    return repaired


def register_file_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    source_path: Path,
    name: str,
    source: str = "exported",
) -> Asset:
    """把一个已经存在的本机文件登记进素材库(渲染成片、配音产出、AI 生成结果都走这条)。"""
    with source_path.open("rb") as handle:
        return _import_stream(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            stream=handle,
            original=source_path.name,
            content_type=None,
            name=name,
            source=source,
        )


def import_uploaded_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    upload: UploadFile,
    name: str | None = None,
) -> Asset:
    return _import_stream(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        stream=upload.file,
        original=Path(upload.filename or "upload.bin").name,
        content_type=upload.content_type,
        name=name,
    )


def import_binary_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    data: bytes,
    original: str,
    content_type: str | None = None,
    source: str = "imported",
    name: str | None = None,
) -> Asset:
    """字节直接入库 —— 给"从别处取回来的一坨数据"用(飞书发来的图片是第一个)。

    没有新逻辑:它只是把 bytes 包成流交给 _import_stream。**不另写一份落盘/探测**,
    因为那正是这个模块存在的理由 —— 曾经上传和按路径注册各写一份,改探测要记得改两处。
    """
    return _import_stream(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        stream=io.BytesIO(data),
        original=Path(original).name,
        content_type=content_type,
        name=name,
        source=source,
    )


def _import_stream(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    stream: BinaryIO,
    original: str,
    content_type: str | None,
    name: str | None,
    source: str = "imported",
) -> Asset:
    """**有字节的素材**入库的唯一实现:落盘 → 探测 → 缩略图/波形 → 建记录 → 起 proxy。

    三个入口(浏览器上传、本机路径注册、渲染/配音/生成产出的文件)只在「字节从哪来」和
    source 标签上不同,后面的步骤完全一样。曾经上传走一份、按路径注册走另一份逐行重复的副本,
    改探测逻辑要记得改两处 —— 现在只有这一处。

    **但它不是 Asset 行的唯一来源。** `POST /api/assets`(`routes/assets.py:create_asset`)直接
    `Asset(**body)` 建行,底下没有文件,也就没有探测、缩略图、波形和 proxy。全仓只有测试在调它
    (前端、智能体、扩展都不用),它同时也是数据归属棘轮那 11 处豁免之一。要么让它走这里,
    要么删掉 —— 在那之前,这句话得说全,否则下一个人会以为拿到 Asset 就一定有这些派生物。
    """
    asset_id = new_id()
    target_dir = asset_dir(workspace_id, asset_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / original
    with target.open("wb") as out:
        shutil.copyfileobj(stream, out)

    kind = guess_kind(target, content_type)
    media_info = _probe_with_duration_repair(target, kind)
    if generate_thumbnail(target, kind, target_dir) is not None:
        media_info = {**media_info, "has_thumbnail": True}
    if generate_waveform(target, kind, target_dir) is not None:
        media_info = {**media_info, "has_waveform": True}
    asset = Asset(
        id=asset_id,
        workspace_id=workspace_id,
        project_id=project_id,
        kind=kind,
        source=source,
        name=(name or original).strip() or original,
        original_filename=original,
        file_key=asset_key(workspace_id, asset_id, original),
        media_info=media_info,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    # 代理转码只是 ffmpeg,不碰任何凭据、不花额度 —— 没有主体是如实的,不是漏填。
    start_proxy_job(db, asset, created_by=None)  # 720p preview proxy for the compositor (no-op unless video)
    return asset

