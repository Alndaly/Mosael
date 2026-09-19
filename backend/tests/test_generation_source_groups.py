"""生成节点的素材清单:整组接进来、按组取用。

整片流程里每一镜走哪条路(首尾帧 / 参考素材)是逐镜决定的,而 Seedance 上两组互斥。所以:

- 参考图常常是**一整组**上游结果(全部角色的三视图)—— `{{角色三视图.results}}` 这种整串引用
  插值后保留列表原样,解析时要摊平,和一条一条写出来是一回事;
- 两组都接上,由「用哪一组素材」选一组 —— 丢掉的是与它互斥的那一组,别的角色不受影响。
"""

from __future__ import annotations

import pytest

from app.domain.generation.operations import GenerationDomainError, keep_source_group, parse_source_assets


def test_一项是一整组时摊平() -> None:
    sheets = ["hero:reference_image", "villain:reference_image"]
    parsed = parse_source_assets(["first:first_frame", sheets, "move:reference_video"], kind="video")
    assert [(one["asset_id"], one["role"]) for one in parsed] == [
        ("first", "first_frame"), ("hero", "reference_image"), ("villain", "reference_image"), ("move", "reference_video"),
    ]


def test_没跑的那一项是空的_自然消失() -> None:
    """尾帧节点在条件分支里没跑时,`{{尾帧.asset_id}}:last_frame` 插值成 `:last_frame`。"""
    parsed = parse_source_assets(["first:first_frame", ":last_frame"], kind="video")
    assert [one["role"] for one in parsed] == ["first_frame"]


SOURCES = [
    {"asset_id": "f", "role": "first_frame"},
    {"asset_id": "l", "role": "last_frame"},
    {"asset_id": "sheet", "role": "reference_image"},
    {"asset_id": "move", "role": "reference_video"},
    {"asset_id": "clip", "role": "source_video"},
]


def test_只用首尾帧() -> None:
    assert [one["asset_id"] for one in keep_source_group(SOURCES, "keyframes")] == ["f", "l", "clip"]


def test_只用参考素材() -> None:
    assert [one["asset_id"] for one in keep_source_group(SOURCES, "references")] == ["sheet", "move", "clip"]


def test_全部就是原样() -> None:
    assert keep_source_group(SOURCES, "all") == SOURCES


def test_写错了当场说() -> None:
    with pytest.raises(GenerationDomainError, match="素材分组"):
        keep_source_group(SOURCES, "keyframe")
