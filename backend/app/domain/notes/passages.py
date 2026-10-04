"""笔记正文的**按段**修改:把一段原文换成新的,或者在一段原文前后插入。智能体的 edit_note 用它。

**锚点是原文本身**(像编辑器里的查找替换),不是字符偏移:模型数不准字数,而原文它可以从 read_note
或笔记页给的上下文里照抄。每个锚点必须在正文里**恰好出现一次** —— 出现多次时改哪一处是猜的,猜错了
就是改了用户没让改的那一句。

算子按顺序落在上一步的结果上。纯函数:不碰库,开卡时干跑、批准时落在那一刻的正文上,都是这一份。
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.notes import NoteDomainError

PASSAGE_OP_KINDS = ("replace", "insert")


def apply_passage_edits(markdown: str, operations: list[Any]) -> str:
    if not isinstance(operations, list) or not operations:
        raise NoteDomainError("noteErr_passageNoOps")
    text = markdown
    for index, operation in enumerate(operations, 1):
        kind = operation.get("kind") if isinstance(operation, dict) else None
        if kind not in PASSAGE_OP_KINDS:
            raise NoteDomainError("noteErr_passageOpUnknown", index=index, kind=str(kind))
        new = operation.get("text")
        if not isinstance(new, str):
            raise NoteDomainError("noteErr_passageTextMissing", index=index)
        if kind == "replace":
            anchor = operation.get("find")
            start = _locate(text, anchor, index, "find")
            text = text[:start] + new + text[start + len(anchor):]
            continue
        after, before = operation.get("after"), operation.get("before")
        if bool(after) == bool(before):
            raise NoteDomainError("noteErr_passageInsertWhere", index=index)
        at = _locate(text, after, index, "after") + len(after) if after else _locate(text, before, index, "before")
        text = text[:at] + new + text[at:]
    return text


def _locate(text: str, anchor: Any, index: int, field: str) -> int:
    """锚点在正文里的位置。没有、或者能落在不止一处(**重叠的也算**:「哈哈」在「哈哈哈」里有两处)都拒。"""
    if not isinstance(anchor, str) or not anchor:
        raise NoteDomainError("noteErr_passageAnchorEmpty", index=index, field=field)
    start = text.find(anchor)
    if start < 0:
        raise NoteDomainError("noteErr_passageNotFound", index=index, field=field, excerpt=anchor[:80])
    if text.find(anchor, start + 1) >= 0:
        count = len(re.findall(f"(?={re.escape(anchor)})", text))
        raise NoteDomainError("noteErr_passageAmbiguous", index=index, field=field, count=count)
    return start
