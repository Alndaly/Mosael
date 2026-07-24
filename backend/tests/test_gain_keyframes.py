"""音量(增益)关键帧:片段自带音频的 gain 随时间插值,编译成 ffmpeg volume 时间表达式,
与视频关键帧共用同一分段线性内核。这里断言读取/编译;真实渲染由 ffmpeg smoke 另行覆盖。"""

from __future__ import annotations

from app.media.render_executor import _volume_expr
from app.media.render_plan import _read_gain_keyframes, build_render_plan


def test_read_gain_keyframes_sorts_and_clamps() -> None:
    kf = _read_gain_keyframes({"gain_keyframes": [{"t": 1, "gain": 9}, {"t": -1, "gain": 0.5}]})
    assert kf == ((0.0, 0.5), (1.0, 4.0))  # t 钳 [0,1]、gain 钳 [0,4]、按 t 排序
    assert _read_gain_keyframes({}) == ()
    assert _read_gain_keyframes({"gain_keyframes": "nope"}) == ()


def test_volume_expr_static() -> None:
    assert _volume_expr(0.5, (), 2.0) == "volume=0.5,"
    assert _volume_expr(1.0, (), 2.0) == ""  # gain≈1、无关键帧 → 省略


def test_volume_expr_keyframed() -> None:
    v = _volume_expr(1.0, ((0.0, 0.0), (1.0, 1.0)), 4.0)
    assert v.startswith("volume='") and v.endswith("':eval=frame,")
    assert "(t)/4" in v  # 段内进度(音频 asetpts 重置到 0)


def test_plan_carries_gain_keyframes() -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{
            "id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4,
            "effects": {"gain_keyframes": [{"t": 0, "gain": 0}, {"t": 1, "gain": 1}]},
        }],
        assets={"a": {"file_key": "a"}},
    )
    assert plan.video_segments[0].gain_keyframes == ((0.0, 0.0), (1.0, 1.0))
