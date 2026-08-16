from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AddTrackRequest,
    CutClipRangeRequest,
    CutClipRangesRequest,
    ExportRequest,
    InsertClipRequest,
    InsertTextClipRequest,
    JobOut,
    MoveClipRequest,
    ClipIdsRequest,
    MoveClipsBatchRequest,
    SequenceCreate,
    SequenceOut,
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
    SubtitleDubRequest,
    SplitClipRequest,
    TrimClipRequest,
)
from app.db.models import Job, Project, Sequence, Track
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm, require_sequence_access
from app.domain.render import start_export
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.history import can_redo, can_undo, redo as redo_operation, undo as undo_operation
from app.media.render_plan import RenderPlanError
from app.domain.sequences.operations import (
    AddTrack,
    CutClipRange,
    CutClipRanges,
    DeleteClip,
    DeleteClipsBatch,
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
    TrimClip,
    add_track as add_track_operation,
    cut_clip_range as cut_clip_range_operation,
    cut_clip_ranges as cut_clip_ranges_operation,
    delete_clip as delete_clip_operation,
    delete_clips_batch as delete_clips_batch_operation,
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
def create_sequence(body: SequenceCreate, db: DbSession, user: CurrentUser) -> Response:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    # workspace_id was authorised, project_id was not — and the listing route filters only on
    # project_id, so pointing a sequence at someone else's project put attacker-controlled rows
    # (names, track and clip structure) inside a project they cannot otherwise touch.
    project = db.get(Project, body.project_id)
    if project is None or project.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="Project not found in this workspace")
    sequence = Sequence(**body.model_dump())
    video = Track(sequence=sequence, kind="video", name="V1", position=0)
    audio = Track(sequence=sequence, kind="audio", name="A1", position=1)
    db.add_all([sequence, video, audio])
    db.flush()  # the id is assigned on flush; assigning before it left active_sequence_id None
    if project.active_sequence_id is None:
        project.active_sequence_id = sequence.id
    db.commit()
    return _get_sequence(db, sequence.id)


@router.get("/sequences/{sequence_id}", response_model=SequenceOut)
def get_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id)
    return _sequence_response(_get_sequence(db, sequence_id))


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
    project = db.get(Project, project_id)
    if project is not None:
        ensure_workspace_access(db, user, project.workspace_id)
    # The editor polls this. Read the revisions first — a tiny scalar query — and only load the
    # full track/clip graph for sequences whose serialised form we do not already hold. Between
    # edits that turns a poll from "materialise 200 clips and encode them" into two dict lookups.
    ids_and_revisions = list(
        db.execute(
            select(Sequence.id, Sequence.revision)
            .where(Sequence.project_id == project_id)
            .order_by(Sequence.updated_at.desc())
        )
    )
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


@router.post("/sequences/{sequence_id}/clips", response_model=SequenceOut)
def insert_clip(sequence_id: str, body: InsertClipRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: insert_clip_operation(db, sequence_id, InsertClip(**body.model_dump())))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/move", response_model=SequenceOut)
def move_clip(sequence_id: str, clip_id: str, body: MoveClipRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: move_clip_operation(db, sequence_id, MoveClip(clip_id=clip_id, **body.model_dump())))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/delete-batch", response_model=SequenceOut)
def delete_clips_batch(sequence_id: str, body: ClipIdsRequest, db: DbSession, user: CurrentUser) -> Response:
    """多选后一次删除:一条操作,撤销一步全部找回。"""
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: delete_clips_batch_operation(db, sequence_id, DeleteClipsBatch(clip_ids=tuple(body.clip_ids))))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/ripple-delete-batch", response_model=SequenceOut)
def ripple_delete_clips_batch(sequence_id: str, body: ClipIdsRequest, db: DbSession, user: CurrentUser) -> Response:
    """多选后一次波纹删除(同轨后续左移补位):同样一条操作、一步撤销。"""
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(
        lambda: ripple_delete_clips_batch_operation(db, sequence_id, RippleDeleteClipsBatch(clip_ids=tuple(body.clip_ids)))
    )
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/move-batch", response_model=SequenceOut)
def move_clips_batch(sequence_id: str, body: MoveClipsBatchRequest, db: DbSession, user: CurrentUser) -> Response:
    """框选后整组拖动:一次手势一条操作,撤销一步还原整组。"""
    require_sequence_access(db, user, sequence_id, perm="edit")
    moves = tuple(ClipMove(**move.model_dump()) for move in body.moves)
    _apply(lambda: move_clips_batch_operation(db, sequence_id, MoveClipsBatch(moves=moves)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/trim", response_model=SequenceOut)
def trim_clip(sequence_id: str, clip_id: str, body: TrimClipRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: trim_clip_operation(db, sequence_id, TrimClip(clip_id=clip_id, **body.model_dump())))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/{clip_id}/cut-range", response_model=SequenceOut)
def cut_clip_range(sequence_id: str, clip_id: str, body: CutClipRangeRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: cut_clip_range_operation(db, sequence_id, CutClipRange(clip_id=clip_id, **body.model_dump())))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/{clip_id}/cut-ranges", response_model=SequenceOut)
def cut_clip_ranges(
    sequence_id: str, clip_id: str, body: CutClipRangesRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    ranges = tuple((item.src_start, item.src_end) for item in body.ranges)
    _apply(lambda: cut_clip_ranges_operation(db, sequence_id, CutClipRanges(clip_id=clip_id, ranges=ranges)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/{clip_id}/split", response_model=SequenceOut)
def split_clip(sequence_id: str, clip_id: str, body: SplitClipRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: split_clip_operation(db, sequence_id, SplitClip(clip_id=clip_id, src_time=body.src_time)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/{clip_id}/split-points", response_model=SequenceOut)
def split_clip_points(
    sequence_id: str, clip_id: str, body: SplitClipPointsRequest, db: DbSession, user: CurrentUser
) -> Response:
    """Split one clip into pieces at several source-time cut points (transcript 按句切分)."""
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: split_clip_points_operation(db, sequence_id, SplitClipPoints(clip_id=clip_id, src_times=tuple(body.src_times))))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/tracks/{track_id}", response_model=SequenceOut)
def set_track_state(
    sequence_id: str, track_id: str, body: SetTrackStateRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: set_track_state_operation(db, sequence_id, SetTrackState(track_id=track_id, **body.model_dump())))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/tracks/{track_id}/move", response_model=SequenceOut)
def move_track(sequence_id: str, track_id: str, body: MoveTrackRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: move_track_operation(db, sequence_id, MoveTrack(track_id=track_id, direction=body.direction)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.put("/sequences/{sequence_id}/subtitle-style", response_model=SequenceOut)
def set_subtitle_style(sequence_id: str, body: SetSubtitleStyleRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: set_subtitle_style_operation(db, sequence_id, SetSubtitleStyle(style=body.style)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/subtitles/generate", response_model=SequenceOut)
def generate_subtitles(sequence_id: str, body: GenerateSubtitlesRequest, db: DbSession, user: CurrentUser) -> Response:
    """一键从逐字稿生成字幕:批量把句子插成字幕轨上的文本片段。"""
    require_sequence_access(db, user, sequence_id, perm="edit")
    cues = tuple((cue.text, cue.timeline_start, cue.duration) for cue in body.cues)
    _apply(lambda: generate_subtitles_operation(db, sequence_id, GenerateSubtitles(track_id=body.track_id, cues=cues)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.delete("/sequences/{sequence_id}/clips/{clip_id}", response_model=SequenceOut)
def delete_clip(sequence_id: str, clip_id: str, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: delete_clip_operation(db, sequence_id, DeleteClip(clip_id=clip_id)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/text-clips", response_model=SequenceOut)
def insert_text_clip(sequence_id: str, body: InsertTextClipRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: insert_text_clip_operation(db, sequence_id, InsertTextClip(**body.model_dump())))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/texts", response_model=SequenceOut)
def set_clip_texts(sequence_id: str, body: SetClipTextsRequest, db: DbSession, user: CurrentUser) -> Response:
    """Retext many clips in one revision — used by translate-whole-track. Registered BEFORE the
    single-clip route below so "texts" is not captured as a {clip_id}."""
    require_sequence_access(db, user, sequence_id, perm="edit")
    texts = tuple((entry.clip_id, entry.text) for entry in body.texts)
    _apply(lambda: set_clip_texts_batch_operation(db, sequence_id, SetClipTextsBatch(texts=texts)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/text", response_model=SequenceOut)
def set_clip_text(
    sequence_id: str, clip_id: str, body: SetClipTextRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: set_clip_text_operation(db, sequence_id, SetClipText(clip_id=clip_id, text=body.text)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/speed", response_model=SequenceOut)
def set_clip_speed(
    sequence_id: str, clip_id: str, body: SetClipSpeedRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: set_clip_speed_operation(db, sequence_id, SetClipSpeed(clip_id=clip_id, speed=body.speed)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/gain", response_model=SequenceOut)
def set_clip_gain(
    sequence_id: str, clip_id: str, body: SetClipGainRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(
        lambda: set_clip_gain_operation(
            db, sequence_id, SetClipGain(clip_id=clip_id, gain=body.gain, muted=body.muted)
        )
    )
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/clips/{clip_id}/detach-audio", response_model=SequenceOut)
def detach_clip_audio(sequence_id: str, clip_id: str, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: detach_clip_audio_operation(db, sequence_id, DetachClipAudio(clip_id=clip_id)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/transform", response_model=SequenceOut)
def set_clip_transform(
    sequence_id: str, clip_id: str, body: SetClipTransformRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(
        lambda: set_clip_transform_operation(
            db, sequence_id, SetClipTransform(clip_id=clip_id, transform=body.transform)
        )
    )
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/reframe", response_model=SequenceOut)
def set_sequence_reframe(
    sequence_id: str, body: SetSequenceReframeRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(
        lambda: set_sequence_reframe_operation(
            db, sequence_id, SetSequenceReframe(width=body.width, height=body.height, fill_mode=body.fill_mode)
        )
    )
    return _sequence_response(_get_sequence(db, sequence_id))


@router.delete("/sequences/{sequence_id}/clips/{clip_id}/ripple", response_model=SequenceOut)
def ripple_delete_clip(sequence_id: str, clip_id: str, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: ripple_delete_clip_operation(db, sequence_id, RippleDeleteClip(clip_id=clip_id)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/tracks", response_model=SequenceOut)
def add_track(sequence_id: str, body: AddTrackRequest, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: add_track_operation(db, sequence_id, AddTrack(kind=body.kind)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.delete("/sequences/{sequence_id}/tracks/{track_id}", response_model=SequenceOut)
def remove_track(
    sequence_id: str, track_id: str, db: DbSession, user: CurrentUser, with_clips: bool = False
) -> Response:
    """Remove a track. A track that still holds clips is refused unless with_clips says
    otherwise — the UI asks first and names how many clips would go with it."""
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(
        lambda: remove_track_operation(db, sequence_id, RemoveTrack(track_id=track_id, with_clips=with_clips))
    )
    return _sequence_response(_get_sequence(db, sequence_id))


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/effects", response_model=SequenceOut)
def set_clip_effects(
    sequence_id: str, clip_id: str, body: SetClipEffectsRequest, db: DbSession, user: CurrentUser
) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: set_clip_effects_operation(db, sequence_id, SetClipEffects(clip_id=clip_id, effects=body.effects)))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/undo", response_model=SequenceOut)
def undo_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: undo_operation(db, sequence_id))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/redo", response_model=SequenceOut)
def redo_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Response:
    require_sequence_access(db, user, sequence_id, perm="edit")
    _apply(lambda: redo_operation(db, sequence_id))
    return _sequence_response(_get_sequence(db, sequence_id))


@router.post("/sequences/{sequence_id}/dub-subtitles", response_model=JobOut)
def dub_subtitles(sequence_id: str, body: SubtitleDubRequest, db: DbSession, user: CurrentUser) -> Job:
    """给选中的字幕条配音,产物落到一条新的音频轨。

    两道闸门都要过:配音**改这条时间线**(edit),也**花 AI 的钱**(ai)。少判一个,就等于让
    只读成员消费工作区的额度、或者让有额度的人改别人的片子。
    """
    sequence = require_sequence_access(db, user, sequence_id, perm="edit")
    ensure_workspace_perm(db, user, sequence.workspace_id, "ai")
    from app.audio.subtitle_dub import DubError, start_subtitle_dub

    synthesis = body.model_dump(exclude={"clip_ids", "match_duration", "line"})
    # 克隆引擎才认 voice_id,远端引擎才认 workspace_id —— 两边都传的话
    # start_synthesis 会收到它这条路上根本没有的参数。
    if body.engine == "clone":
        synthesis.pop("provider_profile_id", None)
        synthesis.pop("engine_model", None)
        synthesis.pop("engine_voice", None)
        synthesis.pop("engine_voice_resource", None)
    else:
        synthesis.pop("voice_id", None)
        synthesis.pop("clone_engine", None)
        synthesis.pop("clone_model", None)
        synthesis["workspace_id"] = sequence.workspace_id
    try:
        return start_subtitle_dub(
            db,
            sequence_id=sequence_id,
            clip_ids=list(body.clip_ids),
            match_duration=body.match_duration,
            line=body.line,
            created_by=user.id,
            synthesis=synthesis,
        )
    except DubError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sequences/{sequence_id}/export", response_model=JobOut)
def export_sequence(sequence_id: str, db: DbSession, user: CurrentUser, body: ExportRequest | None = None) -> Job:
    sequence = require_sequence_access(db, user, sequence_id)
    ensure_workspace_perm(db, user, sequence.workspace_id, "export")
    try:
        return start_export(db, sequence_id, body.model_dump() if body else None, created_by=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RenderPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _apply(operation) -> None:
    try:
        operation()
    except SequenceDomainError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


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


def _sequences_response(sequences: list[Sequence]) -> Response:
    return Response(f"[{','.join(_sequence_json(item) for item in sequences)}]", media_type="application/json")


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
