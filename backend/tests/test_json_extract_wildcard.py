"""按路径取值时 `*` 表示「这一串里的每一个」:从循环交出的一串结果里取出每一项的某一格。

模特上身图要把每一组的视频也列进输出:循环交出的是每一组的全部产物,「每一组的视频」就是
`*.on_model_clip.asset_id`。哪一组没有这一格(视频没出来)就不在结果里,不拿空值占位。
"""

from __future__ import annotations

from app.domain.workflows.executors import get_executor

RESULTS = [
    {"on_model": {"asset_id": "img-1"}, "on_model_clip": {"asset_id": "clip-1"}},
    {"on_model": {"asset_id": "img-2"}},
    {"on_model": {"asset_id": "img-3"}, "on_model_clip": {"asset_id": "clip-3"}},
]


def _extract(source, path: str) -> dict:
    return get_executor("json_extract")(None, None, {"source": source, "path": path})


def test_星号取出每一项的那一格_没有那一格的不占位() -> None:
    assert _extract(RESULTS, "*.on_model_clip.asset_id")["value"] == ["clip-1", "clip-3"]
    assert _extract(RESULTS, "*.on_model.asset_id")["value"] == ["img-1", "img-2", "img-3"]


def test_星号可以在路径中间_也收_JSON_文本() -> None:
    import json

    wrapped = {"results": RESULTS}
    assert _extract(wrapped, "results.*.on_model.asset_id")["value"] == ["img-1", "img-2", "img-3"]
    assert _extract(json.dumps(wrapped), "results.*.on_model_clip.asset_id")["text"] == '["clip-1", "clip-3"]'


def test_没有星号照旧取一格() -> None:
    assert _extract(RESULTS, "0.on_model.asset_id")["value"] == "img-1"
    assert _extract(RESULTS, "1.on_model_clip.asset_id")["value"] is None
