"""镜头表的存取和核心流程:量 → 取帧拼表 →(有视觉模型就)逐批判 → 落库。工作流节点和分析都从这里进。

**两步分开落库。** 量和取帧几秒到几十秒、不花钱;判画面一批一次视觉调用。量完先落一次(界面马上看得到刀口和帧),
之后每判完一批落一次 —— 一批失败不连坐,判到一半被取消,前面几批也在。

**重拆是整份换掉。** 帧和联系表先写进 `shots.new/`,写完再换掉旧的 `shots/`:拆到一半失败时旧表和旧图都还在。

**素材页那条后台任务不住这里**:挑视觉模型、起视觉调用是分析域的事(这个模块不认识任何连接 / 模型,
分层见 tests/test_import_layering),见 app/domain/analysis/shots_task.py。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, get_current_locale
from app.db.models import Asset, ShotBreakdown
from app.domain.jobs import ensure_wanted
from app.domain.shots import describe, detect, frames, report
from app.media.paths import resolve_key


class ShotBreakdownError(LocalizedError, ValueError):
    """拆镜头被拒。带文案 key(`shotsErr_*`)。"""


def lang_now() -> str:
    """判画面用哪种语言写:这次请求的语言(后台线程里由发起处带进来)。"""
    return "en" if get_current_locale() == "en" else "zh"


def shots_dir(asset: Asset) -> Path:
    """帧和联系表的目录:素材目录下的 `shots/`,随素材目录一起删。"""
    return resolve_key(asset.file_key).parent / "shots"


def breakdown_for(db: Session, asset_id: str) -> ShotBreakdown | None:
    return db.scalar(select(ShotBreakdown).where(ShotBreakdown.asset_id == asset_id))


def require_video(asset: Asset) -> Path:
    if asset.kind != "video":
        raise ShotBreakdownError("shotsErr_notVideo")
    if not asset.file_key:
        raise ShotBreakdownError("shotsErr_noLocalFile")
    source = resolve_key(asset.file_key)
    if not source.is_file():
        raise ShotBreakdownError("shotsErr_fileMissing")
    return source


#: 帧图的名字(`S03a.jpg` / `S03b.jpg`,见 frames.frame_name)。详情页按它取缩略图,所以在这里收窄一次:
#: `shots/frames/` 是素材目录里面的目录,名字任由调用方给就等于开了一条走出去的路。
_FRAME_NAME = re.compile(r"S\d{2,}[ab]\.jpg")
#: 联系表的名字(`sheet-01a.jpg` / `sheet-01b.jpg`,见 frames.sheet_name)。同理收窄。
_SHEET_NAME = re.compile(r"sheet-\d{2,}[ab]\.jpg")


def frame_file(asset: Asset, name: str) -> Path | None:
    """这一镜的那张帧图;名字不是帧图、或者文件不在,都回 None(调用方 404)。"""
    if not _FRAME_NAME.fullmatch(name):
        return None
    path = shots_dir(asset) / "frames" / name
    return path if path.is_file() else None


def sheet_file(asset: Asset, name: str) -> Path | None:
    """那一组联系表的 A / B 半张;名字不是联系表、或者文件不在,都回 None(分析据此只交拿得到的那几张)。"""
    if not _SHEET_NAME.fullmatch(name):
        return None
    path = shots_dir(asset) / "sheets" / name
    return path if path.is_file() else None


def transcript_segments(db: Session, asset_id: str) -> list[dict[str, Any]]:
    """这份素材最新那份逐字稿的段落(没转写过是空的)。台词按时间分给镜头,见 describe.assign_dialogue。"""
    from app.domain.transcripts.operations import get_transcript_for_asset

    transcript = get_transcript_for_asset(db, asset_id)
    if transcript is None:
        return []
    return [{"start": segment.start_time, "end": segment.end_time, "text": segment.text} for segment in transcript.segments]


def measure_into(
    db: Session,
    asset: Asset,
    *,
    created_by: str | None,
    lang: str,
    threshold: float = detect.DEFAULT_THRESHOLD,
    min_shot: float = detect.DEFAULT_MIN_SHOT_SECONDS,
    segments: list[dict[str, Any]] | None = None,
) -> ShotBreakdown:
    """量刀口和动静、取帧、拼联系表,写进这份视频的镜头表(没有就建,有就整份换掉;判过的画面一并清掉)。

    `segments` 不给就用这份素材已有的逐字稿分台词。"""
    if not 0.05 <= threshold <= 0.9 or not 0 <= min_shot <= 5:
        raise ShotBreakdownError("shotsErr_badParams")
    source = require_video(asset)
    probe = detect.probe(source)
    measured = detect.measure(source, threshold=threshold)
    ensure_wanted()
    shots = detect.build_shots(probe.duration, measured.cuts, measured.motion, min_shot=min_shot)
    describe.assign_dialogue(shots, segments if segments is not None else transcript_segments(db, asset.id))
    final = shots_dir(asset)
    staging = final.with_name("shots.new")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        frames.grab_frames(source, shots, staging / "frames")
        ensure_wanted()
        aspect = probe.width / probe.height if probe.height else 16 / 9
        sheets = frames.make_sheets(shots, staging / "frames", staging / "sheets", aspect)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(final, ignore_errors=True)
    staging.rename(final)

    hints: list[dict[str, str]] = []
    if len(measured.cuts) + 1 > detect.MAX_SHOTS:
        hints.append({"shot": "", "kind": "truncated", "field": "", "value": str(detect.MAX_SHOTS)})
    row = breakdown_for(db, asset.id)
    if row is None:
        row = ShotBreakdown(asset_id=asset.id, workspace_id=asset.workspace_id)
        db.add(row)
    row.created_by = created_by
    row.lang = lang
    row.params = {"threshold": threshold, "min_shot": min_shot}
    row.meta = probe.as_dict()
    row.cuts = measured.cuts
    row.shots = shots
    row.sheets = sheets
    row.describe = {}
    row.hints = hints
    db.flush()
    return row


def judge(
    db: Session,
    row: ShotBreakdown,
    asset: Asset,
    ask: describe.Ask,
    *,
    provider: str,
    model: str,
    after_batch: Callable[[int, int], None] | None = None,
) -> None:
    """逐批判画面、对账,每判完一批写回一次。一批失败(调用报错、回答读不出来)记一条提示,接着判下一批。

    `after_batch(已判批数, 总批数)`:任务拿它落库、报进度;工作流节点不传(引擎在节点结束时提交)。"""
    folder = shots_dir(asset) / "sheets"
    shots = [dict(shot) for shot in row.shots]
    #: 按**这一刻**的逐字稿重分台词:工作流里转写排在拆镜头后面(官方模板 reference_video_shots 就是),
    #: 量的时候逐字稿还没到;判之前补一次,晚到的台词照样进提示词。重置再分,幂等。
    describe.assign_dialogue(shots, transcript_segments(db, asset.id))
    by_id = {shot["id"]: shot for shot in shots}
    hints = [hint for hint in row.hints if hint.get("kind") == "truncated"]
    judged = 0
    error = ""
    for done, sheet in enumerate(row.sheets, start=1):
        ensure_wanted()
        ids = _ids_between(shots, sheet["first"], sheet["last"])
        batch = [by_id[shot_id] for shot_id in ids]
        try:
            hints.extend(describe.describe_batch(batch, folder / sheet["a"], folder / sheet["b"], ask,
                                                 title=asset.name, lang=row.lang))
            judged += 1
        except LocalizedError as exc:
            #: 一批失败不连坐:记下第一个错误(界面说一句为什么没判全),其余批照判。
            error = error or str(exc)
            hints.append({"shot": batch[0]["id"], "kind": "batch_failed", "field": "", "value": batch[-1]["id"]})
        row.shots = [dict(shot) for shot in shots]
        row.hints = hints + describe.rhythm_hints(shots)
        row.describe = {"provider": provider, "model": model, "batches": len(row.sheets), "judged_batches": judged,
                        "error": error}
        db.flush()
        if after_batch is not None:
            after_batch(done, len(row.sheets))


def _ids_between(shots: list[dict[str, Any]], first: str, last: str) -> list[str]:
    ids = [shot["id"] for shot in shots]
    return ids[ids.index(first): ids.index(last) + 1]


# --------------------------------------------------------------------------------------
# 给界面、分析、工作流读的样子
# --------------------------------------------------------------------------------------


def public_shape(row: ShotBreakdown, asset: Asset) -> dict[str, Any]:
    duration = float((row.meta or {}).get("duration") or 0)
    return {
        "id": row.id,
        "asset_id": row.asset_id,
        "lang": row.lang,
        "params": row.params,
        "meta": row.meta,
        "shots": row.shots,
        "sheets": row.sheets,
        "describe": row.describe,
        "hints": row.hints,
        "stats": report.stats(row.shots, duration),
        "report_markdown": report.report_markdown(asset.name, row.shots, duration, lang=row.lang),
        "storyboard_markdown": report.storyboard_markdown(row.shots, lang=row.lang),
        "updated_at": row.updated_at,
    }


def prompt_context(row: ShotBreakdown, asset: Asset) -> str:
    """交给分析模型的那一段:量好的刀口和时长、判过的景别运镜。模型不必再猜一遍镜头在哪。"""
    duration = float((row.meta or {}).get("duration") or 0)
    numbers = report.stats(row.shots, duration)
    return "\n\n".join([
        "【镜头表(刀口和时长是代码量的,准确;景别、运镜是之前判过的)】",
        report.stats_markdown(numbers, lang=row.lang),
        report.shot_table_markdown(row.shots, lang=row.lang),
    ])


__all__ = ["ShotBreakdownError", "breakdown_for", "frame_file", "judge", "lang_now", "measure_into",
           "prompt_context", "public_shape", "require_video", "sheet_file", "shots_dir", "transcript_segments"]
