"""工作流执行记录保留可检查的输出，同时对体积设硬上限。"""

from app.domain.workflows.engine import _OUTPUT_LIST_LIMIT, _trim_outputs


def test_片段列表保留每个值而不是只剩数量() -> None:
    clip_ids = [f"clip-{index}" for index in range(124)]

    assert _trim_outputs({"clip_ids": clip_ids})["clip_ids"] == clip_ids


def test_超大列表有界并明确说明还有多少项() -> None:
    values = list(range(_OUTPUT_LIST_LIMIT + 7))

    shown = _trim_outputs({"values": values})["values"]

    assert shown[:_OUTPUT_LIST_LIMIT] == values[:_OUTPUT_LIST_LIMIT]
    assert shown[-1] == "… 7 more items"
