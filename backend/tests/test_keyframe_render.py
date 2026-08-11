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
        # 钳制范围是 TRANSFORM_BOUNDS(全项目唯一一份,由 contracts/transform-cases.json 钉住):
        # x ±2、opacity ≤1。此前这里写的是 ±4 —— 那是导出侧自己那份更宽的表,而写入路径钳的是
        # ±2,于是这条测试一直在给一个从来没生效过的范围背书。
        assert kfs == ((0.0, "opacity", 1.0), (0.0, "x", -2.0), (1.0, "x", 2.0))

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


class TestKfExprMultiKeyframe:
    """回归:_kf_expr 生成的 ffmpeg 表达式必须和参考插值 _kf_sample 逐点吻合,尤其 3+ 关键帧。
    历史 bug 是嵌套 if 顺序反了 → 任何早期 prog 都命中最后一段、恒取末值(如缩放全程卡在
    1.7,导出看不到放大)。"""

    @staticmethod
    def _eval(expr: str, t: float) -> float:
        def iff(c, a, b):
            return a if c else b

        def lt(a, b):
            return a < b

        def clip(x, lo, hi):
            return max(lo, min(hi, x))

        return eval(expr.replace("if(", "iff("), {"iff": iff, "lt": lt, "clip": clip, "t": t})

    def _check(self, points):
        from app.media.render_executor import _kf_expr, _kf_sample

        expr = _kf_expr(points, "t")
        for i in range(0, 101):
            t = i / 100.0
            got = self._eval(expr, t)
            ref = _kf_sample(points, points[0][1], t)
            assert abs(got - ref) < 1e-4, f"t={t}: expr={got} != sample={ref} for {points}"

    def test_four_keyframes_ken_burns(self):
        # 用户真实数据:缩放 0.168 → 1.517 → 1.7 → 1.7
        self._check(((0.0, 0.168), (0.503, 1.517), (0.571, 1.7), (0.825, 1.7)))

    def test_three_keyframes_interpolate_each_segment(self):
        self._check(((0.0, 0.0), (0.5, 1.0), (1.0, 0.0)))

    def test_two_keyframes_still_correct(self):
        self._check(((0.0, 1.0), (1.0, 2.0)))

    def test_early_progress_uses_first_segment(self):
        from app.media.render_executor import _kf_expr

        expr = _kf_expr(((0.0, 0.168), (0.5, 1.5), (1.0, 1.7)), "t")
        # 进度 0.1 落在第一段(0→0.5),应在 0.168 与 1.5 之间线性插值,绝不是末值 1.7
        assert 0.168 < self._eval(expr, 0.1) < 1.5
