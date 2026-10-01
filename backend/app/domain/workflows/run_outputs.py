"""运行产出的全文:事件快照截断了的长文字,另存一份给界面按需取。

事件(`workflow.node.finished`)和 `job.result` 里是有界快照 —— 它们随运行列表、事件流反复下发。
用户在「本次产出」里复制 / 下载的却该是那段文字本身:此前复制到的是前 2000 字加一个省略号,
而界面上看不出它被截过。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import WorkflowRunOutput

#: 快照里顶层文字留多少字。超过的在事件里截断,全文进 workflow_run_outputs。
OUTPUT_TEXT_LIMIT = 2000
#: 嵌在列表 / 对象里的文字留多少字(循环的 results、插件交回的结构)。超过的同样截断、同样另存全文。
NESTED_TEXT_LIMIT = 500
#: 列表留几项、对象留几个字段、往下看几层。
OUTPUT_LIST_LIMIT = 200
OUTPUT_OBJECT_LIMIT = 100
_MAX_DEPTH = 4


def snapshot(outputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """一个节点的产出 → (事件 / 结果里的有界快照, 被截断的那些文字的全文)。

    全文的键是**从输出名开始的点号路径**:顶层的 `text`,嵌在里面的 `results.3.text`(列表按下标、对象按键)。
    事件里的 `truncated` 用同一组键,界面据此标「已截断」、按路径来取全文。

    此前只有顶层的长文字另存了全文:循环交出的 `results` 里每一项的文字被截到 500 字、不标,复制到的就是半截。
    截断和记全文在**同一次遍历**里做 —— 分两处写,迟早一边截了、另一边没记。
    """
    cut: dict[str, str] = {}
    shown = {str(key): _trim(value, str(key), 0, cut) for key, value in outputs.items()}
    return shown, cut


def _trim(value: Any, path: str, depth: int, cut: dict[str, str]) -> Any:
    """把运行产出收敛成有界、但仍可检查的 JSON。

    旧实现把**所有数组**直接改成 ``"[124 items]"``。这控制了事件体积，却也把调试工作流最
    需要的内容永久丢掉了：用户知道生成了 124 个片段，却一个 id 都看不到。这里保留有限数量
    的真实元素，并递归限制字符串、对象宽度和深度；体积仍有上限，检查器也终于能逐项展开。
    """
    if isinstance(value, str):
        limit = OUTPUT_TEXT_LIMIT if depth == 0 else NESTED_TEXT_LIMIT
        if len(value) <= limit:
            return value
        cut[path] = value
        return value[:limit] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= _MAX_DEPTH:
        if isinstance(value, list):
            return f"[{len(value)} items]"
        if isinstance(value, dict):
            return f"[{len(value)} fields]"
        return str(value)[:NESTED_TEXT_LIMIT]
    if isinstance(value, list):
        shown = [_trim(item, f"{path}.{index}", depth + 1, cut) for index, item in enumerate(value[:OUTPUT_LIST_LIMIT])]
        if len(value) > OUTPUT_LIST_LIMIT:
            shown.append(f"… {len(value) - OUTPUT_LIST_LIMIT} more items")
        return shown
    if isinstance(value, dict):
        pairs = list(value.items())
        fields = {str(key): _trim(item, f"{path}.{key}", depth + 1, cut) for key, item in pairs[:OUTPUT_OBJECT_LIMIT]}
        if len(pairs) > OUTPUT_OBJECT_LIMIT:
            fields["…"] = f"{len(pairs) - OUTPUT_OBJECT_LIMIT} more fields"
        return fields
    return str(value)[:NESTED_TEXT_LIMIT]


def keep_full_texts(db: Session, job_id: str, node_id: str, texts: dict[str, str]) -> None:
    """记下这些输出的全文(键是 snapshot 给的路径)。同一次运行里同一个节点只跑完一次,不会重复写。"""
    for key, value in texts.items():
        db.add(WorkflowRunOutput(job_id=job_id, node_id=node_id, output_key=key, value=value))


def full_text(db: Session, job_id: str, node_id: str, key: str) -> str | None:
    """某次运行里某个节点某一处被截断的文字的全文;`key` 是 snapshot 给的路径(`text`、`results.3.text`)。"""
    return db.scalar(
        select(WorkflowRunOutput.value).where(
            WorkflowRunOutput.job_id == job_id,
            WorkflowRunOutput.node_id == node_id,
            WorkflowRunOutput.output_key == key,
        )
    )
