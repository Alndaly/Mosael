"""「拆成几批」节点:全量分析(评论区)和分批拉取都靠它。"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.basic import list_chunk
from tests.util import fresh_client


def _chunk(items, size=80):
    fresh_client()
    with SessionLocal() as db:
        return list_chunk(db, None, {"items": items, "size": size})


def test_等长拆批_顺序不变() -> None:
    out = _chunk(list(range(205)), size=80)
    assert out["count"] == 3 and out["total"] == 205
    assert [len(b) for b in out["batches"]] == [80, 80, 45]
    assert out["batches"][0][0] == 0 and out["batches"][-1][-1] == 204


def test_收_JSON_文本_也收真空() -> None:
    """整串引用落空/经模板节点出来时是文本;不是 JSON 数组的文本要明说,不悄悄当成一批。"""
    out = _chunk('[{"text": "a"}, {"text": "b"}]', size=1)
    assert out["count"] == 2 and out["batches"][1] == [{"text": "b"}]
    assert _chunk("")["count"] == 0 and _chunk(None)["count"] == 0
    with pytest.raises(WorkflowDomainError):
        _chunk("这不是一串")


def test_批量有下限也有上限() -> None:
    with pytest.raises(WorkflowDomainError):
        _chunk([1, 2, 3], size=0)  # 填 0 是写错了,报错,不悄悄变成默认
    out = _chunk(list(range(600)), size=9999)
    assert len(out["batches"]) == 2  # 上限 500
