"""一次保存是接着写最新那一版(改写它),还是开新的一版;以及每一版相对上一版改了多少。

编辑器停笔 700ms 就自动保存一次。每次保存都开一版的话,版本记录里「版本 3 到 6」会在 7 秒内连着出现。所以连续的
手动编辑在**存储上**合成一版 —— 窗口内的保存改写最新那一版,判据(`continues`):

- 这次保存和最新那一版都是编辑器里的保存(origin = edit),而且是同一个人;
- 离那一版最后一次保存不到 EDIT_PAUSE —— 停笔超过这么久再动笔,是新的一版;
- 那一版从开始写起不到 EDIT_SPAN —— 一口气写一个小时,版本记录里也每半小时有一个能回去的点;
- 智能体改的、恢复的、追加的、新建的、画板和工作流写的,永远单独成版,它后面的编辑也另起一版。

改写只发生在**最新**那一版上:更早的版本一旦有了后一版就不再变。乐观并发不看版本号,看保存序号(Note.save_seq)。

每一版记下相对**上一版**新加 / 删掉的字数(不算空白)和标题改没改,版本记录里那一句「+120 −30 字」就是它。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.db.models import NoteRevision

EDIT_PAUSE = timedelta(minutes=5)
EDIT_SPAN = timedelta(minutes=30)
#: 改了的那几行两边字数之积超过它就不逐字对齐,整块算删掉 + 新加(数字偏大,但不会让一次保存卡住)。
CHAR_ALIGN_LIMIT = 4_000_000


def continues(latest: NoteRevision | None, *, origin: str, created_by: str | None, at: datetime) -> bool:
    """这次保存是不是接着写最新那一版(是就改写它,不是就开新的一版)。"""
    return (
        latest is not None
        and origin == "edit"
        and latest.origin == "edit"
        and created_by is not None
        and latest.created_by == created_by
        and at - latest.created_at <= EDIT_PAUSE
        and at - latest.started_at <= EDIT_SPAN
    )


def _visible(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def count_changes(before: str, after: str) -> tuple[int, int]:
    """(新加的字数, 删掉的字数),不算空白。先按行对齐,改了的那几行再逐字对齐 —— 改了开头和结尾两处,
    数的是那两处的字,不是中间整篇。"""
    if before == after:
        return 0, 0
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    added = removed = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old, new = "".join(a[i1:i2]), "".join(b[j1:j2])
        if tag != "replace" or len(old) * len(new) > CHAR_ALIGN_LIMIT:
            removed += _visible(old)
            added += _visible(new)
            continue
        for inner, k1, k2, l1, l2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if inner != "equal":
                removed += _visible(old[k1:k2])
                added += _visible(new[l1:l2])
    return added, removed


def changes_since_previous(db: Session, note_id: str, revision: int, data: dict) -> dict:
    """第 revision 版相对第 revision - 1 版改了多少。第 1 版之前什么都没有:正文全算新加,标题不算「改了」。"""
    base = db.get(NoteRevision, (note_id, revision - 1)) if revision > 1 else None
    before = base.snapshot if base is not None else {}
    added, removed = count_changes(str(before.get("markdown") or ""), str(data.get("markdown") or ""))
    return {
        "chars_added": added,
        "chars_removed": removed,
        "title_changed": base is not None and before.get("title") != data.get("title"),
    }
