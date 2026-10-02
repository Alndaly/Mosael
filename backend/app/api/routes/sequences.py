from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.i18n import tr
from app.domain.sequences import use_cases as sequence_use_cases
from app.api.deps import CurrentUser, DbSession, Tx
from app.core.unit_of_work import after_commit
from app.api.schemas import (
    AssetOut,
    SequenceFrameRequest,
    AddTrackRequest,
    CutClipRangeRequest,
    CutClipRangesRequest,
    CutClipRangesBatchRequest,
    ExportRequest,
    AppendAssetRequest,
    InsertClipRequest,
    InsertTextClipRequest,
    JobOut,
    MoveClipRequest,
    ClipIdsRequest,
    DuplicateClipsRequest,
    RippleDeleteClipsRequest,
    MoveClipsBatchRequest,
    SequenceCreate,
    SequenceOut,
    SubtitleImportOut,
    ReplaceClipMediaRequest,
    ClipAudioRequest,
    SetClipEffectsRequest,
    SetClipGainRequest,
    SetClipSpeedRequest,
    SetClipTransformRequest,
    SetSequenceReframeRequest,
    SetClipTextRequest,
    SetClipTextsRequest,
    SetSubtitleStyleRequest,
    SetTrackStateRequest,
    GenerateSubtitlesRequest,
    MoveTrackRequest,
    SplitClipPointsRequest,
    SplitClipPointsBatchRequest,
    SubtitleDubRequest,
    SplitClipRequest,
    TrimClipRequest,
)
from app.db.models import Asset, Job, Sequence, Track
from app.domain.permissions import require_sequence_access
from app.domain.render import start_export
from app.domain.sequences import concurrency
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound, SequenceRevisionConflict
from app.domain.sequences.history import can_redo, can_undo, redo as redo_operation, undo as undo_operation
from app.media.render_plan import RenderPlanError
from app.domain.sequences.operations import (
    AddTrack,
    CutClipRange,
    CutClipRanges,
    ClipRangeCuts,
    CutClipRangesBatch,
    DeleteClip,
    DeleteClipsBatch,
    DuplicateClips,
    RippleDeleteClipsBatch,
    InsertClip,
    GenerateSubtitles,
    InsertTextClip,
    ClipMove,
    MoveClip,
    MoveClipsBatch,
    MoveTrack,
    RemoveTrack,
    RippleDeleteClip,
    DetachClipAudio,
    SetClipEffects,
    SetClipGain,
    SetClipSpeed,
    SetClipTransform,
    SetSequenceReframe,
    SetClipText,
    SetClipTextsBatch,
    SetSubtitleStyle,
    SetTrackState,
    SplitClip,
    SplitClipPoints,
    ClipPointSplits,
    SplitClipPointsBatch,
    TrimClip,
    add_track as add_track_operation,
    cut_clip_range as cut_clip_range_operation,
    cut_clip_ranges as cut_clip_ranges_operation,
    cut_clip_ranges_batch as cut_clip_ranges_batch_operation,
    delete_clip as delete_clip_operation,
    delete_clips_batch as delete_clips_batch_operation,
    duplicate_clips as duplicate_clips_operation,
    ripple_delete_clips_batch as ripple_delete_clips_batch_operation,
    remove_track as remove_track_operation,
    ripple_delete_clip as ripple_delete_clip_operation,
    detach_clip_audio as detach_clip_audio_operation,
    set_clip_effects as set_clip_effects_operation,
    set_clip_gain as set_clip_gain_operation,
    set_clip_speed as set_clip_speed_operation,
    set_clip_transform as set_clip_transform_operation,
    set_sequence_reframe as set_sequence_reframe_operation,
    set_subtitle_style as set_subtitle_style_operation,
    set_track_state as set_track_state_operation,
    split_clip as split_clip_operation,
    split_clip_at_points as split_clip_points_operation,
    split_clip_points_batch as split_clip_points_batch_operation,
    insert_clip as insert_clip_operation,
    generate_subtitles as generate_subtitles_operation,
    insert_text_clip as insert_text_clip_operation,
    set_clip_text as set_clip_text_operation,
    set_clip_texts_batch as set_clip_texts_batch_operation,
    move_clip as move_clip_operation,
    move_clips_batch as move_clips_batch_operation,
    move_track as move_track_operation,
    trim_clip as trim_clip_operation,
)

router = APIRouter(tags=["sequences"])


@router.post("/sequences", response_model=SequenceOut)
def create_sequence(body: SequenceCreate, db: Tx, user: CurrentUser) -> Response:
    try:
        sequence = sequence_use_cases.create(
            db, user, body.workspace_id, body.project_id, name=body.name, width=body.width, height=body.height,
            fps=body.fps,
        )
    except SequenceDomainError as exc:  # 画幅 / 帧率越界(接口这层已挡过一道,领域层是给别的入口的)
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _get_sequence(db, sequence.id)


@router.get("/sequences/{sequence_id}", response_model=SequenceOut)
def get_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Response:
    return _sequence_response(sequence_use_cases.readable(db, user, sequence_id))


def _payload_shape_digest() -> str:
    """这个接口的响应**长什么样**的指纹 —— 由响应模型自己算出来,不是手写的常量。

    手写常量意味着"改了模型要记得改它",而忘记的代价是老客户端上功能凭空消失 —— 没人会想到
    去查缓存。让它跟着模型走,改模型就自动失效。
    """
    schema = json.dumps(SequenceOut.model_json_schema(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(schema.encode()).hexdigest()[:12]


#: 进程启动时算一次 —— 模型在运行期不会变。
_PAYLOAD_SHAPE = _payload_shape_digest()


@router.get("/projects/{project_id}/sequences", response_model=list[SequenceOut])
def list_sequences(project_id: str, request: Request, db: DbSession, user: CurrentUser) -> Response:
    # The editor polls this. Read the revisions first — a tiny scalar query — and only load the
    # full track/clip graph for sequences whose serialised form we do not already hold. Between
    # edits that turns a poll from "materialise 200 clips and encode them" into two dict lookups.
    ids_and_revisions = sequence_use_cases.revisions_of_project(db, user, project_id)
    stale = [sid for sid, revision in ids_and_revisions if _SEQUENCE_JSON.get(sid, (None,))[0] != revision]
    if stale:
        stmt = (
            select(Sequence)
            .where(Sequence.id.in_(stale))
            .options(selectinload(Sequence.tracks).selectinload(Track.clips))
        )
        for sequence in db.scalars(stmt):
            sequence.can_undo = can_undo(db, sequence.id)
            sequence.can_redo = can_redo(db, sequence.id)
            _sequence_json(sequence)  # populates the cache
    bodies = [_SEQUENCE_JSON[sid][1] for sid, _ in ids_and_revisions if sid in _SEQUENCE_JSON]

    # The cache above stops us REBUILDING an unchanged body; this stops us SENDING one. The
    # editor polls this endpoint continuously, and a 200-clip sequence is ~72KB — pushing that
    # through on every tick was the single biggest thing the poll cost, and the thing that made
    # concurrent polls collapse while a small endpoint at the same concurrency did not.
    # `revision` 说的是**数据**变没变;而 body 还取决于**序列化器**长什么样。只用 revision 的话,
    # 给 ClipOut 加一个字段之后:序列一个字没改 → ETag 不变 → 服务端一路回 304 → 浏览器一路用
    # 加字段之前的响应体。用户看到的不是"新字段没生效",而是**一个功能凭空消失**,而且刷新和
    # 重启后端都没用(重启只清进程内那层,清不掉浏览器里的)。这类 bug 发版之后才发作。
    # 把响应模型的形状摘要编进去:它变一次,所有 ETag 失效一次,正好是需要的粒度。
    etag = (
        'W/"'
        + _PAYLOAD_SHAPE
        + ':'
        + ".".join(f"{sid}-{revision}" for sid, revision in ids_and_revisions)
        + '"'
    )
    # no-cache means "store it, but revalidate every time" — which is what a polled endpoint
    # wants, and it makes the browser's revalidation deterministic instead of heuristic. The
    # 304 path is what the browser does with this automatically; JS still sees a 200 and the
    # cached body, so no caller has to change.
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(f"[{','.join(bodies)}]", media_type="application/json", headers=headers)


#: 编辑请求看到的是第几版(见 domain/sequences/concurrency)。落后了而这一步和中间那几步能交换就照做,
#: 否则 409 并附上最新的一版、说清是谁改的。不给就照现状做。
BaseRevision = Annotated[
    int | None,
    Query(description="这一步是照着第几版时间线做的。落后且与中间的改动冲突时回 409,detail 里带最新的序列。"),
]


@router.post("/sequences/{sequence_id}/append", response_model=SequenceOut)
def append_asset(
    sequence_id: str, body: AppendAssetRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """把整段素材接到它那种轨道的末尾;时间线还空着时画幅跟着它走(sequences.append)。"""
    from app.domain.sequences.append import append_asset as append

    require_sequence_access(db, user, sequence_id, perm="edit")
    actor = user.id

    def run() -> None:
        sequence = db.get(Sequence, sequence_id)
        if sequence is None:
            raise SequenceNotFound("Sequence not found")
        concurrency.run_on_base(
            db,
            sequence,
            lambda: append(db, sequence_id, body.asset_id, actor_id=actor),
            base_revision=base_revision,
            footprint=concurrency.POSITIONAL,
            actor_id=actor,
        )

    return _respond(db, user, sequence_id, run)


@router.post("/sequences/{sequence_id}/clips", response_model=SequenceOut)
def insert_clip(
    sequence_id: str, body: InsertClipRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = InsertClip(**body.model_dump())
    return _edit(db, user, sequence_id, base_revision, insert_clip_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/move", response_model=SequenceOut)
def move_clip(
    sequence_id: str, clip_id: str, body: MoveClipRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = MoveClip(clip_id=clip_id, **body.model_dump())
    return _edit(db, user, sequence_id, base_revision, move_clip_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/delete-batch", response_model=SequenceOut)
def delete_clips_batch(
    sequence_id: str, body: ClipIdsRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """多选后一次删除:一条操作,撤销一步全部找回。"""
    op = DeleteClipsBatch(clip_ids=tuple(body.clip_ids), linked=body.linked)
    return _edit(db, user, sequence_id, base_revision, delete_clips_batch_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/duplicate", response_model=SequenceOut)
def duplicate_clips(
    sequence_id: str, body: DuplicateClipsRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """复制几段片段(复制粘贴、Alt 拖复制):速度、调色、关键帧、文字……位置之外的一切照原样,
    放下是覆盖,整批一步撤销。"""
    op = DuplicateClips(clip_ids=tuple(body.clip_ids), timeline_start=body.timeline_start, track_id=body.track_id)
    return _edit(db, user, sequence_id, base_revision, duplicate_clips_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/ripple-delete-batch", response_model=SequenceOut)
def ripple_delete_clips_batch(
    sequence_id: str, body: RippleDeleteClipsRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """多选后一次波纹删除(后续左移补位;链接组员同删同移;all_tracks 时所有未锁定轨一起):一条操作、一步撤销。"""
    op = RippleDeleteClipsBatch(clip_ids=tuple(body.clip_ids), linked=body.linked, all_tracks=body.all_tracks)
    return _edit(db, user, sequence_id, base_revision, ripple_delete_clips_batch_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/move-batch", response_model=SequenceOut)
def move_clips_batch(
    sequence_id: str, body: MoveClipsBatchRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """框选后整组拖动:一次手势一条操作,撤销一步还原整组。"""
    op = MoveClipsBatch(moves=tuple(ClipMove(**move.model_dump()) for move in body.moves), linked=body.linked)
    return _edit(db, user, sequence_id, base_revision, move_clips_batch_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/trim", response_model=SequenceOut)
def trim_clip(
    sequence_id: str, clip_id: str, body: TrimClipRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = TrimClip(clip_id=clip_id, **body.model_dump())
    return _edit(db, user, sequence_id, base_revision, trim_clip_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/cut-ranges", response_model=SequenceOut)
def cut_clip_ranges_batch(
    sequence_id: str, body: CutClipRangesBatchRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    cuts = tuple(
        ClipRangeCuts(
            clip_id=cut.clip_id,
            ranges=tuple((item.src_start, item.src_end) for item in cut.ranges),
        )
        for cut in body.cuts
    )
    op = CutClipRangesBatch(cuts=cuts, linked=body.linked)
    return _edit(db, user, sequence_id, base_revision, cut_clip_ranges_batch_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/{clip_id}/cut-range", response_model=SequenceOut)
def cut_clip_range(
    sequence_id: str, clip_id: str, body: CutClipRangeRequest, db: Tx, user: CurrentUser, linked: bool = True,
    base_revision: BaseRevision = None,
) -> Response:
    """按文字剪的单个区间(波纹删除,见 cutting._ripple_cut)。`linked=false`:链接的音频不跟着剪。"""
    op = CutClipRange(clip_id=clip_id, linked=linked, **body.model_dump())
    return _edit(db, user, sequence_id, base_revision, cut_clip_range_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/{clip_id}/cut-ranges", response_model=SequenceOut)
def cut_clip_ranges(
    sequence_id: str, clip_id: str, body: CutClipRangesRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    ranges = tuple((item.src_start, item.src_end) for item in body.ranges)
    op = CutClipRanges(clip_id=clip_id, ranges=ranges, linked=body.linked)
    return _edit(db, user, sequence_id, base_revision, cut_clip_ranges_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/{clip_id}/split", response_model=SequenceOut)
def split_clip(
    sequence_id: str, clip_id: str, body: SplitClipRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SplitClip(clip_id=clip_id, **body.model_dump())
    return _edit(db, user, sequence_id, base_revision, split_clip_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/split-points", response_model=SequenceOut)
def split_clip_points_batch(
    sequence_id: str, body: SplitClipPointsBatchRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    splits = tuple(
        ClipPointSplits(clip_id=split.clip_id, src_times=tuple(split.src_times))
        for split in body.splits
    )
    op = SplitClipPointsBatch(splits=splits, linked=body.linked)
    return _edit(db, user, sequence_id, base_revision, split_clip_points_batch_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/{clip_id}/split-points", response_model=SequenceOut)
def split_clip_points(
    sequence_id: str, clip_id: str, body: SplitClipPointsRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    """Split one clip into pieces at several source-time cut points (transcript 按句切分)."""
    op = SplitClipPoints(clip_id=clip_id, src_times=tuple(body.src_times), linked=body.linked)
    return _edit(db, user, sequence_id, base_revision, split_clip_points_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/tracks/{track_id}", response_model=SequenceOut)
def set_track_state(
    sequence_id: str, track_id: str, body: SetTrackStateRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SetTrackState(track_id=track_id, **body.model_dump())
    return _edit(db, user, sequence_id, base_revision, set_track_state_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/tracks/{track_id}/move", response_model=SequenceOut)
def move_track(
    sequence_id: str, track_id: str, body: MoveTrackRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = MoveTrack(track_id=track_id, direction=body.direction)
    return _edit(db, user, sequence_id, base_revision, move_track_operation, op, perm="edit")


@router.put("/sequences/{sequence_id}/subtitle-style", response_model=SequenceOut)
def set_subtitle_style(
    sequence_id: str, body: SetSubtitleStyleRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = SetSubtitleStyle(style=body.style)
    return _edit(db, user, sequence_id, base_revision, set_subtitle_style_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/subtitles/generate", response_model=SequenceOut)
def generate_subtitles(
    sequence_id: str, body: GenerateSubtitlesRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """一键从逐字稿生成字幕:批量把句子插成字幕轨上的文本片段。"""
    cues = tuple((cue.text, cue.timeline_start, cue.duration) for cue in body.cues)
    op = GenerateSubtitles(track_id=body.track_id, cues=cues, replace=body.replace)
    return _edit(db, user, sequence_id, base_revision, generate_subtitles_operation, op, perm="edit")


#: 一份字幕文件最大多大。一部两小时电影的双语 SRT 也就几百 KB;再大多半是传错了文件。
_SUBTITLE_FILE_LIMIT = 5 * 1024 * 1024


@router.get("/sequences/{sequence_id}/subtitles/export")
def export_subtitles(
    sequence_id: str,
    db: DbSession,
    user: CurrentUser,
    track_id: str = Query(...),
    format: str = Query("srt"),
    line: str = Query("all"),
) -> Response:
    """一条字幕轨导出成 .srt / .vtt。双语字幕(两行)用 `line` 选全写、只写原文(first)或只写译文(last)。"""
    from app.domain.sequences.subtitle_io import export_track
    from app.domain.workflows.file_export import ascii_file_stem

    sequence = require_sequence_access(db, user, sequence_id)
    try:
        content = export_track(db, sequence_id, track_id, fmt=format, line=line)
    except SequenceDomainError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    suffix = f".{format}"
    media_type = "application/x-subrip" if format == "srt" else "text/vtt"
    return Response(
        content=content.encode("utf-8"),
        media_type=f"{media_type}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_file_stem(sequence.name)}{suffix}"; '
            f"filename*=UTF-8''{quote(sequence.name + suffix)}"
        },
    )


@router.post("/sequences/{sequence_id}/subtitles/import", response_model=SubtitleImportOut)
async def import_subtitles(
    sequence_id: str,
    db: Tx,
    user: CurrentUser,
    file: UploadFile = File(...),
    track_id: str = Form(""),
    offset: float = Form(0.0),
    replace: bool = Form(False),
    base_revision: BaseRevision = None,
) -> SubtitleImportOut:
    """读一份 .srt / .vtt 落到字幕轨上(`track_id` 空 = 新建一条)。整次导入是撤销栈上的一步。

    和别的编辑同一个并发协议(见 domain/sequences/concurrency):照着 `base_revision` 那一版做,落后了且和中间的
    改动对不上就 409 附最新序列。导入会建片段、覆盖落点,是依赖坐标的一步。"""
    from app.domain.sequences.subtitle_io import import_into_track
    from app.media.subtitle_files import SubtitleFileError

    require_sequence_access(db, user, sequence_id, perm="edit")
    data = await file.read(_SUBTITLE_FILE_LIMIT + 1)
    if len(data) > _SUBTITLE_FILE_LIMIT:
        raise HTTPException(status_code=413, detail=tr("subfileErr_tooLarge"))
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    try:
        result = concurrency.run_on_base(
            db,
            sequence,
            lambda: import_into_track(
                db, sequence_id, data, track_id=track_id, offset=offset, replace=replace, actor_id=user.id
            ),
            base_revision=base_revision,
            footprint=concurrency.POSITIONAL,
            actor_id=user.id,
        )
    except SubtitleFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SequenceRevisionConflict as exc:
        raise _conflict(db, sequence_id, exc) from exc
    except SequenceDomainError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return SubtitleImportOut(
        track_id=result.track_id,
        imported=result.imported,
        dropped=result.dropped,
        sequence=SequenceOut.model_validate(_get_sequence(db, sequence_id)),
    )


@router.post("/sequences/{sequence_id}/clips/replace-media", response_model=SequenceOut)
def replace_clip_media(
    sequence_id: str, body: ReplaceClipMediaRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """片段换成另一份素材(位置、时长、属性都不动)。给 `from_asset_id` 就换掉这条时间线上用着它的全部片段。"""
    from app.domain.sequences.media_swap import ReplaceClipMedia, clips_using
    from app.domain.sequences.media_swap import replace_clip_media as replace_media

    sequence = require_sequence_access(db, user, sequence_id, perm="edit")
    clip_ids = list(body.clip_ids) or (clips_using(sequence, body.from_asset_id) if body.from_asset_id else [])
    op = ReplaceClipMedia(clip_ids=tuple(clip_ids), asset_id=body.asset_id)
    return _edit(db, user, sequence_id, base_revision, replace_media, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/{clip_id}/audio", response_model=JobOut)
def process_clip_audio(
    sequence_id: str, clip_id: str, body: ClipAudioRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Job:
    """对片段做声音处理(降噪 / 只留人声 / 拆成人声和背景音),做完直接换到时间线上。排成任务:要跑好几分钟。"""
    from app.ai.providers.contracts.denoise import DenoiseError
    from app.domain.voices.clip_audio import ClipAudioError, start_clip_audio_job

    require_sequence_access(db, user, sequence_id, perm="edit")
    _ensure_seen(db, user, sequence_id, base_revision, [clip_id])
    try:
        return start_clip_audio_job(db, sequence_id=sequence_id, clip_id=clip_id, action=body.action, created_by=user.id)
    except (ClipAudioError, DenoiseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sequences/{sequence_id}/clips/{clip_id}", response_model=SequenceOut)
def delete_clip(
    sequence_id: str, clip_id: str, db: Tx, user: CurrentUser, linked: bool = True, base_revision: BaseRevision = None
) -> Response:
    """`linked=false`:只删这一段,链接的组员留着(「临时解链」)。"""
    op = DeleteClip(clip_id=clip_id, linked=linked)
    return _edit(db, user, sequence_id, base_revision, delete_clip_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/text-clips", response_model=SequenceOut)
def insert_text_clip(
    sequence_id: str, body: InsertTextClipRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = InsertTextClip(**body.model_dump())
    return _edit(db, user, sequence_id, base_revision, insert_text_clip_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/texts", response_model=SequenceOut)
def set_clip_texts(
    sequence_id: str, body: SetClipTextsRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    """Retext many clips in one revision — used by translate-whole-track. Registered BEFORE the
    single-clip route below so "texts" is not captured as a {clip_id}."""
    op = SetClipTextsBatch(texts=tuple((entry.clip_id, entry.text) for entry in body.texts))
    return _edit(db, user, sequence_id, base_revision, set_clip_texts_batch_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/text", response_model=SequenceOut)
def set_clip_text(
    sequence_id: str, clip_id: str, body: SetClipTextRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SetClipText(clip_id=clip_id, text=body.text)
    return _edit(db, user, sequence_id, base_revision, set_clip_text_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/speed", response_model=SequenceOut)
def set_clip_speed(
    sequence_id: str, clip_id: str, body: SetClipSpeedRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SetClipSpeed(clip_id=clip_id, **body.model_dump())
    return _edit(db, user, sequence_id, base_revision, set_clip_speed_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/gain", response_model=SequenceOut)
def set_clip_gain(
    sequence_id: str, clip_id: str, body: SetClipGainRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SetClipGain(clip_id=clip_id, gain=body.gain, muted=body.muted)
    return _edit(db, user, sequence_id, base_revision, set_clip_gain_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/clips/{clip_id}/detach-audio", response_model=SequenceOut)
def detach_clip_audio(
    sequence_id: str, clip_id: str, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = DetachClipAudio(clip_id=clip_id)
    return _edit(db, user, sequence_id, base_revision, detach_clip_audio_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/transform", response_model=SequenceOut)
def set_clip_transform(
    sequence_id: str, clip_id: str, body: SetClipTransformRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SetClipTransform(clip_id=clip_id, transform=body.transform)
    return _edit(db, user, sequence_id, base_revision, set_clip_transform_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/reframe", response_model=SequenceOut)
def set_sequence_reframe(
    sequence_id: str, body: SetSequenceReframeRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = SetSequenceReframe(width=body.width, height=body.height, fill_mode=body.fill_mode)
    return _edit(db, user, sequence_id, base_revision, set_sequence_reframe_operation, op, perm="edit")


@router.delete("/sequences/{sequence_id}/clips/{clip_id}/ripple", response_model=SequenceOut)
def ripple_delete_clip(
    sequence_id: str, clip_id: str, db: Tx, user: CurrentUser, linked: bool = True, all_tracks: bool = False,
    base_revision: BaseRevision = None,
) -> Response:
    """`linked=false` 只删这一段;`all_tracks=true` 这段时间从所有未锁定轨上拿掉(见 RippleDeleteClip)。"""
    op = RippleDeleteClip(clip_id=clip_id, linked=linked, all_tracks=all_tracks)
    return _edit(db, user, sequence_id, base_revision, ripple_delete_clip_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/tracks", response_model=SequenceOut)
def add_track(
    sequence_id: str, body: AddTrackRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Response:
    op = AddTrack(kind=body.kind, index=body.index)
    return _edit(db, user, sequence_id, base_revision, add_track_operation, op, perm="edit")


@router.delete("/sequences/{sequence_id}/tracks/{track_id}", response_model=SequenceOut)
def remove_track(
    sequence_id: str, track_id: str, db: Tx, user: CurrentUser, with_clips: bool = False,
    base_revision: BaseRevision = None,
) -> Response:
    """Remove a track. A track that still holds clips is refused unless with_clips says
    otherwise — the UI asks first and names how many clips would go with it."""
    op = RemoveTrack(track_id=track_id, with_clips=with_clips)
    return _edit(db, user, sequence_id, base_revision, remove_track_operation, op, perm="edit")


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/effects", response_model=SequenceOut)
def set_clip_effects(
    sequence_id: str, clip_id: str, body: SetClipEffectsRequest, db: Tx, user: CurrentUser,
    base_revision: BaseRevision = None,
) -> Response:
    op = SetClipEffects(clip_id=clip_id, effects=body.effects)
    return _edit(db, user, sequence_id, base_revision, set_clip_effects_operation, op, perm="edit")


@router.post("/sequences/{sequence_id}/undo", response_model=SequenceOut)
def undo_sequence(
    sequence_id: str, db: Tx, user: CurrentUser, expected_revision: int | None = None, mine: bool = False
) -> Response:
    """撤一步。`expected_revision`:调用方看到的是第几版(画板、剪辑页都带着它)。

    缺省撤整条时间线上最新的一步,版本对不上就 409(不撤别人的那一步)。`mine=true` 撤**这个人自己**最近的一步:
    其间别人的改动和它冲突就 409 并说清是谁;不冲突的话版本落后也照撤。409 的 detail 里带最新的序列。
    """
    require_sequence_access(db, user, sequence_id, perm="edit")
    return _respond(
        db, user, sequence_id,
        lambda: undo_operation(db, sequence_id, expected_revision=expected_revision, actor_id=user.id, mine=mine),
    )


@router.post("/sequences/{sequence_id}/redo", response_model=SequenceOut)
def redo_sequence(
    sequence_id: str, db: Tx, user: CurrentUser, expected_revision: int | None = None, mine: bool = False
) -> Response:
    """`expected_revision`、`mine` 同撤销。"""
    require_sequence_access(db, user, sequence_id, perm="edit")
    return _respond(
        db, user, sequence_id,
        lambda: redo_operation(db, sequence_id, expected_revision=expected_revision, actor_id=user.id, mine=mine),
    )


@router.post("/sequences/{sequence_id}/dub-subtitles", response_model=JobOut)
def dub_subtitles(
    sequence_id: str, body: SubtitleDubRequest, db: Tx, user: CurrentUser, base_revision: BaseRevision = None
) -> Job:
    """给选中的字幕条配音,产物落到一条新的音频轨。

    两道闸门都要过:配音**改这条时间线**(edit),也**花 AI 的钱**(ai)。少判一个,就等于让
    只读成员消费工作区的额度、或者让有额度的人改别人的片子。

    配哪几句是照着调用方看到的那一版选的(`base_revision`):那几条字幕(或那条字幕轨)在这之后被别人改过,
    就 409 附最新序列 —— 不按一份过时的选择去付费合成(见 _ensure_seen)。
    """
    from app.domain.voices import use_cases as voices
    from app.domain.voices.subtitle_dub import DubError, dub_targets
    from app.domain.voices.voices import VoiceError

    require_sequence_access(db, user, sequence_id, perm="edit")
    # 「碰过没有」按要配的那几条字幕算:没点名就是整条轨上现在的那些(改字的记录里只有片段 id,没有轨道 id),
    # 再加上轨道本身(删掉 / 新放上的字幕记录里带着轨道)。认不出要配哪几条的,留给下面说清楚原因。
    try:
        targets = dub_targets(db, sequence_id, list(body.clip_ids), body.track_id)
    except DubError:
        targets = list(body.clip_ids)
    _ensure_seen(db, user, sequence_id, base_revision, [*targets, body.track_id])
    try:
        return voices.dub_subtitles(db, user, sequence_id, **body.model_dump())
    except (DubError, VoiceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sequences/{sequence_id}/export", response_model=JobOut)
def export_sequence(sequence_id: str, db: Tx, user: CurrentUser, body: ExportRequest | None = None) -> Job:
    sequence_use_cases.exportable(db, user, sequence_id)
    try:
        return start_export(db, sequence_id, body.model_dump() if body else None, created_by=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RenderPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sequences/{sequence_id}/frame", response_model=AssetOut)
def grab_sequence_frame_route(
    sequence_id: str, body: SequenceFrameRequest, db: Tx, user: CurrentUser
) -> Asset:
    """取播放头这一帧,存成一份新素材。

    **走渲染那条路,不是抓预览的画布** —— 预览里花字和字幕是 DOM 叠上去的,画布抓不到它们:
    抓出来的画面看着对,只是少了一层字,而用户不会发现。
    """
    from app.domain.render import grab_sequence_frame
    from app.media.render_executor import RenderExecutionError

    sequence_use_cases.exportable(db, user, sequence_id)
    try:
        return grab_sequence_frame(db, sequence_id, body.at, created_by=user.id)
    except RenderPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RenderExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _edit(db, user, sequence_id: str, base_revision: int | None, handler, op, *, perm: str) -> Response:
    """一次编辑请求:过闸(权限由调用点点名)、记下是谁、照着它看到的那一版判断还能不能做(见 domain/sequences/concurrency)。"""
    require_sequence_access(db, user, sequence_id, perm=perm)
    return _respond(
        db, user, sequence_id,
        lambda: concurrency.apply_on_base(db, sequence_id, handler, op, base_revision=base_revision, actor_id=user.id),
    )


def _ensure_seen(db, user, sequence_id: str, base_revision: int | None, ids: list[str]) -> None:
    """排任务的编辑(配音、片段声音处理)也照着调用方看到的那一版:任务稍后才动时间线,但念哪几句、处理哪一段,
    是按他看到的那一版选的。那几段(或那条轨)在这之后被别人改过,就 409 附最新序列,不替他在一份过时的选择上花钱。
    只看点名的那几样有没有被碰过(见 concurrency.Footprint):别处的编辑不挡。"""
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    try:
        concurrency.run_on_base(
            db,
            sequence,
            lambda: None,
            base_revision=base_revision,
            footprint=concurrency.Footprint(coordinate_free=True, ids=frozenset(one for one in ids if one)),
            actor_id=user.id,
        )
    except SequenceRevisionConflict as exc:
        raise _conflict(db, sequence_id, exc) from exc


def _respond(db, user, sequence_id: str, run) -> Response:
    try:
        run()
    except SequenceRevisionConflict as exc:
        raise _conflict(db, sequence_id, exc) from exc
    except SequenceDomainError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _edited_response(db, sequence_id)


def _conflict(db, sequence_id: str, exc: SequenceRevisionConflict) -> HTTPException:
    """409 和画板、工作流的 409 同一个形状(code / base_revision / current_revision / message),**另带最新的序列** ——
    客户端拿它直接换掉手里那份过时的,而不是只弹一句「刷新后重试」。

    先回滚:这一步可能已经改了一半(版本号的 CAS 在记账那一刻才撞上),交回去的得是库里真有的那一版。
    """
    message = str(exc)
    db.rollback()
    latest = _get_sequence(db, sequence_id)
    return HTTPException(
        status_code=409,
        detail={
            "code": "sequence_revision_conflict",
            "message": message,
            "base_revision": exc.base_revision,
            "current_revision": latest.revision,
            "sequence": json.loads(_sequence_json(latest)),
        },
    )


# sequence_id -> (revision, serialised JSON). One entry per sequence, so it cannot grow with
# traffic. `revision` is a sound key: every mutation goes through _record_operation, which bumps
# it — and undo/redo record operations of their own, so even can_undo/can_redo cannot change
# without the revision changing with them.
_SEQUENCE_JSON: dict[str, tuple[int, str]] = {}


def _sequence_json(sequence: Sequence) -> str:
    cached = _SEQUENCE_JSON.get(sequence.id)
    if cached is not None and cached[0] == sequence.revision:
        return cached[1]
    body = SequenceOut.model_validate(sequence).model_dump_json()
    # A plain dict assignment is atomic under the GIL; two threads racing here just compute the
    # same bytes twice, which is cheaper than holding a lock on the hot path.
    _SEQUENCE_JSON[sequence.id] = (sequence.revision, body)
    return body


def _edited_response(db, sequence_id: str) -> Response:
    """改完之后的整条序列。**响应体照常算,缓存等提交之后再记。**

    这次编辑要到 Tx 收尾时才提交;提交失败的话,先记进去的 (revision, body) 就是一版没落库的
    时间线 —— 下一次真正走到这个 revision 的编辑会被轮询拿到这份旧的。
    """
    sequence = _get_sequence(db, sequence_id)
    cached = _SEQUENCE_JSON.get(sequence.id)
    if cached is not None and cached[0] == sequence.revision:
        return Response(cached[1], media_type="application/json")
    body = SequenceOut.model_validate(sequence).model_dump_json()
    entry = (sequence.id, sequence.revision, body)
    after_commit(db, lambda: _SEQUENCE_JSON.__setitem__(entry[0], (entry[1], entry[2])))
    return Response(body, media_type="application/json")


def _sequence_response(sequence: Sequence) -> Response:
    """Serialise a sequence ONCE, with Pydantic's own JSON writer.

    Returning the ORM object and letting `response_model` handle it costs the payload twice:
    Pydantic validates it into a model, then FastAPI's jsonable_encoder walks that whole model
    tree again turning it into JSON-compatible primitives. On a 200-clip sequence the encoder
    alone was ~48% of the request — 2.01ms of the 4.17ms — and being pure Python it is exactly
    the GIL-bound work that made throughput FALL as concurrency rose.

    Returning a Response makes FastAPI hand it straight to the transport, skipping both the
    re-validation and the encoder; model_dump_json does the encoding in Rust instead.
    `response_model` stays on the decorator, so the OpenAPI schema (and the generated TS
    client) is byte-for-byte unchanged.
    """
    return Response(_sequence_json(sequence), media_type="application/json")


def _get_sequence(db, sequence_id: str) -> Sequence:
    stmt = (
        select(Sequence)
        .where(Sequence.id == sequence_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
    )
    sequence = db.scalar(stmt)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    sequence.can_undo = can_undo(db, sequence_id)
    sequence.can_redo = can_redo(db, sequence_id)
    return sequence
