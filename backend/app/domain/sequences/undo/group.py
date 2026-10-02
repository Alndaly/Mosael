"""操作组(见 sequences/grouping.py)的逆向/正向重放:按步骤逆序撤、正序重做。

每一步怎么撤,由那一步自己的 kind 在注册表里登记的那一对说了算 —— 组不认识任何具体操作,
所以组里能放什么不需要另一份清单。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Sequence
from app.domain.sequences.undo.registry import _pair, undoable


@undoable("operation_group")
class OperationGroup:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for step in reversed(payload.get("steps") or []):
            _pair(step["kind"]).inverse(db, sequence, step["payload"])
            # 每一步之后落一次:后一步(逆序的前一步)可能要按 id 找回这一步刚重建的行。
            db.flush()

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for step in payload.get("steps") or []:
            _pair(step["kind"]).forward(db, sequence, step["payload"])
            db.flush()
