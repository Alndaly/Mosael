"""片段变换契约的后端一侧:跑 contracts/transform-cases.json。

前端 `transform.parity.test.ts` 跑**同一份文件**。

为什么需要契约:`_read_transform` 的原注释写着「Mirrors the frontend readTransform defaults」——
而它没有做到。抓到时的实际状态是**四份互不相同的答案**:

    写入 clean_transform          scale [0.1, 4]   x/y ±2    rotation ±180
    导出 _read_transform          scale [0.01,10]  x/y ±4    rotation % 360
    导出 _KF_RANGES(关键帧)      scale [0.01,10]  x/y ±4    rotation ±3600
    预览 readTransform            **一处都不钳**,而且数字字符串直接退回默认值

写入那份最严,所以另外几份从来没咬到过 —— 但那是"上游恰好挡住",不是两侧一致。任何绕过
`set_clip_transform` 的写入(插件、导入、手改库),预览与成片立刻是两个画面。

为什么不共用一份实现:同 ADR-0004 —— 预览要在浏览器里本地同步跑到 60fps,导出要无头、可外派。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.sequences.operations import TRANSFORM_BOUNDS, TRANSFORM_DEFAULTS
from app.media.render_executor import _kf_sample
from app.media.render_plan import _read_transform

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "transform-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _ids(section: str) -> list[str]:
    return [case["name"] for case in _load()[section]]


def test_contract_file_is_present_and_versioned() -> None:
    assert _CONTRACT.is_file(), f"变换契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "transform"
    assert isinstance(data["version"], int)
    assert data["normalize"] and data["sample"], "语料为空 = 没有任何一致性保护"


def test_bounds_and_defaults_match_the_contract() -> None:
    """合法范围只有一份 —— 语料说了算,不是三份实现各自说了算。"""
    data = _load()

    assert TRANSFORM_DEFAULTS == data["defaults"]
    assert {key: list(value) for key, value in TRANSFORM_BOUNDS.items()} == data["bounds"]


@pytest.mark.parametrize("case", _load()["normalize"], ids=_ids("normalize"))
def test_read_transform_matches_contract(case: dict) -> None:
    transform = _read_transform({"transform": case["raw"]})

    actual = {
        "scale": transform.scale,
        "x": transform.x,
        "y": transform.y,
        "rotation": transform.rotation,
        "opacity": transform.opacity,
    }

    assert actual == case["transform"], (
        f"{case['name']}\n  契约: {case['transform']}\n  实际: {actual}\n  用例理由: {case.get('why', '')}"
    )


@pytest.mark.parametrize("case", _load()["sample"], ids=_ids("sample"))
def test_keyframe_sampling_matches_contract(case: dict) -> None:
    """关键帧采样:分段线性、端点保持。`render_executor` 的注释声称与预览 sampleProp 锁步。"""
    points = tuple(
        sorted(
            (float(kf["t"]), float(kf[case["prop"]]))
            for kf in case["keyframes"]
            if isinstance(kf.get(case["prop"]), (int, float))
        )
    )

    actual = _kf_sample(points, case["base"], case["progress"])

    assert actual == pytest.approx(case["value"]), (
        f"{case['name']}\n  契约: {case['value']}\n  实际: {actual}\n  用例理由: {case.get('why', '')}"
    )
