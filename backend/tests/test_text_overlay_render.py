"""花字(独立文本元素)导出编译:video 轨上无 asset 的文本片段,每条自带样式、用 transform 定位,
编译成带 \\pos/\\frz/\\fscx 与逐条样式(字号/颜色/描边/阴影/粗斜)的 ASS Dialogue,烧录进画面。

这里断言样式校验、计划收集与 ASS 生成;真实渲染由 test 层的 ffmpeg smoke 另行覆盖。"""

from __future__ import annotations

from pathlib import Path

from app.media.render_executor import _text_overlay_dialogue, build_ffmpeg_command
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
        # transform 默认恒等 → 画面正中
        line = _text_overlay_dialogue(item, 1920, 1080)
        assert "\\an5" in line
        assert "\\pos(960.0,540.0)" in line  # 恒等 transform → 画面中心
        assert "\\fs64" in line
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
        line = _text_overlay_dialogue(item, 1000, 500)
        assert "\\pos(1000.0,0.0)" in line  # x=1→右缘, y=-1→上缘
        assert "\\frz-90.00" in line  # 顺时针 90° → ASS -90
        assert "\\fscx200.0\\fscy200.0" in line
        assert "\\alpha&H80&" in line  # opacity .5 → alpha 128


def test_text_overlay_triggers_ass_burn(tmp_path: Path) -> None:
    """有花字(即使没有字幕轨)也要生成 subtitles 滤镜把 ASS 烧进画面。"""
    plan = _plan_with_text([{
        "id": "t1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "标题",
    }])
    graph = " ".join(build_ffmpeg_command(plan, lambda k: tmp_path / k, tmp_path / "o.mp4"))
    assert "subtitles=filename=" in graph
    assert (tmp_path / "o.ass").exists()  # ASS 已落盘
