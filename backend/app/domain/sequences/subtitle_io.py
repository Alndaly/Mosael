"""字幕轨 ⇄ SRT / WebVTT 文件。

导出:一条字幕轨写成 .srt / .vtt,双语字幕(「原文\n译文」两行)可以选全写、只写原文或只写译文。
导入:读 .srt / .vtt 落到指定字幕轨(不指定就新建一条),可以整体平移、可以替换轨上原有的字幕。

**导入是撤销栈上的一步**:新建的轨、删掉的旧字幕、铺上的新字幕记成一个操作组(见 grouping)。
**超出时间线内容的字幕不落**:整部电影的字幕导进一段剪过的片子,后面那几百条落在黑屏上没有意义 —— 丢掉,
条数报回去;落在内容里、尾巴超出的截到末尾(和生成字幕同一条规矩,见 text._checked_cues)。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Sequence, Track
from app.domain.sequences._timeline import _require_sequence, timeline_span
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.media.subtitle_files import Cue, decode, parse, resolve_overlaps, to_srt, to_vtt

FORMATS = ("srt", "vtt")
#: 双语字幕导出哪一行:全部、第一行(原文)、最后一行(译文)。和配音的「念哪一行」同一组选项。
LINES = ("all", "first", "last")


def _pick_line(text: str, line: str) -> str:
    lines = [part.strip() for part in (text or "").splitlines() if part.strip()]
    if not lines:
        return ""
    if line == "first":
        return lines[0]
    if line == "last":
        return lines[-1]
    return "\n".join(lines)


def _subtitle_track(sequence: Sequence, track_id: str) -> Track:
    track = next((track for track in sequence.tracks or [] if track.id == track_id), None)
    if track is None:
        raise SequenceNotFound("Track not found")
    if track.kind != "subtitle":
        raise SequenceDomainError("Subtitles need a subtitle track")
    return track


def export_track(db: Session, sequence_id: str, track_id: str, *, fmt: str, line: str = "all") -> str:
    """这条字幕轨写成 `fmt`(srt / vtt)的文本。一条字幕都没有就报错 —— 导出一个空文件只会让人以为成功了。"""
    if fmt not in FORMATS:
        raise SequenceDomainError("subfileErr_format", formats=" / ".join(FORMATS))
    if line not in LINES:
        raise SequenceDomainError("subfileErr_line")
    track = _subtitle_track(_require_sequence(db, sequence_id), track_id)
    cues = [
        Cue(start=clip.timeline_start, end=clip.timeline_start + timeline_span(clip), text=text)
        for clip in sorted(track.clips or [], key=lambda one: one.timeline_start)
        if (text := _pick_line(clip.text_override or "", line))
    ]
    if not cues:
        raise SequenceDomainError("subfileErr_trackEmpty")
    return to_srt(cues) if fmt == "srt" else to_vtt(cues)


@dataclass(frozen=True)
class ImportResult:
    track_id: str
    imported: int
    #: 起点落在时间线内容之外、没有落下的条数。
    dropped: int


def import_into_track(
    db: Session,
    sequence_id: str,
    data: bytes,
    *,
    track_id: str = "",
    offset: float = 0.0,
    replace: bool = False,
    actor_id: str | None = None,
) -> ImportResult:
    """读一份 .srt / .vtt 落到字幕轨上。`offset` 秒整体平移(文件里的第 0 秒落在时间线的第几秒)。"""
    import math

    from app.domain.sequences.append import track_end
    from app.domain.sequences.grouping import OperationGroup
    from app.domain.sequences.text import GenerateSubtitles, generate_subtitles
    from app.domain.sequences.tracks import AddTrack, add_track

    if not math.isfinite(offset):
        raise SequenceDomainError("seqErr_cueNotFinite", index=0)
    sequence = _require_sequence(db, sequence_id)
    if track_id:
        _subtitle_track(sequence, track_id)
    cues = resolve_overlaps(parse(decode(data)))
    content_end = max(
        (track_end(track) for track in sequence.tracks or [] if track.kind != "subtitle" and track.role != "dub"),
        default=0.0,
    )
    shifted = [(cue.text, cue.start + offset, cue.end - cue.start) for cue in cues if cue.start + offset >= 0]
    kept = [cue for cue in shifted if content_end <= 0 or cue[1] < content_end]
    if not kept:
        raise SequenceDomainError("subfileErr_nothingInRange")
    with OperationGroup(sequence_id, label="import_subtitles", actor_id=actor_id).collect(db):
        if not track_id:
            add_track(db, sequence_id, AddTrack(kind="subtitle", actor_id=actor_id))
            db.refresh(sequence)
            track_id = max((t for t in sequence.tracks if t.kind == "subtitle"), key=lambda t: t.position).id
        generate_subtitles(
            db, sequence_id, GenerateSubtitles(track_id=track_id, cues=tuple(kept), replace=replace, actor_id=actor_id)
        )
    return ImportResult(track_id=track_id, imported=len(kept), dropped=len(cues) - len(kept))
