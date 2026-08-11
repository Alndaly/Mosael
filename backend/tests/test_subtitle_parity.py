"""字幕契约的后端一侧:跑 contracts/subtitle-cases.json。

前端 `subtitleStyle.parity.test.ts` 跑**同一份文件**。

为什么需要契约:字幕框的那几个数字(圆角 0.33em、内边距 0.16/0.55em、行高 1.45、最大宽度
86%、投影)在两侧**各手写了一遍** —— 预览在 Monitor.tsx 的 className 里,导出在
text_render._subtitle_style_css 里;竖直定位同样是两份(render_executor._subtitle_overlay_pos
的注释就写着「镜像预览 subtitleCss」)。这正是 ADR-0004 划给「必须逐字一致」那一侧的东西:
它决定**预览里看到的和导出的成片是不是同一个画面**,而 contracts/ 这套机制本来就是为一次
WYSIWYG 事故建的,只是当初只覆盖了场景层。

为什么不共用一份实现:同 ADR-0004 —— 预览要在浏览器里跟着显示尺寸缩放(所以字号用 cqw、
定位用百分比,由浏览器解析),导出要在原生帧上无头渲染(所以用 px 和 overlay 坐标)。两种
写法**在画幅原生宽度上解析到同一个像素值**,所以语料记的是解析后的结果,不是 CSS 写法。

**改语义时**:先改 contracts/subtitle-cases.json,看着两侧一起红,再改两侧实现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.media.render_executor import _subtitle_overlay_pos
from app.media.text_render import _subtitle_style_css

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "subtitle-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return _load()["cases"]


def _ids() -> list[str]:
    return [case["name"] for case in _cases()]


@dataclass
class _Style:
    """样式对象只按属性访问,不依赖 ORM —— 语料里的字段原样喂进去。"""

    font_size: float
    color: str
    bg_color: str
    bg_opacity: float
    bold: bool
    position: str
    offset: float
    font_family: str
    font_id: str


def _declarations(css: str) -> dict[str, str]:
    """`a:b;c:d` → {a: b}。font-family 里带逗号但不带分号,所以按分号切是安全的。"""
    out: dict[str, str] = {}
    for part in css.split(";"):
        if ":" in part:
            name, _, value = part.partition(":")
            out[name.strip()] = value.strip()
    return out


def test_contract_file_is_present_and_versioned() -> None:
    """语料找不到就静默跳过是最坏的结果 —— 那样两侧都「通过」,而契约根本没跑。"""
    assert _CONTRACT.is_file(), f"字幕契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "subtitle"
    assert isinstance(data["version"], int)
    assert data["cases"], "语料为空 = 没有任何一致性保护"


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_subtitle_box_matches_contract(case: dict) -> None:
    style = _Style(**case["style"])
    css = _declarations(_subtitle_style_css(style, case["frame"]["w"]))
    want = case["box"]

    actual = {
        "font_size_px": float(css["font-size"].removesuffix("px")),
        "color": css["color"],
        "font_weight": int(css["font-weight"]),
        "background": css["background"],
        "max_width_px": float(css["max-width"].removesuffix("px")),
        "border_radius": css["border-radius"],
        "padding": css["padding"],
        "line_height": css["line-height"],
        "text_align": css["text-align"],
        "text_shadow": css["text-shadow"],
        "white_space": css["white-space"],
    }
    expected = {**want, "font_size_px": float(want["font_size_px"]), "max_width_px": float(want["max_width_px"])}

    assert actual == expected, (
        f"{case['name']}\n  契约: {expected}\n  实际: {actual}\n  用例理由: {case.get('why', '')}"
    )


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_subtitle_placement_matches_contract(case: dict) -> None:
    style = _Style(**case["style"])
    place = case["placement"]

    x, y = _subtitle_overlay_pos(
        style, place["box_w"], place["box_h"], case["frame"]["w"], case["frame"]["h"]
    )

    assert (x, y) == (place["x"], place["y"]), (
        f"{case['name']}\n  契约: {(place['x'], place['y'])}\n  实际: {(x, y)}\n"
        f"  用例理由: {case.get('why', '')}"
    )
