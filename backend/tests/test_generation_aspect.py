"""「要几比几」翻成具体模型认的参数(ADR 0094 第二步):节点上记的是画幅,不是某个模型的尺寸 —— 换模型不丢。"""

from __future__ import annotations

import pytest

from app.domain.generation.aspect import parameters_for_aspect, ratio_of, size_for_aspect

#: ComfyUI 工作流(真跑时的 H3 图生视频):画幅在 `115.aspect_ratio` 这个节点输入上,选项写成「9:16 (Portrait Widescreen)」。
COMFY_H3 = {
    "parameter_keys": ["115.aspect_ratio", "115.megapixels", "first_frame"],
    "parameter_schema": {"115.aspect_ratio": {"enum": ["1:1 (Square)", "2:3 (Portrait Photo)", "9:16 (Portrait Widescreen)",
                                                       "16:9 (Widescreen)"]}},
}
#: gpt-image-2 这类:尺寸表里挑一档。
SIZE_TABLE = {"parameter_keys": ["size"], "sizes": ["1024x1024", "1024x1536", "1536x1024", "720x1280", "1280x720"],
              "default_size": "1024x1024"}
#: Seedance 这类:有画幅选项。
ASPECT_OPTIONS = {"parameter_keys": ["aspect_ratio", "resolution"], "aspect_ratios": ["16:9", "9:16", "1:1", "adaptive"]}
#: ComfyUI 的 EmptyLatentImage 宽高(任意尺寸,8 的倍数)。
CUSTOM = {"parameter_keys": ["size"], "sizes": ["1024x1024"], "default_size": "1024x1024",
          "custom_size": {"minimum": 64, "multiple_of": 8}}


@pytest.mark.parametrize(("caps", "expected"), [
    (ASPECT_OPTIONS, {"aspect_ratio": "9:16"}),
    (COMFY_H3, {"115.aspect_ratio": "9:16 (Portrait Widescreen)"}),
    (SIZE_TABLE, {"size": "720x1280"}),
])
def test_按模型认的那一格翻(caps: dict, expected: dict) -> None:
    assert parameters_for_aspect(caps, "9:16", {}) == expected


def test_任意尺寸_按默认那一档的面积取这个画幅() -> None:
    [(key, value)] = parameters_for_aspect(CUSTOM, "9:16", {}).items()
    width, height = (int(one) for one in value.split("x"))
    assert key == "size" and width % 8 == 0 and height % 8 == 0
    assert ratio_of(value) == pytest.approx(9 / 16, rel=0.02)
    assert width * height == pytest.approx(1024 * 1024, rel=0.05)


def test_写明了的优先_什么都不加() -> None:
    assert parameters_for_aspect(SIZE_TABLE, "9:16", {"size": "1024x1024"}) == {}
    assert parameters_for_aspect(COMFY_H3, "9:16", {"115.aspect_ratio": "16:9 (Widescreen)"}) == {}


def test_对不上就不硬塞() -> None:
    assert parameters_for_aspect({"parameter_keys": ["seed"]}, "9:16", {}) == {}
    assert parameters_for_aspect(ASPECT_OPTIONS, "21:9", {}) == {}, "选项里没有 21:9,不挑一个最近的冒充"
    assert parameters_for_aspect(SIZE_TABLE, "", {}) == {}
    assert parameters_for_aspect(None, "9:16", {}) == {}


def test_尺寸表里的画幅比写法也认() -> None:
    assert size_for_aspect(["16:9", "9:16"], "9:16") == "9:16"
    assert size_for_aspect(["832*480", "480*832"], "16:9") == "832*480"
