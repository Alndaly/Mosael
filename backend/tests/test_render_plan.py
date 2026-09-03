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


def test_clip_appearance_is_validated_for_base_and_overlay_video():
    """Mask/shadow are render semantics, not inspector-only decoration."""
    base = clip("c1", "a1", 0, 0, 4)
    base["effects"] = {
        "appearance": {
            "mask": {"shape": "circle", "radius": 99},
            "shadow": {
                "enabled": True,
                "color": "#123456",
                "opacity": 0.65,
                "blur": 32,
                "offset_x": 12,
                "offset_y": -8,
            },
        }
    }
    overlay = clip("c2", "a2", 0, 0, 4)
    overlay["effects"] = {"appearance": {"mask": {"shape": "rounded", "radius": 0.2}}}

    plan = build_render_plan(
        sequence_id="seq1",
        revision=1,
        width=1920,
        height=1080,
        fps=30,
        clips=[base],
        overlay_clips=[overlay],
        assets={"a1": {"file_key": "a1.mp4"}, "a2": {"file_key": "a2.mp4"}},
    )

    assert plan.video_segments[0].appearance.mask.shape == "circle"
    assert plan.video_segments[0].appearance.mask.radius == 0.5
    assert plan.video_segments[0].appearance.shadow.color == "#123456"
    assert plan.video_segments[0].appearance.shadow.opacity == 0.65
    assert plan.overlays[0].appearance.mask.shape == "rounded"
    assert plan.overlays[0].appearance.mask.radius == 0.2


def test_clip_curves_emit_ffmpeg_specs():
    c = clip("c1", "a1", 0, 0, 5)
    c["effects"] = {"color": {"curves": {
        "luma": [[0, 0], [0.5, 0.7], [1, 1]],
        "r": [[0, 0], [1, 1]],                  # identity → dropped
        "g": [[0, 0.1], [0.5, 0.6], [0.502, 0.9], [1, 1]],  # 0.5/0.502 near-dup → 0.502 dropped
    }}}
    plan = make_plan([c])
    curves = plan.video_segments[0].curves
    assert curves == (
        ("master", "0.000/0.000 0.500/0.700 1.000/1.000"),
        ("g", "0.000/0.100 0.500/0.600 1.000/1.000"),
    ), curves


def test_identity_curves_are_dropped():
    c = clip("c1", "a1", 0, 0, 5)
    c["effects"] = {"color": {"curves": {"luma": [[0, 0], [1, 1]]}}}
    assert make_plan([c]).video_segments[0].curves == ()


def test_export_params_scale_output_and_encode():
    from app.domain.render import resolve_export_output

    style = {"font_size": 48.0, "position": "bottom"}
    w, h, fps, out_style, crf, preset = resolve_export_output(
        1920, 1080, 30.0, style, {"resolution": "720p", "fps": 24, "quality": "compact"}
    )
    assert (w, h, fps) == (1280, 720, 24.0)
    assert out_style["font_size"] == 32.0  # 字幕字号随输出等比缩放
    assert (crf, preset) == (26, "veryfast")

    # 竖屏按短边对齐;original/未知档位不缩放;不升采样
    assert resolve_export_output(1080, 1920, 30.0, {}, {"resolution": "720p"})[:2] == (720, 1280)
    assert resolve_export_output(1920, 1080, 30.0, {}, {"resolution": "original"})[:2] == (1920, 1080)
    assert resolve_export_output(640, 360, 30.0, {}, {"resolution": "1080p"})[:2] == (640, 360)

    # 无参数 = 老行为(标准档)
    assert resolve_export_output(1920, 1080, 30.0, {}, None) == (1920, 1080, 30.0, {}, 20, "veryfast")


def test_plan_carries_encode_settings():
    plan = build_render_plan(
        sequence_id="seq1", revision=1, width=1280, height=720, fps=30.0,
        clips=[clip("c1", "a1", 0, 0, 2)], assets={"a1": {"file_key": "media/a1.mp4"}},
        crf=18, encode_preset="medium",
    )
    assert (plan.output.crf, plan.output.encode_preset) == (18, "medium")
    # 非法值回退默认
    fallback = build_render_plan(
        sequence_id="seq1", revision=1, width=1280, height=720, fps=30.0,
        clips=[clip("c1", "a1", 0, 0, 2)], assets={"a1": {"file_key": "media/a1.mp4"}},
        crf=99, encode_preset="warp-speed",
    )
    assert (fallback.output.crf, fallback.output.encode_preset) == (51, "veryfast")


def test_base_padded_to_full_duration_when_overlay_longer():
    """底轨(base)比上层视频短时,画面补黑场延伸到整条时间线——否则导出视频在底轨结束处截断,
    音频/上层视频还在走画面却没了(用户报的「预览与导出完全不同」)。"""
    plan = build_render_plan(
        sequence_id="s", revision=1, width=1920, height=1080, fps=30.0,
        clips=[clip("base", "a1", 0, 0, 3)],  # 底轨 3s
        overlay_clips=[{"id": "ov", "asset_id": "a2", "timeline_start": 0, "src_in": 0, "src_out": 8}],  # 叠加层 8s
        assets={"a1": {"file_key": "media/a1.mp4"}, "a2": {"file_key": "media/a2.mp4"}},
    )
    assert plan.timeline_duration == 8
    assert plan.video_segments[-1].kind == "gap"  # 尾部黑场
    assert round(sum(s.duration for s in plan.video_segments), 3) == 8  # 画面铺满整条


def test_no_trailing_pad_when_base_longest():
    """底轨最长时不补尾部黑场(回归:别给正常时间线平白加黑帧)。"""
    plan = build_render_plan(
        sequence_id="s", revision=1, width=1920, height=1080, fps=30.0,
        clips=[clip("base", "a1", 0, 0, 8)],
        overlay_clips=[{"id": "ov", "asset_id": "a2", "timeline_start": 0, "src_in": 0, "src_out": 3}],
        assets={"a1": {"file_key": "media/a1.mp4"}, "a2": {"file_key": "media/a2.mp4"}},
    )
    assert plan.timeline_duration == 8
    assert [s.kind for s in plan.video_segments] == ["clip"]  # 无尾部 gap
