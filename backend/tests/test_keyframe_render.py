"""关键帧导出编译:预览里 clip 的 transform 随时间插值,导出的成片也要一致。

这里断言的是「关键帧 → FFmpeg 时间表达式」的编译(位置/旋转本批),不跑真实渲染:表达式对了,
ffmpeg 自会逐帧求值。scale/opacity 关键帧仍走静态值(下一批),此处不覆盖其动画。"""

from __future__ import annotations

from pathlib import Path

from app.media.render_executor import _kf_expr, build_ffmpeg_command
from app.media.render_plan import Transform, _read_keyframes, build_render_plan


class TestKfExpr:
    def test_single_point_is_a_constant(self) -> None:
        assert _kf_expr(((0.5, 1.3),), "(t)/4") == "1.30000"

    def test_two_points_are_piecewise_linear_with_end_hold(self) -> None:
        expr = _kf_expr(((0.0, -1.0), (1.0, 1.0)), "(t)/4")
        # before first → first value; the interpolated segment; the progress term appears
        assert "if(lt(((t)/4),0.000000),-1.00000," in expr
        assert "(t)/4" in expr and "clip(" in expr

    def test_empty_is_zero(self) -> None:
        assert _kf_expr((), "(t)/4") == "0"


class TestReadKeyframes:
    def test_flattens_clamps_and_sorts(self) -> None:
        raw = [{"t": 1.0, "x": 9.0}, {"t": 0.0, "x": -9.0, "opacity": 2.0}]
        kfs = _read_keyframes(raw)
        # x clamped to ±4, opacity to ≤1, flattened to (t, prop, value), sorted by t
        assert kfs == ((0.0, "opacity", 1.0), (0.0, "x", -4.0), (1.0, "x", 4.0))

    def test_transform_keyed_pulls_one_track(self) -> None:
        tf = Transform(keyframes=((0.0, "x", -1.0), (1.0, "x", 1.0), (0.5, "opacity", 0.3)))
        assert tf.keyed("x") == ((0.0, -1.0), (1.0, 1.0))
        assert tf.keyed("opacity") == ((0.5, 0.3),)
        assert tf.animates is True  # x has two points that differ


def _graph(clips=None, overlay_clips=None, tmp="/nonexistent") -> str:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=clips or [{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        overlay_clips=overlay_clips,
        assets={"a": {"file_key": "a"}, "b": {"file_key": "b"}},
    )
    return " ".join(build_ffmpeg_command(plan, lambda k: Path(tmp) / k, Path(tmp) / "o.mp4"))


def test_position_keyframes_compile_to_an_overlay_expression() -> None:
    """A base clip animating x becomes a composited element whose overlay x is a time expr."""
    graph = _graph(clips=[{
        "id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4,
        "transform": {"keyframes": [{"t": 0, "x": -1}, {"t": 1, "x": 1}]},
    }])
    assert "overlay=x='(0.5+(if(lt(" in graph  # expression, not a fixed integer
    assert "(t)/4" in graph  # normalized progress over the 4s clip


def test_overlay_track_progress_is_offset_by_start() -> None:
    """An upper-track element keys against (t − start)/duration, not the base's t/duration."""
    graph = _graph(overlay_clips=[{
        "id": "c2", "asset_id": "b", "timeline_start": 2, "src_in": 0, "src_out": 4,
        "transform": {"keyframes": [{"t": 0, "y": -1}, {"t": 1, "y": 1}]},
    }])
    assert "(t-2.000000)/4" in graph


def test_scale_keyframes_compile_to_an_eval_frame_scale() -> None:
    """Animating scale re-evaluates the element size per frame, and centring switches to overlay
    W/H/w/h so the growing element stays put."""
    graph = _graph(clips=[{
        "id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4,
        "transform": {"keyframes": [{"t": 0, "scale": 1}, {"t": 1, "scale": 2}]},
    }])
    assert "scale=w='iw*(" in graph and "eval=frame" in graph
    assert "overlay=x='(0.5+(0.00000)*0.5)*W-w/2'" in graph  # centred via element w/h, not a fixed px


def test_opacity_keyframes_compile_to_a_geq_alpha_expression() -> None:
    """Animating opacity scales the alpha plane by the opacity curve (luma/chroma pass through)."""
    graph = _graph(clips=[{
        "id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4,
        "transform": {"keyframes": [{"t": 0, "opacity": 0}, {"t": 1, "opacity": 1}]},
    }])
    assert "geq=lum='lum(X,Y)'" in graph and "a='alpha(X,Y)*clip((" in graph
    assert "(T)/4" in graph  # geq exposes frame time as T, not t


def test_rotation_keyframes_compile_to_a_rotate_expression() -> None:
    graph = _graph(clips=[{
        "id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4,
        "transform": {"keyframes": [{"t": 0, "rotation": 0}, {"t": 1, "rotation": 90}]},
    }])
    assert "rotate='((" in graph and "*PI/180)'" in graph


def test_static_transform_still_uses_fixed_integer_position() -> None:
    """No keyframes → the old fast path: a plain-integer overlay offset, no time expression."""
    graph = _graph(clips=[{
        "id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4,
        "transform": {"x": 0.5, "scale": 1.2},
    }])
    assert "if(lt(" not in graph  # nothing animates
