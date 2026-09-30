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


def long_texts(outputs: dict[str, Any]) -> dict[str, str]:
    """快照会截断的那几个输出(顶层的长文字)。"""
    return {
        str(key): value
        for key, value in outputs.items()
        if isinstance(value, str) and len(value) > OUTPUT_TEXT_LIMIT
    }


def keep_full_texts(db: Session, job_id: str, node_id: str, texts: dict[str, str]) -> None:
    """记下这些输出的全文。同一次运行里同一个节点只跑完一次,不会重复写。"""
    for key, value in texts.items():
        db.add(WorkflowRunOutput(job_id=job_id, node_id=node_id, output_key=key, value=value))


def full_text(db: Session, job_id: str, node_id: str, key: str) -> str | None:
    return db.scalar(
        select(WorkflowRunOutput.value).where(
            WorkflowRunOutput.job_id == job_id,
            WorkflowRunOutput.node_id == node_id,
            WorkflowRunOutput.output_key == key,
        )
    )
