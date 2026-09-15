"""自由元素(带蒙版/阴影的片段)的几何 —— 和前端跑**同一份**语料。

前端 features/editor/playback/freeElementGeometry.parity.test.ts 跑 contracts 里的同一个文件。
各写一遍的结果已经见过两次:先是圆的大小差 1.78 倍,修好大小之后圆里的**内容**又差 1.78 倍。
两次都要等到看成片才发现 —— 而两边各自的单元测试素材恰好和画幅同比例,那一档两种写法都对,
所以一次都没拦住。

这里核的是**滤镜串里真正写下的数字**,不是复述公式:铺满那一步(scale + crop)和圆形那一步
(crop=side:side) 都从 build_ffmpeg_command 的输出里读回来。公式抄一遍的话,抄错了两边一起错。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.media.render_executor import _appearance_filters
from app.media.render_plan import ClipAppearance, MaskSpec, ShadowSpec


CONTRACT = json.loads((Path(__file__).parents[2] / "contracts" / "clip-free-element-geometry.json").read_text())


def test_contract_is_versioned() -> None:
    assert CONTRACT["contract"] == "clip-free-element-geometry"
    assert CONTRACT["version"] == 1
    assert CONTRACT["cases"]


def _appearance(circle: bool) -> ClipAppearance:
    if circle:
        return ClipAppearance(mask=MaskSpec(shape="circle", radius=0.5), shadow=ShadowSpec())
    # 只有阴影也是自由元素 —— 这一档盯的是"不是圆也要按画幅裁"。
    return ClipAppearance(
        mask=MaskSpec(shape="none", radius=0.0),
        shadow=ShadowSpec(enabled=True, color="#000000", opacity=0.5, blur=8, offset_x=0, offset_y=0),
    )


def test_export_element_size_matches_the_shared_contract() -> None:
    for case in CONTRACT["cases"]:
        frame_w, frame_h = case["frame"]["width"], case["frame"]["height"]
        filters, _label, element_sized = _appearance_filters(
            "in", _appearance(case["circle"]), frame_w, frame_h, "p",
        )
        want = case["expected"]["element"]

        if case["circle"]:
            # 圆形先把**画幅那么大**的元素中心裁成正方 —— 边长就是元素尺寸。
            crop = re.search(r"crop=(\d+):(\d+):", ";".join(filters))
            assert crop, case["name"]
            assert (int(crop.group(1)), int(crop.group(2))) == (want["width"], want["height"]), case["name"]
        else:
            # 没有蒙版时不裁:元素就是铺满之后的画幅尺寸。
            assert "crop=" not in ";".join(filters), case["name"]
            assert (frame_w, frame_h) == (want["width"], want["height"]), case["name"]

        # element_sized 决定后面按元素自身尺寸缩放还是按画幅 —— 两档都必须是 True,
        # 否则 transform 的 scale 会乘错基准(圆会按画幅缩,阴影那档会丢掉外扩的透明边)。
        assert element_sized is True, case["name"]


def test_source_rect_is_element_over_cover_scale() -> None:
    """源区域 = 元素输出尺寸 ÷ 铺满系数,居中。

    导出侧这块是 `scale=W:H:force_original_aspect_ratio=increase` + `crop=W:H` 做的(它写在
    调用方的滤镜串里,不在 _appearance_filters 内),所以这里按同一条式子核语料本身自洽 ——
    前端那侧用同一批数字去断言 canvas 的 drawImage 源矩形。
    """
    for case in CONTRACT["cases"]:
        mw, mh = case["source"]["width"], case["source"]["height"]
        frame_w, frame_h = case["frame"]["width"], case["frame"]["height"]
        cover = max(frame_w / mw, frame_h / mh)
        element = case["expected"]["element"]
        rect = case["expected"]["source_rect"]

        assert rect["width"] == round(element["width"] / cover, 6), case["name"]
        assert rect["height"] == round(element["height"] / cover, 6), case["name"]
        assert rect["x"] == round((mw - element["width"] / cover) / 2, 6), case["name"]
        assert rect["y"] == round((mh - element["height"] / cover) / 2, 6), case["name"]
