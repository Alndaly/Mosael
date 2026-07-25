"""花字(独立文本元素)导出编译:video 轨上无 asset 的文本片段,每条自带样式、用 transform 定位,
编译成带 \\pos/\\frz/\\fscx 与逐条样式(字号/颜色/描边/阴影/粗斜)的 ASS Dialogue,烧录进画面。

这里断言样式校验、计划收集与 ASS 生成;真实渲染由 test 层的 ffmpeg smoke 另行覆盖。"""

from __future__ import annotations

from pathlib import Path

from app.media.render_executor import _text_overlay_dialogues, build_ffmpeg_command
from app.media.render_plan import (
    DEFAULT_TEXT_STYLE,
    TextOverlayItem,
    TextStyleSpec,
    _read_text_style,
    build_render_plan,
)


class TestReadTextStyle:
    def test_defaults_when_missing(self) -> None:
        assert _read_text_style(None) is DEFAULT_TEXT_STYLE
        assert _read_text_style({}) == DEFAULT_TEXT_STYLE

    def test_clamps_and_validates(self) -> None:
        st = _read_text_style(
            {"font_size": 9999, "stroke_width": 999, "color": "not-a-color", "align": "sideways", "bold": False}
        )
        assert st.font_size == 800.0  # 上界
        assert st.stroke_width == 40.0  # 上界
        assert st.color == "#ffffff"  # 非法色 → 默认
        assert st.align == "center"  # 非法对齐 → 默认
        assert st.bold is False

    def test_keeps_valid_values(self) -> None:
        st = _read_text_style({"color": "#ff0066", "stroke_color": "#101010", "stroke_width": 3, "italic": True})
        assert st.color == "#ff0066" and st.stroke_color == "#101010"
        assert st.stroke_width == 3.0 and st.italic is True


def _plan_with_text(text_overlays):
    return build_render_plan(
        sequence_id="s", revision=1, width=1920, height=1080, fps=30,
        clips=[{"id": "b", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets={"a": {"file_key": "a"}},
        text_overlays=text_overlays,
    )


def test_build_render_plan_collects_text_overlays() -> None:
    plan = _plan_with_text([{
        "id": "t1", "asset_id": None, "timeline_start": 1, "src_in": 0, "src_out": 3,
        "text_override": "  你好 花字  ",
        "effects": {"text_style": {"color": "#ffcc00", "stroke_width": 2}},
        "transform": {"x": 0.5, "y": -0.5, "scale": 1.5},
    }])
    assert len(plan.text_overlays) == 1
    item = plan.text_overlays[0]
    assert item.text == "你好 花字"  # trimmed
    assert item.start == 1.0 and item.duration == 3.0  # src_out−src_in
    assert item.style.color == "#ffcc00" and item.style.stroke_width == 2.0
    assert item.transform.x == 0.5 and item.transform.scale == 1.5


def test_empty_text_overlay_is_skipped() -> None:
    plan = _plan_with_text([{
        "id": "t1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "   ",
    }])
    assert plan.text_overlays == ()


class TestDialogue:
    def test_position_scale_rotation_and_style_tags(self) -> None:
        item = TextOverlayItem(
            start=1.0, duration=2.0, text="Hi",
            style=TextStyleSpec(font_size=64, color="#ff0000", stroke_color="#000000", stroke_width=3, bold=True),
        )
        # transform 默认恒等 → 画面正中,静态时单条 Dialogue
        (line,) = _text_overlay_dialogues(item, 1920, 1080)
        from app.media.render_executor import _ASS_FONTSIZE_SCALE

        assert "\\an5" in line
        assert "\\pos(960.0,540.0)" in line  # 恒等 transform → 画面中心
        assert f"\\fs{64 * _ASS_FONTSIZE_SCALE:g}" in line  # 字号按 libass↔浏览器系数放大
        assert "\\1c&H0000FF&" in line  # 红 #ff0000 → BGR 0000FF
        assert "\\bord3\\3c&H000000&" in line
        assert "\\b1" in line
        assert line.endswith("Hi")

    def test_transform_maps_to_pos_frz_fscx_alpha(self) -> None:
        from app.media.render_plan import Transform
        item = TextOverlayItem(
            start=0.0, duration=1.0, text="x",
            transform=Transform(x=1.0, y=-1.0, scale=2.0, rotation=90.0, opacity=0.5),
        )
        (line,) = _text_overlay_dialogues(item, 1000, 500)
        assert "\\pos(1000.0,0.0)" in line  # x=1→右缘, y=-1→上缘
        assert "\\frz-90.00" in line  # 顺时针 90° → ASS -90
        assert "\\fscx200.0\\fscy200.0" in line
        assert "\\alpha&H80&" in line  # opacity .5 → alpha 128

    def test_keyframed_text_compiles_to_move_and_t(self) -> None:
        """打了关键帧的花字:位置用 \\move 线性,缩放用 \\t 渐变,与预览分段线性一致。"""
        from app.media.render_plan import Transform
        item = TextOverlayItem(
            start=0.0, duration=2.0, text="hi",
            transform=Transform(keyframes=((0.0, "x", -1.0), (1.0, "x", 1.0), (0.0, "scale", 1.0), (1.0, "scale", 2.0))),
        )
        lines = _text_overlay_dialogues(item, 1000, 500)
        assert len(lines) == 1  # 时间点只有 0 和 1 → 单段
        assert "\\move(0.0,250.0,1000.0,250.0)" in lines[0]  # x:-1→0px 到 1→1000px,y=0→250
        assert "\\t(0,2000," in lines[0] and "\\fscx200.0" in lines[0]  # scale 1→2 用 \t 渐变

    def test_multi_keyframe_text_splits_into_segments(self) -> None:
        """三个位置关键帧 → 两段 \\move,拼成分段线性。"""
        from app.media.render_plan import Transform
        item = TextOverlayItem(
            start=0.0, duration=3.0, text="hi",
            transform=Transform(keyframes=((0.0, "x", -1.0), (0.5, "x", 0.0), (1.0, "x", 1.0))),
        )
        lines = _text_overlay_dialogues(item, 1000, 500)
        assert len(lines) == 2  # 时间点 0/0.5/1 → 两段
        assert "\\move(0.0,250.0,500.0,250.0)" in lines[0]  # 段1: x -1→0
        assert "\\move(500.0,250.0,1000.0,250.0)" in lines[1]  # 段2: x 0→1


def test_text_overlay_triggers_ass_burn(tmp_path: Path) -> None:
    """有花字(即使没有字幕轨)也要生成 subtitles 滤镜把 ASS 烧进画面。"""
    plan = _plan_with_text([{
        "id": "t1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "标题",
    }])
    graph = " ".join(build_ffmpeg_command(plan, lambda k: tmp_path / k, tmp_path / "o.mp4"))
    assert "subtitles=filename=" in graph
    assert (tmp_path / "o.ass").exists()  # ASS 已落盘


def test_read_text_style_keeps_font_id() -> None:
    assert _read_text_style({"font_id": "f1", "font_family": "Foo"}).font_id == "f1"
    assert _read_text_style({}).font_id == ""


def test_fontsdir_falls_back_to_title_font(tmp_path: Path) -> None:
    """字幕无上传字体、花字有 → subtitles 的 fontsdir 用花字解析出的 workspace 字体根目录。"""
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "b", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "a"}},
        text_overlays=[{
            "id": "t", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2,
            "text_override": "x", "effects": {"text_style": {"font_family": "Foo", "font_dir": str(tmp_path)}},
        }],
    )
    graph = " ".join(build_ffmpeg_command(plan, lambda k: tmp_path / k, tmp_path / "o.mp4"))
    assert ":fontsdir='" in graph  # 花字上传字体让 fontsdir 出现(字幕本身没有字体)


class TestHuaziBoxNotInheritedFromSubtitle:
    """回归:花字自己没有背景,不能继承字幕的背景框。历史 bug 是花字与字幕共用 Default 样式
    (BorderStyle=3 带框),于是字幕一开框、花字就凭空多个黑框,与预览不符。花字应走独立的
    Text 样式(BorderStyle=1,仅描边/阴影)。"""

    def _ass(self) -> str:
        from app.media.render_executor import _build_ass

        plan = build_render_plan(
            sequence_id="s", revision=1, width=1920, height=1080, fps=30,
            clips=[{"id": "c", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 3}],
            assets={"a": {"file_key": "/x.png"}},
            subtitle_clips=[{"id": "s1", "timeline_start": 0, "src_in": 0, "src_out": 3, "text_override": "字幕"}],
            subtitle_style={"font_size": 40, "bg_opacity": 0.6, "color": "#ffffff"},
            text_overlays=[{"id": "t1", "timeline_start": 0, "src_in": 0, "src_out": 3, "text_override": "花字",
                            "effects": {"text_style": {"font_size": 72, "color": "#ffee00"}}}],
        )
        return _build_ass(plan)

    def test_subtitle_uses_boxed_default_style(self) -> None:
        ass = self._ass()
        default = next(ln for ln in ass.splitlines() if ln.startswith("Style: Default,"))
        # Default 样式:BorderStyle=3(第 16 个字段)= 不透明框,字幕保留背景
        assert default.split(",")[15] == "3"
        assert any(ln.startswith("Dialogue:") and ",Default," in ln and "字幕" in ln for ln in ass.splitlines())

    def test_huazi_uses_boxless_text_style(self) -> None:
        ass = self._ass()
        assert any(ln.startswith("Style: Text,") for ln in ass.splitlines()), "花字应有独立 Text 样式"
        text_style = next(ln for ln in ass.splitlines() if ln.startswith("Style: Text,"))
        assert text_style.split(",")[15] == "1"  # BorderStyle=1:无背景框
        # 花字 Dialogue 必须引用 Text 样式,而不是带框的 Default
        huazi = next(ln for ln in ass.splitlines() if ln.startswith("Dialogue:") and "花字" in ln)
        assert ",Text," in huazi and ",Default," not in huazi


def test_fontsize_scaled_to_match_browser_rendering():
    """libass 渲染字号比浏览器小约 0.71×,导出前需按 _ASS_FONTSIZE_SCALE 放大,才和预览等大。"""
    from app.media.render_executor import _ASS_FONTSIZE_SCALE, _text_style_tags

    tags = _text_style_tags(_read_text_style({"font_size": 100}))
    assert f"\\fs{100 * _ASS_FONTSIZE_SCALE:g}" in tags
    assert _ASS_FONTSIZE_SCALE > 1.0
