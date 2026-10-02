"""时间线的每个算子都拒收非有限的数;特效存之前清洗,读不了的值当场拒。

接口那层的 pydantic(allow_inf_nan=False)只挡得住 HTTP 的标量字段。智能体的 edit_timeline、工作流
节点直接把数交给领域算子,而算子各自只比了大小 —— 和 NaN 的比较全是 False:移动只判 `< 0`,NaN 就
放进去了;音量把 NaN 钳成了 4.0;剪段的 NaN 起点被当成「不相交」;字幕的 NaN 起点照样插。存下的 NaN
序列化出来不是合法 JSON,那条时间线浏览器再也打不开。

特效则是另一个口子:dict 字段里的值原样存,`{"fade_in": "abc"}`、`{"color": [1, 2]}` 要到导出才炸成 500。
"""

from __future__ import annotations

import math

import pytest

from app.core.db import SessionLocal
from app.db.models import Clip
from app.domain.render import build_plan_for_sequence
from app.domain.sequences.errors import SequenceDomainError
from tests.util import fresh_client, insert_asset

NAN, INF = float("nan"), float("inf")


@pytest.fixture()
def timeline():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    seq = sequence["id"]
    video = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    subtitle = next(
        t["id"] for t in client.post(f"/api/sequences/{seq}/tracks", json={"kind": "subtitle"}).json()["tracks"]
        if t["kind"] == "subtitle"
    )
    asset = insert_asset(ws, kind="video", name="v.mp4", file_key="media/v.mp4", media_info={"duration": 10})
    state = client.post(
        f"/api/sequences/{seq}/clips",
        json={"track_id": video, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 10},
    ).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["id"]
    return {"client": client, "seq": seq, "clip": clip, "video": video, "subtitle": subtitle}


def _cases(clip: str, subtitle: str) -> list[tuple[object, object]]:
    from app.domain.sequences import operations as ops

    return [
        (ops.move_clip, ops.MoveClip(clip_id=clip, timeline_start=NAN)),
        (ops.move_clip, ops.MoveClip(clip_id=clip, timeline_start=INF)),
        (ops.move_clip, ops.MoveClip(clip_id=clip, timeline_start="3")),  # type: ignore[arg-type]
        (ops.set_clip_gain, ops.SetClipGain(clip_id=clip, gain=NAN)),
        (ops.set_clip_speed, ops.SetClipSpeed(clip_id=clip, speed=NAN)),
        (ops.cut_clip_range, ops.CutClipRange(clip_id=clip, src_start=NAN, src_end=4)),
        (ops.split_clip, ops.SplitClip(clip_id=clip, src_time=INF)),
        (ops.trim_clip, ops.TrimClip(clip_id=clip, timeline_start=0, src_in=0, src_out=INF)),
        (ops.set_clip_transform, ops.SetClipTransform(clip_id=clip, transform={"scale": NAN})),
        (ops.set_clip_transform, ops.SetClipTransform(clip_id=clip, transform={"keyframes": [{"t": NAN, "scale": 1}]})),
        (ops.set_clip_transform, ops.SetClipTransform(clip_id=clip, transform={"scale": "big"})),
        (ops.set_clip_effects, ops.SetClipEffects(clip_id=clip, effects={"fade_in": NAN})),
        (ops.set_clip_effects, ops.SetClipEffects(clip_id=clip, effects={"text_style": {"font_size": INF}})),
        (ops.insert_text_clip, ops.InsertTextClip(track_id=subtitle, text="hi", timeline_start=0, duration=INF)),
    ]


@pytest.mark.parametrize("case", range(14))
def test_领域算子拒收非有限数_时间线不动(timeline, case) -> None:
    """接口与 edit_timeline 的入参模型各挡了一层;工作流节点、配音、画板这些领域内的调用方直接调算子,
    挡在算子这里才是全集。"""
    handler, op = _cases(timeline["clip"], timeline["subtitle"])[case]
    with SessionLocal() as db:
        with pytest.raises(SequenceDomainError):
            handler(db, timeline["seq"], op)
        db.rollback()
        clip = db.get(Clip, timeline["clip"])
        assert (clip.timeline_start, clip.gain, clip.speed, clip.src_out) == (0, 1.0, 1.0, 10)


def test_整组移动里有一个非有限的起点_整组不动(timeline) -> None:
    from app.domain.sequences.operations import ClipMove, MoveClipsBatch, move_clips_batch

    with SessionLocal() as db:
        with pytest.raises(SequenceDomainError):
            move_clips_batch(db, timeline["seq"], MoveClipsBatch(moves=(ClipMove(clip_id=timeline["clip"], timeline_start=NAN),)))
        assert db.get(Clip, timeline["clip"]).timeline_start == 0


def test_一键生成字幕_非有限的起点或时长被拒(timeline) -> None:
    client, seq = timeline["client"], timeline["seq"]
    from app.domain.sequences.operations import GenerateSubtitles, generate_subtitles

    with SessionLocal() as db:
        with pytest.raises(SequenceDomainError):
            generate_subtitles(db, seq, GenerateSubtitles(track_id=timeline["subtitle"], cues=(("a", NAN, 1.0),)))
        with pytest.raises(SequenceDomainError):
            generate_subtitles(db, seq, GenerateSubtitles(track_id=timeline["subtitle"], cues=(("a", 0.0, INF),)))
    assert client.get(f"/api/sequences/{seq}").status_code == 200


def test_字幕样式里的非有限数回落默认_而不是钳到上限(timeline) -> None:
    from app.domain.sequences.operations import clean_subtitle_style

    style = clean_subtitle_style({"font_size": NAN, "offset": INF})
    assert style["font_size"] == 32.0 and style["offset"] == 8.0


@pytest.mark.parametrize(
    "effects",
    [
        {"fade_in": "abc"},
        {"fade_in": True},
        {"color": [1, 2]},
        {"color": {"brightness": "x"}},
        {"color": {"curves": {"luma": [[0, 0, 0]]}}},
        {"filter": "nope"},
        {"gain_keyframes": [{"t": 0}]},
        {"appearance": "round"},
    ],
)
def test_读不了的特效值当场拒_导出不再_500(timeline, effects) -> None:
    client, seq, clip = timeline["client"], timeline["seq"], timeline["clip"]
    res = client.patch(f"/api/sequences/{seq}/clips/{clip}/effects", json={"effects": effects})
    assert res.status_code == 422, res.text
    with SessionLocal() as db:
        assert db.get(Clip, clip).effects == {}
        build_plan_for_sequence(db, seq)  # 存着的仍是能导出的东西


def test_特效清洗_钳范围_丢掉不认得的键_认得的原样留下(timeline) -> None:
    client, seq, clip = timeline["client"], timeline["seq"], timeline["clip"]
    effects = {
        "fade_in": -2,
        "video_fade_out": 1.5,
        "color": {"brightness": 3, "lut": "", "curves": {"luma": [[0, 0.1], [1, 2]]}, "junk": 1},
        "gain_keyframes": [{"t": 1, "gain": 9}, {"t": -1, "gain": 0.5}],
        "text_style": {"font_size": 60, "color": "#ff0000"},
        "pip": {"x": 0.1},
        "filter": "bw",
    }
    state = client.patch(f"/api/sequences/{seq}/clips/{clip}/effects", json={"effects": effects}).json()
    stored = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["effects"]
    assert stored == {
        "fade_in": 0.0,
        "video_fade_out": 1.5,
        "color": {"brightness": 1.0, "curves": {"luma": [[0.0, 0.1], [1.0, 1.0]]}},
        "gain_keyframes": [{"t": 0.0, "gain": 0.5}, {"t": 1.0, "gain": 4.0}],
        "text_style": {"font_size": 60, "color": "#ff0000"},
        "filter": "bw",
    }
    assert all(math.isfinite(v) for v in (stored["fade_in"], stored["video_fade_out"]))
