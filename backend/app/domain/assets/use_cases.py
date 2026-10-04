"""素材的用例:**谁能做**和**做什么**写在一起(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

每个函数第一个参数之后是行动人,自己过闸(`require_asset` / `ensure_workspace_*`),不提交事务。
HTTP 路由、智能体工具、工作流节点调同一个函数,走的就是同一道闸 —— 此前闸写在路由里,
别的入口要么经 HTTP 回连借路由的检查,要么各自补一份。

对外的领域错误(NotVisible / PermissionDenied / LocalizedError 家族)由 api 统一翻成状态码;
这里不认识 HTTP。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Job, Transcript, User
from app.domain.assets.deletion import Deleted, delete_asset as _delete
from app.domain.assets.project_scope import asset_project
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm, require_asset

#: 标签的长度上限;更长的截断。
TAG_MAX_CHARS = 40


# ---------------- 读 ----------------


def readable(db: Session, user: User, asset_id: str) -> Asset:
    """他看得到的一份素材(不是成员 / 不存在都是 404,见 NotVisible)。"""
    return require_asset(db, user, asset_id)


def readable_file(db: Session, user: User, asset_id: str) -> Asset:
    """他看得到、且底下有文件的素材 —— 取文件、预览、缩略图、帧条、波形、代理都从这里进。"""
    asset = db.get(Asset, asset_id)
    if asset is None or not asset.file_key:
        raise NotVisible("Not found")
    ensure_workspace_access(db, user, asset.workspace_id)
    return asset


def lineage(db: Session, user: User, asset_id: str) -> dict[str, Any]:
    """这份素材的来源链(他看得到这份素材才行;出处和它在同一个工作区)。"""
    from app.domain.assets.lineage import lineage_tree

    asset = require_asset(db, user, asset_id)
    return {"asset_id": asset.id, "ai_generated": bool(asset.ai_generated), "parents": lineage_tree(db, asset)}


def list_assets(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    project_id: str | None = None,
    kind: str | None = None,
    name_contains: str | None = None,
) -> list[Asset]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Asset).where(Asset.workspace_id == workspace_id)
    if project_id:
        # 工作区级素材(project_id IS NULL)属于整个工作区,任何项目都该能用它 —— 否则从
        # 「素材」页导入的素材在剪辑页看不到(素材页按工作区列,剪辑页按项目过滤)。
        stmt = stmt.where(or_(Asset.project_id == project_id, Asset.project_id.is_(None)))
    if kind and kind != "all":
        stmt = stmt.where(Asset.kind == kind)
    if name_contains:
        stmt = stmt.where(Asset.name.contains(name_contains))
    return list(db.scalars(stmt.order_by(Asset.created_at.desc())))


def transcript_by_source(db: Session, user: User, workspace_id: str, url: str) -> Transcript | None:
    from app.domain.assets.source_url import find_transcript_by_source

    ensure_workspace_access(db, user, workspace_id)
    return find_transcript_by_source(db, workspace_id, url)


def transcript_of(db: Session, user: User, asset_id: str) -> Transcript | None:
    from app.domain.transcripts import get_transcript_for_asset

    readable(db, user, asset_id)
    return get_transcript_for_asset(db, asset_id)


def ensure_can_browse(db: Session, user: User, workspace_id: str) -> None:
    """只读地看这个工作区(链接识别这类不碰任何素材的查询)。"""
    ensure_workspace_access(db, user, workspace_id)


# ---------------- 改 ----------------


def clean_tags(tags: list[str]) -> list[str]:
    """标签去重且保序;空白标签直接丢弃,过长的截断。"""
    cleaned: list[str] = []
    for tag in tags:
        value = tag.strip()[:TAG_MAX_CHARS]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def update_asset(
    db: Session,
    user: User,
    asset_id: str,
    *,
    name: str | None = None,
    tags: list[str] | None = None,
    project_id: str | None = None,
) -> Asset:
    asset = require_asset(db, user, asset_id, perm="edit")
    if name is not None:
        asset.name = name
    if tags is not None:
        asset.tags = clean_tags(tags)
    if project_id is not None:
        # 跨工作区归档会让素材从原工作区消失 —— 拒绝而不是静默照做(见 assets/project_scope);
        # 空串 = 移出项目。
        asset.project_id = asset_project(db, asset.workspace_id, project_id)
    db.flush()
    return asset


def delete_asset(db: Session, user: User, asset_id: str) -> Deleted:
    """删除的三个后果(清文件、引用它的片段转脱机占位、受影响序列推版本号)全在 assets/deletion 一处。"""
    return _delete(db, require_asset(db, user, asset_id, perm="delete"))


def attach_transcript(db: Session, user: User, asset_id: str, **fields: Any) -> Transcript:
    """给素材挂一份逐字稿。素材不存在时交给 transcripts 说「找不到」(它有自己的错误与状态码)。"""
    from app.domain.transcripts import attach_transcript as attach
    from app.domain.transcripts import get_transcript_for_asset

    if db.get(Asset, asset_id) is not None:
        require_asset(db, user, asset_id, perm="edit")
    transcript = attach(db, asset_id=asset_id, **fields)
    return get_transcript_for_asset(db, asset_id) or transcript


def analyze(
    db: Session,
    user: User,
    asset_id: str,
    question: str,
    *,
    session_target: Any = None,
    profile_id: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """看图 / 看视频。分析记的那一笔用量跟调用方的事务走。

    `session_target`:智能体发起时,这次对话定下的连接、模型和视频分析方式(agent/analysis_target 解析,
    **由调用方**解析好传进来 —— 素材域不认识智能体会话,认识了就把 agent、画板、Blender 一起卷进包级的环)。
    给了它,调用方传的 mode 不作数:用户在会话里选定的方式不能被工具参数覆盖。
    """
    from app.domain.analysis.service import analyze_asset

    asset = require_asset(db, user, asset_id, perm="ai")
    if session_target is not None:
        return analyze_asset(
            db, asset, question, user_id=user.id, mode=session_target.mode,
            resolved_connection=session_target.connection, model=session_target.model, surface="automation",
        )
    return analyze_asset(db, asset, question, user_id=user.id, profile_id=profile_id, mode=mode)


def grab_frame(db: Session, user: User, asset_id: str, at: float, *, project_id: str | None = None) -> Asset:
    """取某一帧存成一份**新**素材;原素材不动。"""
    from app.domain.assets.frames import save_frame_as_asset

    asset = db.get(Asset, asset_id)
    if asset is None or not asset.file_key:
        raise NotVisible("Not found")
    ensure_workspace_perm(db, user, asset.workspace_id, "edit")
    return save_frame_as_asset(db, asset, at, project_id=project_id)


# ---------------- 导入 ----------------


def import_upload(db: Session, user: User, workspace_id: str, *, project_id: str | None, name: str | None, upload) -> Asset:
    from app.domain.assets.importer import import_uploaded_asset

    ensure_workspace_perm(db, user, workspace_id, "upload")
    return import_uploaded_asset(db, workspace_id=workspace_id, project_id=project_id, name=name, upload=upload)


def import_web_capture(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    project_id: str | None,
    upload,
    name: str | None,
    capture: str,
    page_url: str,
    page_title: str,
    captured_at: str,
    source_url: str = "",
) -> Asset:
    """内嵌浏览器里截的图、采的页面图片,带着出处入库(见 assets/web_capture)。

    先过闸、再看出处、最后才读字节:没权限或出处不像样的请求,一个字节都不落盘。
    """
    from app.domain.assets.web_capture import read_capped, register_web_capture, web_source

    ensure_workspace_perm(db, user, workspace_id, "upload")
    source = web_source(
        page_url=page_url, page_title=page_title, captured_at=captured_at, capture=capture, source_url=source_url,
    )
    data = read_capped(upload.file)
    return register_web_capture(db, workspace_id=workspace_id, project_id=project_id, data=data, source=source, name=name)


def import_local(db: Session, user: User, workspace_id: str, *, project_id: str | None, path: Path) -> Asset:
    """登记一个**已经放行过**的本机文件(路径的闸在 host_files,由调用方先过)。"""
    from app.domain.assets.importer import register_file_asset

    ensure_workspace_perm(db, user, workspace_id, "upload")
    return register_file_asset(
        db, workspace_id=workspace_id, project_id=project_id, source_path=path, name=path.name, source="imported",
    )


def ensure_can_import(db: Session, user: User, workspace_id: str) -> None:
    """能往这个工作区里放东西。探测链接也按它判:能看的人不等于能往这里塞东西。"""
    ensure_workspace_perm(db, user, workspace_id, "upload")


def import_from_url(db: Session, user: User, workspace_id: str, **request: Any) -> Job:
    from app.domain.assets.from_url import start_url_import

    ensure_workspace_perm(db, user, workspace_id, "upload")
    return start_url_import(db, workspace_id=workspace_id, created_by=user.id, **request)


# ---------------- 派生任务(产出新素材,原素材不动) ----------------


def start_transcription(db: Session, user: User, asset_id: str, *, language: str = "", engine: str = "") -> Job:
    from app.domain.voices.transcription import start_transcription as start

    require_asset(db, user, asset_id, perm="ai")
    return start(db, asset_id, created_by=user.id, language=language, engine=engine)


def start_gif(db: Session, user: User, asset_id: str, **options: Any) -> Job:
    from app.domain.assets.video_gif import start_video_to_gif

    return start_video_to_gif(db, asset=require_asset(db, user, asset_id, perm="edit"), created_by=user.id, **options)


def start_separation(db: Session, user: User, asset_id: str, *, engine: str = "") -> Job:
    from app.domain.assets.separation import start_separation_job

    return start_separation_job(db, asset=require_asset(db, user, asset_id, perm="edit"), created_by=user.id, engine=engine)


def start_denoise(db: Session, user: User, asset_id: str, *, engine: str, strength: Any) -> Job:
    from app.domain.assets.denoise import start_denoise_job

    asset = require_asset(db, user, asset_id, perm="edit")
    return start_denoise_job(db, asset=asset, created_by=user.id, engine=engine, strength=strength)


def regenerate_proxy(db: Session, user: User, asset_id: str) -> Job | None:
    from app.domain.assets.proxies import start_proxy_job

    return start_proxy_job(db, require_asset(db, user, asset_id, perm="edit"), created_by=user.id, force=True)
