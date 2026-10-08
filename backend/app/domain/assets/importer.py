from __future__ import annotations

import io
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

from app.core.uploads import UploadedFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, new_id
from app.domain.assets.lineage import Derivation, inherits_ai
from app.domain.assets.project_scope import asset_project
from app.media.paths import asset_dir, asset_key, resolve_key
from app.core.i18n import LocalizedError
from app.media.probe import declared_video, guess_kind, probe_media, remux_in_place, repackage_as_mp4
from app.domain.assets.proxies import start_proxy_job
from app.media.thumbnails import generate_thumbnail, thumbnail_path
from app.media.waveform import generate_waveform, waveform_path


class AssetFileTypeError(LocalizedError, ValueError):
    """这种文件素材库不收:不是图片、视频、音频,也不是认得的文档。"""

    status = 415


def _document_info(path: Path) -> dict:
    """文档在导入这一步只记格式和大小;页数、字数、封面由解析写(ADR 0031 §2)。"""
    return {"format": path.suffix.lower().lstrip("."), "size_bytes": path.stat().st_size}


def _probe_with_duration_repair(target: Path, kind: str) -> dict:
    """探测媒体信息;时长缺失的音视频(MediaRecorder 直录 webm 的已知形态)
    先无损 remux 补容器头再重探,后续缩略图/波形/剪辑都依赖时长。

    这里先只看**头里**有没有:probe_media 量得出没写在头里的时长,可浏览器不会 ——
    头不补,播放器里照样拖不动。补头失败时,重探仍会逐包量出真实时长。"""
    media_info = probe_media(target, measure_missing_duration=False)
    if kind != "image" and media_info.get("duration") is None:
        remux_in_place(target)
        media_info = probe_media(target)
    return media_info


#: 启动兜底补过、仍量不出时长的素材,`media_info` 里记这个键(值是 "failed",和 `proxy_status` 的 failed 同一个规矩:终态)。
DURATION_STATUS = "duration_status"


def reconcile_broken_media_info(db: Session) -> int:
    """启动兜底:修复 remux 修复上线前导入的坏素材(摄像头/录音直录 webm,
    media_info 缺 duration)。remux 是 `-c copy` 的 I/O 级操作,坏素材通常
    也只有零星几条,同步跑完即可;顺带补缺失的缩略图/波形。

    **每条最多试一次。** 补头、逐包量都量不出时长的(110 字节的坏录音),记 `duration_status: failed`,之后的启动跳过。
    此前没有「试过了」这回事:每次启动都对它跑两遍 ffmpeg 重封装、原地改写一遍这份文件 —— 换成一个几 GB、量不出时长的
    录屏,每次启动多等两遍整文件拷贝,壳一直转圈。"""
    repaired = 0
    for asset in db.scalars(select(Asset).where(Asset.kind.in_(("audio", "video")))):
        info = asset.media_info or {}
        if info.get("duration") is not None or info.get(DURATION_STATUS) == "failed" or not asset.file_key:
            continue
        source = resolve_key(asset.file_key)
        if not source.is_file():
            continue
        # 补头是尽力而为;补不上,probe_media 照样逐包量出时长,素材不该因此一直缺时长。
        remux_in_place(source)
        probed = probe_media(source)
        if probed.get("duration") is None:
            asset.media_info = {**info, DURATION_STATUS: "failed"}
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
    return repaired


def register_file_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    source_path: Path,
    name: str,
    source: str = "exported",
    derived_from: Sequence[Derivation] = (),
    ai_generated: bool = False,
    intermediate: str = "",
    move: bool = False,
) -> Asset:
    """把一个已经存在的本机文件登记进素材库(渲染成片、配音产出、AI 生成结果都走这条)。

    `move`:这个文件是调用方自己的中转(导出成片、生成下回来的、分离 / 降噪的产出、下载下来的),登记就是**搬进去**,
    不再整份复制一遍 —— 同一块盘上是一次改名。此前导出几个 GB 的成片要再占一倍的盘,复制到一半盘满,刚编完的成片在
    调用方的 finally 里被删掉(MED-6)。不是自己的文件(别人目录里的、用户指定的路径)不能搬。

    `derived_from`:它是从哪几份素材做出来的(见 domain/assets/lineage —— 截取、转 GIF、导出成片……
    **产出派生素材的地方都要说**,否则 AI 内容加工一道就认不出来了)。`ai_generated`:它自己就是 AI 生成 /
    合成的(生成任务的产出、合成配音);出处里有 AI 内容的不用说,登记时自己继承。`intermediate`:它是某道工序逐条
    做出来的零件(逐句配音的一句、对口型的一块……,见 domain/assets/intermediates)—— **做它的那道工序在这里说**,
    素材库就默认不列它。"""
    if move:
        return _import_stream(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            move_from=source_path,
            original=source_path.name,
            content_type=None,
            name=name,
            source=source,
            derived_from=derived_from,
            ai_generated=ai_generated,
            intermediate=intermediate,
        )
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
            derived_from=derived_from,
            ai_generated=ai_generated,
            intermediate=intermediate,
        )


def import_uploaded_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    upload: UploadedFile,
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
    stream: BinaryIO | None = None,
    move_from: Path | None = None,
    original: str,
    content_type: str | None,
    name: str | None,
    source: str = "imported",
    derived_from: Sequence[Derivation] = (),
    ai_generated: bool = False,
    intermediate: str = "",
) -> Asset:
    """**有字节的素材**入库的唯一实现:落盘 → 探测 → 缩略图/波形 → 建记录 → 起 proxy。

    三个入口(浏览器上传、本机路径注册、渲染/配音/生成产出的文件)只在「字节从哪来」和
    source 标签上不同,后面的步骤完全一样。曾经上传走一份、按路径注册走另一份逐行重复的副本,
    改探测逻辑要记得改两处 —— 现在只有这一处。

    **但它不是 Asset 行的唯一来源。** `POST /api/assets`(`routes/assets.py:create_asset`)直接
    `Asset(**body)` 建行,底下没有文件,也就没有探测、缩略图、波形和 proxy。全仓只有测试在调它
    (前端、智能体、扩展都不用),它同时也是数据归属棘轮那 11 处豁免之一。要么让它走这里,
    要么删掉 —— 在那之前,这句话得说全,否则下一个人会以为拿到 Asset 就一定有这些派生物。

    挂到哪个项目在**落盘之前**就判(见 project_scope):拒了的导入不该在磁盘上留下文件。

    **落了盘、行没进库,目录整个清掉。** 此前落盘之后任何一步出错(盘满、探测出错、提交时库被锁),文件就留在
    media/assets 下,没有任何一行指着它(MED-6)。行提交之后再出的错(起代理任务之类)不清 —— 行在,文件就得在。
    """
    project_id = asset_project(db, workspace_id, project_id)
    asset_id = new_id()
    target_dir = asset_dir(workspace_id, asset_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        asset = _store(db, target_dir, asset_id, workspace_id=workspace_id, project_id=project_id, stream=stream,
                       move_from=move_from, original=original, content_type=content_type, name=name, source=source,
                       derived_from=derived_from, ai_generated=ai_generated, intermediate=intermediate)
    except BaseException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    db.refresh(asset)
    # 代理转码只是 ffmpeg,不碰任何凭据、不花额度 —— 没有主体是如实的,不是漏填。
    start_proxy_job(db, asset, created_by=None)  # 720p preview proxy for the compositor (no-op unless video)
    if asset.kind == "document":
        #: 文档一进来就用**本地解析**解一遍(ADR 0031):不出本机、不花钱,智能体马上就能读。交给云端(MinerU)
        #: 必须是人点名的 —— 在素材详情里「用 ×× 重新解析」,这里不看他的默认。
        from app.domain.documents import LOCAL_PARSER
        from app.domain.documents.extraction import start_parse

        start_parse(db, asset, owner_user_id=None, provider_id=LOCAL_PARSER)
    return asset


def _store(
    db: Session,
    target_dir: Path,
    asset_id: str,
    *,
    workspace_id: str,
    project_id: str | None,
    stream: BinaryIO | None,
    move_from: Path | None,
    original: str,
    content_type: str | None,
    name: str | None,
    source: str,
    derived_from: Sequence[Derivation],
    ai_generated: bool,
    intermediate: str,
) -> Asset:
    """落盘 → 探测 → 缩略图 / 波形 → 建行、提交。出错由调用方清目录。"""
    target = target_dir / original
    if move_from is not None:
        #: 同一块盘上是一次改名;跨盘时 shutil.move 退回「复制再删源」。
        shutil.move(move_from, target)
    else:
        with target.open("wb") as out:
            shutil.copyfileobj(stream, out)

    kind = guess_kind(target, content_type)
    if kind == "document":
        media_info = _document_info(target)
    else:
        if kind == "video" and (repackaged := repackage_as_mp4(target)) is not None:
            # 录屏这类 .mov 在界面里拖进度条会卡住;原样换成 mp4 容器(见 repackage_as_mp4)。
            target, original = repackaged, repackaged.name
        media_info = _probe_with_duration_repair(target, kind)
        #: 不是认得的种类(扩展名、类型都没说是视频),也探不出画面和声音:不收 —— 此前一律兜底成视频。
        if kind == "video" and not declared_video(target, content_type) and not (
                media_info.get("duration") or media_info.get("width")):
            raise AssetFileTypeError("assetErr_unsupportedFileType", name=original)
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
        derived_from=[one.as_json() for one in derived_from],
        #: 含 AI 在这一刻定下:自己是 AI 做的,或继承出处的(见 lineage —— 导出时不再顺着来源链查库)。
        ai_generated=ai_generated or inherits_ai(db, derived_from),
        intermediate=intermediate,
    )
    db.add(asset)
    # **这一笔提交是有意留下的**(入口层之外少数几处之一):字节已经落了盘,行跟着落库;调用方
    # 常常连着登记好几份(分离的两条 stem、宫格的九张、白模的首尾帧再加一段运镜),每一份之间
    # 还有探测、缩略图、波形、渲染这些慢活 —— 不在这里提交的话,SQLite 的写锁要一路攥到
    # 最后一份登记完,别的会话(任务进度)等过 busy_timeout 就报「database is locked」。
    db.commit()
    return asset

