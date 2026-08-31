from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, PresentedToken
from app.api.schemas import AssetFrameRequest, AnalyzeAssetRequest, AnalyzeAssetResponse, AssetCreate, AssetOut, AssetUpdate, JobOut, LocalImportRequest, TranscriptAttachRequest, TranscriptOut, UrlImportRequest, UrlProbeRequest, UrlProbeResponse, VideoToGifRequest
from app.domain.voices.service import AsrError, start_transcription
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm, require_asset
from app.db.models import Asset, Clip, Job, Transcript, Project
from app.core.config import settings
from app.domain.assets import import_uploaded_asset, register_file_asset
from app.domain.assets.proxies import start_proxy_job
from app.domain.transcripts import attach_transcript, get_transcript_for_asset
from app.domain.transcripts.operations import SegmentIn, TokenIn, TranscriptDomainError
from app.media.image_preview import browser_compatible_image
from app.media.paths import resolve_key
from app.media.proxy import proxy_path
from app.media.thumbnails import generate_thumbnail, thumbnail_path
from app.media.waveform import waveform_path

router = APIRouter(tags=["assets"])


@router.post("/assets", response_model=AssetOut)
def create_asset(body: AssetCreate, db: DbSession, user: CurrentUser) -> Asset:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    asset = Asset(**body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/import", response_model=AssetOut)
def import_asset(
    db: DbSession,
    user: CurrentUser,
    workspace_id: str = Form(...),
    project_id: str | None = Form(None),
    name: str | None = Form(None),
    file: UploadFile = File(...),
) -> Asset:
    ensure_workspace_perm(db, user, workspace_id, "upload")
    return import_uploaded_asset(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        upload=file,
    )


@router.post("/assets/probe-url", response_model=UrlProbeResponse)
def probe_url(body: UrlProbeRequest, db: DbSession, user: CurrentUser) -> dict:
    """这个链接后面有什么 —— 只读元数据,不下载任何媒体流。

    **先探再下**:一个链接可能是一条视频,也可能是一整个播放列表。直接「粘链接就下」在单条时
    顺手,在播放列表上就是一次没人要的几十 GB。

    权限按 `upload` 判:探测本身只是出网读一份公开元数据,但它是导入的第一步,而能看的人不等于
    能往这个工作区里塞东西。
    """
    ensure_workspace_perm(db, user, body.workspace_id, "upload")
    from app.media import ytdlp

    cookie_file = None
    workdir = None
    if body.profile_id:
        import tempfile
        from pathlib import Path as _Path

        from app.domain.assets.from_url import _cookie_file

        workdir = _Path(tempfile.mkdtemp(prefix="open-studio-probe-"))
        cookie_file = _cookie_file(body.workspace_id, body.profile_id, workdir)
    try:
        listing = ytdlp.probe(body.url.strip(), cookie_file=cookie_file, start=body.start)
    except ytdlp.YtdlpError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if workdir is not None:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)
    return {
        "title": listing.title,
        "is_playlist": listing.is_playlist,
        "truncated": listing.truncated,
        "start": listing.start,
        "entries": [
            {
                "id": entry.id,
                "url": entry.url,
                "title": entry.title,
                "duration": entry.duration,
                "uploader": entry.uploader,
                "thumbnail": entry.thumbnail,
                "heights": list(entry.heights),
            }
            for entry in listing.entries
        ],
    }


@router.post("/assets/import-url", response_model=JobOut)
def import_from_url(body: UrlImportRequest, db: DbSession, user: CurrentUser) -> Job:
    """把选中的条目下载进素材库。返回任务 —— 下载要跑一阵,不该占着一个请求。"""
    ensure_workspace_perm(db, user, body.workspace_id, "upload")
    from app.domain.assets.from_url import UrlImportError, start_url_import

    try:
        return start_url_import(
            db,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            items=[item.model_dump() for item in body.items],
            kind=body.kind,
            created_by=user.id,
            profile_id=body.profile_id,
            max_height=body.max_height,
        )
    except UrlImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# 桌面端拖进来的文件能有的后缀。白名单而不是"什么都收":这个接口收的是一个由客户端指定的
# **本机绝对路径**,能读什么必须收窄到媒体文件,不能变成一个通用的任意文件读取器。
_LOCAL_IMPORT_SUFFIXES = {
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi",
    ".mp3", ".wav", ".m4a", ".aac", ".flac",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
}


@router.post("/assets/import-local", response_model=AssetOut)
def import_local_asset(
    body: LocalImportRequest,
    db: DbSession,
    user: CurrentUser,
) -> Asset:
    """按本机绝对路径导入(桌面端把文件拖到应用图标上 / 「用 Open Studio 打开」)。

    **只在桌面端自带的后端上可用**。团队服务器部署没有 local_desktop 标记,这个接口直接
    404 —— 否则任何一个客户端都能让服务器去读它自己的文件系统,那是任意文件读取。
    标记由 Electron 在 spawn 后端时置入(见 electron/main.cjs)。
    """
    if not settings.local_desktop:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_perm(db, user, body.workspace_id, "upload")

    path = Path(body.path).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(status_code=422, detail="路径不存在或不是文件")
    if path.suffix.lower() not in _LOCAL_IMPORT_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型:{path.suffix}")
    # 复用「登记一个已存在的本机文件」这条既有路径 —— 渲染成片、配音产出、AI 生成结果
    # 走的都是它。拖进来的文件只是 source 标签不同。
    return register_file_asset(
        db,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        source_path=path,
        name=path.name,
        source="imported",
    )


@router.get("/assets", response_model=list[AssetOut])
def list_assets(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
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
    stmt = stmt.order_by(Asset.created_at.desc())
    return list(db.scalars(stmt))


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: DbSession, user: CurrentUser) -> Asset:
    # 单资产详情。前端 MediaPreview / 智能体工具卡靠它拉元数据;缺这个路由会 404,
    # 卡片就一直显示「素材不可用」。require_asset 已内含工作区访问校验。
    return require_asset(db, user, asset_id)


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: str, body: AssetUpdate, db: DbSession, user: CurrentUser) -> Asset:
    asset = require_asset(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "edit")
    if body.name is not None:
        asset.name = body.name
    if body.tags is not None:
        # 标签去重且保序;空白标签直接丢弃。
        cleaned: list[str] = []
        for tag in body.tags:
            value = tag.strip()[:40]
            if value and value not in cleaned:
                cleaned.append(value)
        asset.tags = cleaned
    if body.project_id is not None:
        target = body.project_id.strip()
        if target:
            project = db.get(Project, target)
            # 跨工作区归档会让素材从原工作区消失 —— 拒绝而不是静默照做。
            if project is None or project.workspace_id != asset.workspace_id:
                raise HTTPException(status_code=422, detail="项目不存在或不属于该工作区")
            asset.project_id = project.id
        else:
            asset.project_id = None  # 空串 = 移出项目
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str, db: DbSession, user: CurrentUser) -> Response:
    asset = require_asset(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "delete")
    in_use = db.scalar(select(Clip.id).where(Clip.asset_id == asset_id).limit(1))
    if in_use is not None:
        raise HTTPException(status_code=422, detail="素材正在时间线中使用，请先从时间线移除")
    file_dir = resolve_key(asset.file_key).parent if asset.file_key else None
    db.delete(asset)
    db.commit()
    if file_dir is not None and file_dir.is_dir():
        import shutil

        shutil.rmtree(file_dir, ignore_errors=True)
    return Response(status_code=204)


@router.post("/assets/{asset_id}/analyze", response_model=AnalyzeAssetResponse)
def analyze_asset_route(
    asset_id: str,
    body: AnalyzeAssetRequest,
    db: DbSession,
    user: CurrentUser,
    token: PresentedToken,
) -> AnalyzeAssetResponse:
    """Analyze an existing image or video.

    Ordinary authenticated HTTP requests use the independently selected analysis profile.
    Agent-tool service tokens are bound to an AgentSession, so the server derives the current
    provider, model, workspace and video mode from that session. OAuth image/video-frame input
    uses the tool-free Gateway and never requires a caller-supplied service address.
    """
    from app.domain.analysis.service import AnalysisError, analyze_asset

    asset = require_asset(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "ai")
    resolved_profile = None
    model = ""
    surface = "direct"
    mode = body.mode
    # 智能体工具回连携带的短期令牌绑定 agent_session_id。当前模型从这份服务端事实解析，
    # 不能让模型在工具参数里自报 profile/model —— 那既可伪造，也可能摸到别人的连接。
    from app.core.security import find_session
    from app.db.models import AgentSession

    auth = find_session(db, token)
    if auth is not None and auth.agent_session_id:
        session = db.get(AgentSession, auth.agent_session_id)
        if session is None or session.workspace_id != asset.workspace_id:
            raise HTTPException(status_code=422, detail="素材不属于当前智能体会话的工作区")
        from app.ai.sidecar.adapters import AdapterError
        from app.domain.agent.host import resolve_chat_provider

        try:
            _provider, model, resolved_profile = resolve_chat_provider(
                db,
                session.provider_profile_id,
                session.model or "",
                user_id=user.id,
            )
        except AdapterError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        surface = "automation"
        mode = session.analysis_video_mode or "auto"
    try:
        result = analyze_asset(
            db,
            asset,
            body.question,
            user_id=user.id,
            profile_id=None if resolved_profile is not None else body.profile_id,
            mode=mode,
            resolved_profile=resolved_profile,
            model=model,
            surface=surface,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 分析本身只读,但记了一笔用量;记账跟调用方事务走(见 domain/usage.billable),得落盘。
    db.commit()
    return AnalyzeAssetResponse(**result)


@router.put("/assets/{asset_id}/transcript", response_model=TranscriptOut)
def put_transcript(asset_id: str, body: TranscriptAttachRequest, db: DbSession, user: CurrentUser) -> Transcript:
    if db.get(Asset, asset_id) is not None:
        asset = require_asset(db, user, asset_id)
        ensure_workspace_perm(db, user, asset.workspace_id, "edit")
    try:
        transcript = attach_transcript(
            db,
            asset_id=asset_id,
            language=body.language,
            source=body.source,
            segments=[
                SegmentIn(
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    text=segment.text,
                    speaker=segment.speaker,
                    tokens=tuple(
                        TokenIn(start_time=token.start_time, end_time=token.end_time, text=token.text)
                        for token in segment.tokens
                    ),
                )
                for segment in body.segments
            ],
        )
    except TranscriptDomainError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 422
        raise HTTPException(status_code=status, detail=message) from exc
    return get_transcript_for_asset(db, asset_id) or transcript


@router.post("/assets/{asset_id}/transcribe", response_model=JobOut)
def transcribe_asset(asset_id: str, db: DbSession, user: CurrentUser, language: str = ""):
    """`language` 空 = 自动:WhisperX 自己检测,中文素材走 FunASR 的中文预设。

    说了具体语言就按它选引擎 —— FunASR 装的那套是中文权重,拿它转英文只会出一堆错字
    (见 service.resolve_asr_runtime)。
    """
    asset = require_asset(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "ai")
    try:
        return start_transcription(db, asset_id, created_by=user.id, language=language)
    except AsrError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/convert-gif", response_model=JobOut)
def convert_asset_to_gif(asset_id: str, body: VideoToGifRequest, db: DbSession, user: CurrentUser) -> Job:
    """Create a **new** GIF asset. The source video remains untouched."""
    from app.domain.assets.video_gif import VideoGifError, start_video_to_gif

    asset = require_asset(db, user, asset_id, perm="edit")
    try:
        return start_video_to_gif(
            db,
            asset=asset,
            created_by=user.id,
            fps=body.fps,
            width=body.width,
            start=body.start,
            duration=body.duration,
        )
    except VideoGifError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/transcript", response_model=TranscriptOut)
def get_transcript(asset_id: str, db: DbSession, user: CurrentUser) -> Transcript:
    require_asset(db, user, asset_id)
    transcript = get_transcript_for_asset(db, asset_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript


@router.get("/assets/{asset_id}/file")
def get_asset_file(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset file missing")
    media_type = mimetypes.guess_type(asset.original_filename or path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=asset.original_filename or path.name)


@router.get("/assets/{asset_id}/preview")
def get_asset_preview(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """A full-size browser-compatible representation of an image.

    The original file remains the download source. Unsupported browser containers such as HEIC
    are decoded into a cached JPEG, including for assets imported before this endpoint existed.
    """
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    if asset.kind != "image":
        raise HTTPException(status_code=422, detail="Preview is only available for image assets")
    source = resolve_key(asset.file_key)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Asset file missing")
    compatible = browser_compatible_image(source, source.parent)
    if compatible is None:
        raise HTTPException(status_code=422, detail="Image preview could not be generated")
    preview, media_type = compatible
    return FileResponse(preview, media_type=media_type)


@router.get("/assets/{asset_id}/thumbnail")
def get_asset_thumbnail(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    source = resolve_key(asset.file_key)
    thumb = thumbnail_path(source.parent)
    if not thumb.is_file():
        generate_thumbnail(source, asset.kind, source.parent)  # backfill for pre-thumbnail imports
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    return FileResponse(thumb, media_type="image/jpeg")


@router.post("/assets/{asset_id}/frame", response_model=AssetOut)
def grab_asset_frame(asset_id: str, body: AssetFrameRequest, db: DbSession, user: CurrentUser) -> Asset:
    """取这段视频的某一帧,存成一份新素材。

    **原素材不动**,产出是新的一份 —— 取帧是「我要这个画面」,不是「把这段片子变成一张图」。
    """
    import tempfile

    from app.media.still import StillError, grab_frame

    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "edit")
    if asset.kind != "video":
        raise HTTPException(status_code=400, detail="只能从视频里取帧")

    source = resolve_key(asset.file_key)
    with tempfile.TemporaryDirectory(prefix="open-studio-still-") as tmp:
        target = Path(tmp) / "frame.jpg"
        try:
            grab_frame(source, body.at, target)
        except StillError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=body.project_id or asset.project_id,
            source_path=target,
            #: 名字带上时间 —— 从同一段片子取三帧,光看「xxx 的帧」分不出哪张是哪张。
            name=f"{asset.name} · {body.at:.1f}s",
            source="generated",
        )


@router.get("/assets/{asset_id}/filmstrip")
def get_asset_filmstrip(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """剪辑面板用的帧条(一张横向长图)。**按需生成、落盘缓存** —— 和缩略图同一条路。"""
    from app.media.filmstrip import filmstrip_path, generate_filmstrip

    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    source = resolve_key(asset.file_key)
    strip = filmstrip_path(source.parent)
    if not strip.is_file():
        generate_filmstrip(source, asset.kind, source.parent)
    if not strip.is_file():
        raise HTTPException(status_code=404, detail="Filmstrip not available")
    return FileResponse(strip, media_type="image/jpeg")


@router.get("/assets/{asset_id}/waveform")
def get_asset_waveform(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    waveform = waveform_path(resolve_key(asset.file_key).parent)
    if not waveform.is_file():
        raise HTTPException(status_code=404, detail="Waveform not available")
    return FileResponse(waveform, media_type="application/json")


@router.get("/assets/{asset_id}/proxy")
def get_asset_proxy(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """The 720p preview proxy the compositor decodes (see media/proxy.py)."""
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    proxy = proxy_path(resolve_key(asset.file_key).parent)
    if not proxy.is_file():
        raise HTTPException(status_code=404, detail="Proxy not available")
    return FileResponse(proxy, media_type="video/mp4")



@router.post("/assets/{asset_id}/proxy", response_model=JobOut)
def regenerate_asset_proxy(asset_id: str, db: DbSession, user: CurrentUser):
    """Force a fresh proxy transcode (e.g. after a failed one)."""
    asset = require_asset(db, user, asset_id, perm="edit")
    job = start_proxy_job(db, asset, created_by=user.id, force=True)
    if job is None:
        raise HTTPException(status_code=422, detail="该素材不支持生成预览代理")
    return job


def _require_file_backed_asset(db: DbSession, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or not asset.file_key:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
