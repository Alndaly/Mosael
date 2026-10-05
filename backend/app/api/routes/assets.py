from __future__ import annotations

import mimetypes
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import AssetFrameRequest, AnalyzeAssetRequest, AnalyzeAssetResponse, AssetFacetsOut, AssetLineageOut, AssetOut, AssetPageOut, AssetUpdate, DenoiseAssetRequest, JobOut, LocalImportRequest, TranscriptAttachRequest, TranscriptOut, UrlImportRequest, UrlProbeRequest, UrlProbeResponse, UrlSupportResponse, VideoToGifRequest
from app.domain.voices.transcription import ASRError
from app.db.models import Asset, Job, Transcript
from app.core.config import settings
from app.domain import host_files
from app.domain.assets import use_cases
from app.domain.assets.listing import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, AssetFacets, AssetListingError, AssetScope
from app.domain.transcripts.operations import SegmentIn, TokenIn, TranscriptDomainError
from app.media.image_preview import browser_compatible_image
from app.media.paths import resolve_key
from app.media.proxy import audio_proxy_path, proxy_path
from app.media.thumbnails import THUMBNAIL_MEDIA_TYPE, generate_thumbnail, thumbnail_path
from app.media.waveform import waveform_path

router = APIRouter(tags=["assets"])


@router.get("/assets/url-support", response_model=UrlSupportResponse)
def url_support(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    url: str = Query(min_length=4, max_length=2000),
) -> dict[str, str | bool]:
    """Classify a page through yt-dlp's registry without downloading it.

    This is intentionally distinct from ``probe-url``: the side panel only needs to know whether
    importing the active page is meaningful. It must not make the user wait for remote metadata.
    """
    use_cases.ensure_can_browse(db, user, workspace_id)
    from app.media.ytdlp import matching_extractor

    extractor = matching_extractor(url)
    return {"supported": extractor is not None, "extractor": extractor or ""}


@router.post("/assets/import", response_model=AssetOut)
def import_asset(
    db: Tx,
    user: CurrentUser,
    workspace_id: str = Form(...),
    project_id: str | None = Form(None),
    name: str | None = Form(None),
    file: UploadFile = File(...),
) -> Asset:
    return use_cases.import_upload(db, user, workspace_id, project_id=project_id, name=name, upload=file)


@router.post("/assets/capture", response_model=AssetOut)
def import_web_capture(
    db: Tx,
    user: CurrentUser,
    workspace_id: str = Form(...),
    capture: str = Form(..., max_length=40),
    page_url: str = Form(..., max_length=2000),
    page_title: str = Form("", max_length=1000),
    captured_at: str = Form(..., max_length=64),
    source_url: str = Form("", max_length=2000),
    project_id: str | None = Form(None),
    name: str | None = Form(None, max_length=400),
    file: UploadFile = File(...),
) -> Asset:
    """内嵌浏览器里截的图、采的页面图片入库,带着出处(来源网址、页面标题、截取时间、怎么截的)。

    只收图片、有大小上限、文件名由服务端定 —— 闸都在 domain/assets/web_capture。
    """
    from app.domain.assets.web_capture import WebCaptureError

    try:
        return use_cases.import_web_capture(
            db, user, workspace_id, project_id=project_id, upload=file, name=name, capture=capture,
            page_url=page_url, page_title=page_title, captured_at=captured_at, source_url=source_url,
        )
    except WebCaptureError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/assets/web-download", response_model=AssetOut)
def import_web_download(
    db: Tx,
    user: CurrentUser,
    workspace_id: str = Form(...),
    filename: str = Form(..., max_length=400),
    #: 页面脚本拼出来的下载(blob:、data:)没有能记的地址,就空着。
    source_url: str = Form("", max_length=2000),
    page_url: str = Form(..., max_length=2000),
    page_title: str = Form("", max_length=1000),
    captured_at: str = Form(..., max_length=64),
    project_id: str | None = Form(None),
    file: UploadFile = File(...),
) -> Asset:
    """用户在内嵌浏览器里点下载的文件入库(不弹系统保存框,下完直接进素材库),带着出处。

    大小上限、只收素材库认得的类型、文件名只取名字本身 —— 闸都在 domain/assets/web_download。
    """
    from app.domain.assets.web_capture import WebCaptureError

    try:
        return use_cases.import_web_download(
            db, user, workspace_id, project_id=project_id, upload=file, filename=filename, source_url=source_url,
            page_url=page_url, page_title=page_title, captured_at=captured_at,
        )
    except WebCaptureError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/assets/probe-url", response_model=UrlProbeResponse)
def probe_url(body: UrlProbeRequest, db: DbSession, user: CurrentUser) -> dict:
    """这个链接后面有什么 —— 只读元数据,不下载任何媒体流。

    **先探再下**:一个链接可能是一条视频,也可能是一整个播放列表。直接「粘链接就下」在单条时
    顺手,在播放列表上就是一次没人要的几十 GB。

    权限按 `upload` 判:探测本身只是出网读一份公开元数据,但它是导入的第一步,而能看的人不等于
    能往这个工作区里塞东西。
    """
    use_cases.ensure_can_import(db, user, body.workspace_id)
    from app.core.i18n import get_current_locale, t
    from app.domain.assets.from_url import probe_url as probe
    from app.media.ytdlp import YtdlpError

    from app.domain import sharing

    try:
        listing = probe(
            body.url, workspace_id=body.workspace_id, profile_id=body.profile_id or "", start=body.start,
            actor=user.id,
        )
    except sharing.NotUsableError as exc:
        # 别人的私有浏览器档案:借不了它的登录态。
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except YtdlpError as exc:
        # 出口才翻:领域抛的是原因 key,这里按请求方的 Accept-Language 渲染。
        raise HTTPException(status_code=422, detail=t(exc.key, get_current_locale(), **exc.params)) from exc
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
def import_from_url(body: UrlImportRequest, db: Tx, user: CurrentUser) -> Job:
    """把选中的条目下载进素材库。返回任务 —— 下载要跑一阵,不该占着一个请求。"""
    from app.domain import sharing
    from app.domain.assets.from_url import UrlImportError
    from app.domain.browser import BrowserDomainError

    try:
        return use_cases.import_from_url(
            db,
            user,
            body.workspace_id,
            project_id=body.project_id,
            items=[item.model_dump() for item in body.items],
            kind=body.kind,
            profile_id=body.profile_id,
            max_height=body.max_height,
        )
    except sharing.NotUsableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (UrlImportError, BrowserDomainError) as exc:
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
    db: Tx,
    user: CurrentUser,
) -> Asset:
    """按本机绝对路径导入(桌面端把文件拖到应用图标上 / 「用 Mosael 打开」)。

    **只在桌面端自带的后端上可用**。团队服务器部署没有 local_desktop 标记,这个接口直接
    404 —— 否则任何一个客户端都能让服务器去读它自己的文件系统,那是任意文件读取。
    标记由 Electron 在 spawn 后端时置入(见 electron/main.cjs)。
    """
    if not settings.local_desktop:
        raise HTTPException(status_code=404, detail="Not found")
    use_cases.ensure_can_import(db, user, body.workspace_id)

    # 桌面端的后端也可能被同事经远程访问连上 —— 这台电脑上的文件仍是部署主人的,
    # 读之前过同一道闸(见 domain/host_files)。放行的是**真实路径**:软链接名叫 .mp4 不算数。
    try:
        path = host_files.ensure_readable(db, body.path, actor=user.id).path
    except host_files.HostFileError as exc:
        raise HTTPException(status_code=422, detail=tr("routeErr_pathNotFile")) from exc
    if path.suffix.lower() not in _LOCAL_IMPORT_SUFFIXES:
        raise HTTPException(status_code=422, detail=tr("routeErr_unsupportedFileType", suffix=path.suffix))
    # 复用「登记一个已存在的本机文件」这条既有路径 —— 渲染成片、配音产出、AI 生成结果
    # 走的都是它。拖进来的文件只是 source 标签不同。
    return use_cases.import_local(db, user, body.workspace_id, project_id=body.project_id, path=path)


@router.get("/assets", response_model=AssetPageOut)
def list_assets(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = None,
    kind: Annotated[list[str] | None, Query()] = None,
    source: str | None = None,
    q: Annotated[str, Query(max_length=300)] = "",
    tag: Annotated[list[str] | None, Query()] = None,
    tag_match: Literal["all", "any"] = "all",
    intermediate: Annotated[str, Query(max_length=24)] = "",
    sort: Literal["created", "updated", "name", "duration"] = "created",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> dict:
    """素材库的一页:筛选、排序在服务端做,只带卡片字段(详情另取 `GET /api/assets/{id}`)。

    `kind` / `tag` 可以给几个(`?kind=video&kind=audio`)。翻下一页把上一页的 `next_cursor` 原样交回来,
    其余参数不变。中间产物(逐句配音的一句……)默认不列,`intermediate=dub_line` 只列那一种。
    """
    scope = AssetScope(
        workspace_id=workspace_id, project_id=project_id, kinds=tuple(kind or ()), source=source or None,
        query=q, tags=tuple(tag or ()), tag_match=tag_match, intermediate=intermediate,
    )
    try:
        found = use_cases.list_assets(db, user, scope, sort=sort, cursor=cursor, limit=limit)
    except AssetListingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"items": found.items, "next_cursor": found.next_cursor, "total": found.total}


@router.get("/assets/facets", response_model=AssetFacetsOut)
def asset_facets(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = None,
    intermediate: Annotated[str, Query(max_length=24)] = "",
) -> AssetFacets:
    """页签上的数字和标签筛选的候选:每种各几份、每个标签挂在几份上(整个范围,不看搜索);
    另有每种中间产物各几份。"""
    try:
        return use_cases.asset_facets(db, user, workspace_id, project_id=project_id, intermediate=intermediate)
    except AssetListingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/sequences/{sequence_id}/assets", response_model=list[AssetOut])
def sequence_assets(sequence_id: str, db: DbSession, user: CurrentUser) -> list[Asset]:
    """这条时间线上用到的素材,完整字段(剪辑台的时间线、监视器、检查器读它)。"""
    return use_cases.assets_on_sequence(db, user, sequence_id)


@router.get("/assets/transcript-by-source", response_model=TranscriptOut)
def get_transcript_by_source(workspace_id: str, url: str, db: DbSession, user: CurrentUser) -> Transcript:
    """Resolve a completed transcript for a previously imported video URL."""
    transcript = use_cases.transcript_by_source(db, user, workspace_id, url)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: DbSession, user: CurrentUser) -> Asset:
    # 单资产详情。前端 MediaPreview / 智能体工具卡靠它拉元数据;缺这个路由会 404,
    # 卡片就一直显示「素材不可用」。
    return use_cases.readable(db, user, asset_id)


@router.get("/assets/{asset_id}/lineage", response_model=AssetLineageOut)
def get_asset_lineage(asset_id: str, db: DbSession, user: CurrentUser) -> dict:
    """来源链:这份素材是从哪几份、经过什么操作做出来的,一级一级往上(素材详情里的「来自」)。"""
    return use_cases.lineage(db, user, asset_id)


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: str, body: AssetUpdate, db: Tx, user: CurrentUser) -> Asset:
    return use_cases.update_asset(db, user, asset_id, name=body.name, tags=body.tags, project_id=body.project_id)


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str, db: Tx, user: CurrentUser) -> Response:
    use_cases.delete_asset(db, user, asset_id)
    return Response(status_code=204)


@router.post("/assets/{asset_id}/analyze", response_model=AnalyzeAssetResponse)
def analyze_asset_route(
    asset_id: str,
    body: AnalyzeAssetRequest,
    db: Tx,
    user: CurrentUser,
) -> AnalyzeAssetResponse:
    """Analyze an existing image or video with the independently selected analysis profile.

    The agent does not come through here: its analyze_asset tool derives the connection, model and
    video mode from its own conversation. OAuth image/video-frame input uses the tool-free Gateway
    and never requires a caller-supplied service address.
    """
    from app.domain.analysis.service import AnalysisError

    # 智能体看素材走 analyze_asset 这个工具(用这次对话的连接、模型和视频分析方式,见 mcp_server);
    # 这条路由是人点的,用他单独选的分析配置。
    try:
        result = use_cases.analyze(db, user, asset_id, body.question, profile_id=body.profile_id, mode=body.mode)
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AnalyzeAssetResponse(**result)


@router.put("/assets/{asset_id}/transcript", response_model=TranscriptOut)
def put_transcript(asset_id: str, body: TranscriptAttachRequest, db: Tx, user: CurrentUser) -> Transcript:
    try:
        return use_cases.attach_transcript(
            db,
            user,
            asset_id,
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
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/transcribe", response_model=JobOut)
def transcribe_asset(
    asset_id: str,
    db: Tx,
    user: CurrentUser,
    language: str = "",
    engine: str = "",
):
    """`language` 空 = 由引擎自动检测;`engine` 是转写提供方 id(`builtin:funasr`、插件连接 id),空 = 按这个人的默认。

    语言只传给识别模型,不暗中切换引擎。挑法见 `transcription.transcriber`(ADR 0032)。
    """
    try:
        return use_cases.start_transcription(db, user, asset_id, language=language, engine=engine)
    except ASRError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/convert-gif", response_model=JobOut)
def convert_asset_to_gif(asset_id: str, body: VideoToGifRequest, db: Tx, user: CurrentUser) -> Job:
    """Create a **new** GIF asset. The source video remains untouched."""
    from app.domain.assets.video_gif import VideoGifError

    try:
        return use_cases.start_gif(
            db,
            user,
            asset_id,
            fps=body.fps,
            width=body.width,
            start=body.start,
            duration=body.duration,
        )
    except VideoGifError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/separate", response_model=JobOut)
def separate_asset_audio(asset_id: str, db: Tx, user: CurrentUser, engine: str = "") -> Job:
    """拆成人声 + 背景音两份**新**素材;原素材不动(ADR-0016)。

    排成任务而不是同步返回:一段长素材在 CPU 上要跑十几分钟,而那样长的 HTTP 请求会先被
    某一层断掉 —— 用户看到"失败了",后台其实还在跑。
    """
    from app.ai.providers.contracts.separation import SeparationError
    try:
        return use_cases.start_separation(db, user, asset_id, engine=engine)
    except SeparationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/denoise", response_model=JobOut)
def denoise_asset_audio(asset_id: str, body: DenoiseAssetRequest, db: Tx, user: CurrentUser) -> Job:
    """降噪,产出一份**新**素材;原素材不动(ADR-0017)。排成任务,理由同分离。"""
    from app.ai.providers.contracts.denoise import DenoiseError
    try:
        return use_cases.start_denoise(db, user, asset_id, engine=body.engine, strength=body.strength)
    except DenoiseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/transcript", response_model=TranscriptOut)
def get_transcript(asset_id: str, db: DbSession, user: CurrentUser) -> Transcript:
    transcript = use_cases.transcript_of(db, user, asset_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript


@router.get("/assets/{asset_id}/file")
def get_asset_file(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = use_cases.readable_file(db, user, asset_id)
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
    asset = use_cases.readable_file(db, user, asset_id)
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
    asset = use_cases.readable_file(db, user, asset_id)
    source = resolve_key(asset.file_key)
    thumb = thumbnail_path(source.parent)
    if not thumb.is_file():
        generate_thumbnail(source, asset.kind, source.parent)  # backfill for pre-thumbnail imports
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    return FileResponse(thumb, media_type=THUMBNAIL_MEDIA_TYPE)


@router.post("/assets/{asset_id}/frame", response_model=AssetOut)
def grab_asset_frame(asset_id: str, body: AssetFrameRequest, db: Tx, user: CurrentUser) -> Asset:
    """取这段视频的某一帧,存成一份新素材。

    **原素材不动**,产出是新的一份 —— 取帧是「我要这个画面」,不是「把这段片子变成一张图」。
    """
    from app.domain.assets.frames import AssetFrameError
    from app.media.still import StillError

    try:
        return use_cases.grab_frame(db, user, asset_id, body.at, project_id=body.project_id)
    except (AssetFrameError, StillError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/filmstrip")
def get_asset_filmstrip(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """剪辑面板用的帧条(一张横向长图)。**按需生成、落盘缓存** —— 和缩略图同一条路。"""
    from app.media.filmstrip import filmstrip_path, generate_filmstrip

    asset = use_cases.readable_file(db, user, asset_id)
    source = resolve_key(asset.file_key)
    strip = filmstrip_path(source.parent)
    if not strip.is_file():
        generate_filmstrip(source, asset.kind, source.parent)
    if not strip.is_file():
        raise HTTPException(status_code=404, detail="Filmstrip not available")
    return FileResponse(strip, media_type="image/jpeg")


@router.get("/assets/{asset_id}/waveform")
def get_asset_waveform(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = use_cases.readable_file(db, user, asset_id)
    waveform = waveform_path(resolve_key(asset.file_key).parent)
    if not waveform.is_file():
        raise HTTPException(status_code=404, detail="Waveform not available")
    return FileResponse(waveform, media_type="application/json")


@router.get("/assets/{asset_id}/proxy")
def get_asset_proxy(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """The 720p preview proxy the compositor decodes (see media/proxy.py)."""
    asset = use_cases.readable_file(db, user, asset_id)
    proxy = proxy_path(resolve_key(asset.file_key).parent)
    if not proxy.is_file():
        raise HTTPException(status_code=404, detail="Proxy not available")
    return FileResponse(proxy, media_type="video/mp4")


@router.get("/assets/{asset_id}/audio-proxy")
def get_asset_audio_proxy(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """预览混音器解的音频代理(AAC 48k,faststart,见 media/proxy.py)。

    按 Range 取:前端先读开头的样本表,再只取要播的那几段样本的字节,不把整份下下来。
    """
    asset = use_cases.readable_file(db, user, asset_id)
    proxy = audio_proxy_path(resolve_key(asset.file_key).parent)
    if not proxy.is_file():
        raise HTTPException(status_code=404, detail="Audio proxy not available")
    return FileResponse(proxy, media_type="audio/mp4")



@router.post("/assets/{asset_id}/proxy", response_model=JobOut)
def regenerate_asset_proxy(asset_id: str, db: Tx, user: CurrentUser):
    """Force a fresh proxy transcode (e.g. after a failed one)."""
    job = use_cases.regenerate_proxy(db, user, asset_id)
    if job is None:
        raise HTTPException(status_code=422, detail=tr("routeErr_noProxyForAsset"))
    return job
