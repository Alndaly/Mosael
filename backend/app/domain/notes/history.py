"""一版笔记归在哪一组、相对这一组之前那一版改了多少 —— 版本记录一组一项(见 tests/test_note_revision_groups.py)。

编辑器停笔 700ms 就自动保存一次,每次保存都是一版:修订号同时是乐观并发的基准、来源 / 画板文档格 / 引用链接钉住的
那一版,所以**每次保存照旧落一行,一行都不删不改**。合成一版的是**版本记录里的一项**:每一版落库时记下它归在哪一组
(`group_start`:这一组第一版的号),判据:

- 这一版和上一版都是编辑器里的保存(origin = edit),而且是同一个人;
- 离上一版不到 EDIT_PAUSE —— 停笔超过这么久再动笔,是新的一版;
- 离这一组第一版不到 EDIT_SPAN —— 一口气写一个小时,版本记录里也隔半小时有一个能回去的点;
- 智能体改的、恢复的、追加的、新建的、画板和工作流写的,永远单独成一组,它后面的编辑也另起一组。

每一版还记下相对**这一组之前那一版**改了多少:新加 / 删掉的字数(不算空白)、标题改没改。一组里最新那一版的这几个数,
就是这一组一共改了多少 —— 列表上那一句「+120 −30 字」。
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


def group_start(db: Session, note_id: str, revision: int, *, origin: str, created_by: str | None, at: datetime) -> int:
    """这一版归在哪一组(返回那一组第一版的号;自己起一组就是自己的号)。"""
    if origin != "edit" or created_by is None or revision == 1:
        return revision
    previous = db.get(NoteRevision, (note_id, revision - 1))
    if previous is None or previous.origin != "edit" or previous.created_by != created_by:
        return revision
    if at - previous.created_at > EDIT_PAUSE:
        return revision
    first = previous if previous.group_start == previous.revision else db.get(NoteRevision, (note_id, previous.group_start))
    if first is None or at - first.created_at > EDIT_SPAN:
        return revision
    return previous.group_start


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


def changes_since_group(db: Session, note_id: str, start: int, data: dict) -> dict:
    """相对这一组之前那一版(第 start - 1 版)改了多少。第一组之前什么都没有:正文全算新加,标题不算「改了」。"""
    base = db.get(NoteRevision, (note_id, start - 1)) if start > 1 else None
    before = base.snapshot if base is not None else {}
    added, removed = count_changes(str(before.get("markdown") or ""), str(data.get("markdown") or ""))
    return {
        "chars_added": added,
        "chars_removed": removed,
        "title_changed": base is not None and before.get("title") != data.get("title"),
    }
