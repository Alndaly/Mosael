from __future__ import annotations

import pytest

from app.media.render_plan import RenderPlanError, build_render_plan


def make_plan(clips, assets=None):
    return build_render_plan(
        sequence_id="seq1",
        revision=3,
        width=1920,
        height=1080,
        fps=30.0,
        clips=clips,
        assets=assets
        if assets is not None
        else {"a1": {"file_key": "media/a1.mp4"}, "a2": {"file_key": "media/a2.mp4"}},
    )


def clip(id_, asset_id, start, src_in, src_out):
    return {"id": id_, "asset_id": asset_id, "timeline_start": start, "src_in": src_in, "src_out": src_out}


def test_contiguous_clips_produce_clip_segments_only():
    plan = make_plan([clip("c1", "a1", 0, 0, 4), clip("c2", "a2", 4, 1, 3)])
    assert [s.kind for s in plan.video_segments] == ["clip", "clip"]
    assert plan.timeline_duration == 6
    assert plan.video_segments[1].source.src_in == 1
    assert plan.render_plan_hash


def test_gap_becomes_black_segment():
    plan = make_plan([clip("c1", "a1", 2, 0, 3)])
    assert [s.kind for s in plan.video_segments] == ["gap", "clip"]
    assert plan.video_segments[0].duration == 2
    assert plan.timeline_duration == 5


def test_out_of_order_clips_are_sorted():
    plan = make_plan([clip("c2", "a2", 5, 0, 1), clip("c1", "a1", 0, 0, 5)])
    assert plan.video_segments[0].source.asset_id == "a1"
    assert plan.timeline_duration == 6


def test_overlap_rejected():
    with pytest.raises(RenderPlanError, match="overlaps"):
        make_plan([clip("c1", "a1", 0, 0, 4), clip("c2", "a2", 3, 0, 2)])


def test_missing_asset_file_rejected():
    with pytest.raises(RenderPlanError, match="without a file"):
        make_plan([clip("c1", "missing", 0, 0, 4)])


def test_empty_sequence_rejected():
    with pytest.raises(RenderPlanError, match="no clips"):
        make_plan([])


def test_hash_changes_with_content():
    p1 = make_plan([clip("c1", "a1", 0, 0, 4)])
    p2 = make_plan([clip("c1", "a1", 0, 0, 5)])
    assert p1.render_plan_hash != p2.render_plan_hash


def test_hash_stable_for_same_content():
    p1 = make_plan([clip("c1", "a1", 0, 0, 4)])
    p2 = make_plan([clip("c1", "a1", 0, 0, 4)])
    assert p1.render_plan_hash == p2.render_plan_hash
