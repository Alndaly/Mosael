"""建表与历史数据迁移 —— **依赖序的顶端**,爱 import 谁 import 谁。

从 `app/core/db.py` 搬出来的。那里是被所有人 import 的底座,而迁移必须认识领域层
(声音克隆的共用 venv 往哪搬、插件表怎么拆成包/实例/能力),两者方向相反。挤在一个模块
里的那段时间,这些 import 只能写在函数体里把环推迟到运行时;搬出来之后写在文件顶上即可。

**新增迁移就写在这里,并挂进 `init_db()`** —— 顺序有讲究,函数各自的 docstring 说明了
自己必须排在 create_all 之前还是之后。仓库不用 alembic:每条迁移都先探 schema 再动手
(见各函数开头的 `inspect(engine)`),重复跑是安全的。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from app.core.config import LOGIN_SESSION_TTL, settings
from app.core.db import Base, PARTITION_PREFIX, engine
from app.core.tokens import TOKEN_SCHEME, token_digest
from app.db.migration_runner import MigrationPhase, MigrationPlan, MigrationStep
from app.db.model_base import now
from app.db.safety import DATABASE_SCHEMA_VERSION, mark_database_version, snapshot_before_upgrade

logger = logging.getLogger(__name__)


def _migrate_tool_confirmations_session() -> None:
    """tool_confirmations 新增 session_id 列(确认卡归属于哪次智能体会话)。

    create_all 只建新表,不给**已有**表补列。这列可空:MCP / 飞书等外部智能体没有会话。
    老行留空 → 它们照旧由全局确认中心兜底,不会突然从某个对话里消失。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    if "session_id" in {c["name"] for c in inspector.get_columns("tool_confirmations")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN session_id VARCHAR(64)"))


def _migrate_tool_confirmations_name_their_tool_call() -> None:
    """tool_confirmations 新增 tool_call_id 列:卡是那次对话里哪一次工具调用开的。

    create_all 只建新表,不给已有表补列。这列可空:MCP 直连等外部智能体开的卡不是对话里的某一步。
    老卡不回填 —— 已有结论的卡此前就不在对话里留存(批完只在当时那个界面的内存里留一张,刷新即无),
    没有可以「摆回去」的东西;重启时还在等的会话卡已被 reconcile_orphaned_agent_sessions 作废。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    if "tool_call_id" in {c["name"] for c in inspector.get_columns("tool_confirmations")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN tool_call_id VARCHAR(128)"))


def _migrate_note_revisions_remember_where_they_came_from() -> None:
    """笔记的每一版补三列:怎么来的 `origin`、替谁写的 `created_by`、从哪一版恢复的 `restored_from`。

    加列必须在 SCHEMA 之前:之后 ORM 上的 NoteRevision 已经指望这三列在了。老版本按推得出来的回填:

    - 第 1 版是新建(create_note 写的永远是第 1 版);
    - 批准过的改笔记确认卡(tool_confirmations 里 tool = edit_note、status = executed)结果里记着笔记和修订号,
      那一版是智能体改的,作者记批准它的人(那个人已经不在了就留空);
    - 其余记成编辑。恢复、追加当时没留痕,推不出来;作者也留空 —— 说不出是谁。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(note_revisions)"))}
        if not columns or "origin" in columns:
            return
        conn.execute(text("ALTER TABLE note_revisions ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'edit'"))
        conn.execute(text(
            "ALTER TABLE note_revisions ADD COLUMN created_by VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL"
        ))
        conn.execute(text("ALTER TABLE note_revisions ADD COLUMN restored_from INTEGER"))
        conn.execute(text("UPDATE note_revisions SET origin = 'create' WHERE revision = 1"))
        cards = {row[1] for row in conn.execute(text("PRAGMA table_info(tool_confirmations)"))}
        if not {"tool", "status", "result", "decided_by"} <= cards:
            return
        executed = conn.execute(text(
            "SELECT result, decided_by FROM tool_confirmations WHERE tool = 'edit_note' AND status = 'executed'"
        )).all()
        for result, decided_by in executed:
            try:
                landed = json.loads(result) if isinstance(result, str) else result
                note_id, revision = str(landed["note_id"]), int(landed["revision"])
            except (TypeError, ValueError, KeyError):
                continue
            conn.execute(text(
                "UPDATE note_revisions SET origin = 'agent', created_by = (SELECT id FROM users WHERE id = :by) "
                "WHERE note_id = :note AND revision = :revision"
            ), {"by": decided_by, "note": note_id, "revision": revision})


def _migrate_notes_count_their_saves() -> None:
    """笔记补一列保存序号 `save_seq`:乐观并发从此认它,版本号(revision)只管版本记录。

    加列必须在 SCHEMA 之前:之后 ORM 上的 Note 已经指望它在了。从当前版本号起数 —— 起点是多少不要紧,
    只要以后每次写入都 +1;取版本号是让老库里每篇的序号都不小于它已经走过的写入次数。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(notes)"))}
        if not columns or "save_seq" in columns:
            return
        conn.execute(text("ALTER TABLE notes ADD COLUMN save_seq INTEGER NOT NULL DEFAULT 1"))
        conn.execute(text("UPDATE notes SET save_seq = revision"))


def _migrate_note_revisions_take_the_merged_shape() -> None:
    """笔记的版本表收成「连续编辑在存储上合成一版」那个样子:补上从什么时候开始写 `started_at`、相对上一版改了多少
    (`chars_added` / `chars_removed` / `title_changed`),去掉分组那一列 `group_start`。

    取代了 1.8.3 开发期的 note-revisions-fold-consecutive-edits(它只在界面上分组,加的 group_start 现在没用了;
    它靠「group_start 在不在」判断跑没跑过,在新样子的库上重跑会撞上重复的列,所以整步拿掉)。老库停在哪一步都收得拢:
    跑过那一步的有 group_start 和字数列,没跑过的两样都没有。加列、删列都必须在 SCHEMA 之前。
    老版本的开始时间就是它落库的时间;字数先记 0,老库里的碎版本由后面的 merge-consecutive-edits 真正合并,字数在那里重算。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(note_revisions)"))}
        if not columns:
            return
        for name, kind in (("chars_added", "INTEGER NOT NULL DEFAULT 0"), ("chars_removed", "INTEGER NOT NULL DEFAULT 0"),
                           ("title_changed", "BOOLEAN NOT NULL DEFAULT 0")):
            if name not in columns:
                conn.execute(text(f"ALTER TABLE note_revisions ADD COLUMN {name} {kind}"))
        if "started_at" not in columns:
            conn.execute(text("ALTER TABLE note_revisions ADD COLUMN started_at DATETIME"))
            conn.execute(text("UPDATE note_revisions SET started_at = created_at"))
        if "group_start" in columns:
            conn.execute(text("ALTER TABLE note_revisions DROP COLUMN group_start"))


def _migrate_note_revisions_guess_where_they_came_from() -> None:
    """老版本的来历尽量补出来。只动说不出是谁写的老版本(created_by 为空、记成新建 / 编辑的那些)。

    补来历那一步(remember-where-they-came-from)只认得出第 1 版是新建、批准过的改笔记卡是智能体改的。这里再往下推,
    先看留了记录的,再看内容:
    - board_write 任务的产出里记着笔记和版本号 → 画板写入,作者是点「写」的人;
    - 对话记录里 create_note / append_note 的结果记着笔记和版本号 → 智能体修改,作者是对话的主人;
    - 工作流运行事件里「存成笔记」节点的产出(有引用链接、没有正文,版本 1)→ 工作流写入;
    - 标题、正文、来源和更早的某一版一模一样,又和紧挨着的上一版不同,而且那一版在这一口气之前(两版之间隔过一次超过
      5 分钟的停笔)→ 从那一版恢复(取最近的那一版)。同一口气里打了几个字又删回去,内容也会和两版之前一样,那是编辑;
    - 在上一版末尾隔一个空行接了一段、来源也多了 → 存到笔记(追加);
    - 推不出来的才留着「手动编辑」。和上一版内容一样的(只改了属性)不在这里管,由 merge-consecutive-edits 清掉。
    要读任务、对话、运行事件,所以排在 SCHEMA 之后、合并那一步之前(合并时恢复的那一版要单独成版)。
    """
    with engine.begin() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}

        def columns(table: str) -> set[str]:
            return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))} if table in tables else set()

        if not {"origin", "created_by", "restored_from", "snapshot"} <= columns("note_revisions"):
            return
        rows = conn.execute(text(
            "SELECT note_id, revision, snapshot, origin, created_by, created_at FROM note_revisions ORDER BY note_id, revision"
        )).all()
        unknown = {(note_id, revision) for note_id, revision, _, origin, created_by, _ in rows
                   if created_by is None and origin in ("create", "edit") and isinstance(revision, int)}
        if not unknown:
            return
        users = {row[0] for row in conn.execute(text("SELECT id FROM users"))} if "users" in tables else set()

        def parsed(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            try:
                return json.loads(value)
            except ValueError:
                return None

        found: dict[tuple[str, int], tuple[str, str | None]] = {}

        def note_at(note_id: Any, revision: Any) -> tuple[str, int] | None:
            if isinstance(note_id, str) and isinstance(revision, int) and not isinstance(revision, bool):
                return note_id, revision
            return None

        if {"kind", "result", "created_by"} <= columns("jobs"):
            for result, created_by in conn.execute(text(
                "SELECT result, created_by FROM jobs WHERE kind = 'board_write' AND result LIKE '%note_id%'"
            )):
                for output in (parsed(result) or {}).get("outputs") or []:
                    key = note_at(output.get("note_id"), output.get("revision")) if isinstance(output, dict) else None
                    if key and output.get("type") == "note":
                        found.setdefault(key, ("board", created_by))
        if {"payload", "session_id"} <= columns("agent_messages") and "owner_user_id" in columns("agent_sessions"):
            for payload, owner in conn.execute(text(
                "SELECT m.payload, s.owner_user_id FROM agent_messages m JOIN agent_sessions s ON s.id = m.session_id "
                "WHERE m.payload LIKE '%create_note%' OR m.payload LIKE '%append_note%'"
            )):
                timeline = (parsed(payload) or {}).get("timeline") if isinstance(parsed(payload), dict) else None
                for item in timeline or []:
                    tool = item.get("tool") if isinstance(item, dict) else None
                    if not isinstance(tool, dict) or tool.get("name") not in ("create_note", "append_note") or tool.get("status") != "done":
                        continue
                    result = tool.get("result")
                    content = result.get("content") if isinstance(result, dict) else None
                    text_part = content[0].get("text") if isinstance(content, list) and content and isinstance(content[0], dict) else None
                    note = parsed(text_part)
                    key = note_at(note.get("id"), note.get("revision")) if isinstance(note, dict) else None
                    if key:
                        found.setdefault(key, ("agent", owner))
        if {"job_id", "payload"} <= columns("task_events") and {"kind", "created_by"} <= columns("jobs"):
            for payload, created_by in conn.execute(text(
                "SELECT t.payload, j.created_by FROM task_events t JOIN jobs j ON j.id = t.job_id "
                "WHERE j.kind = 'workflow' AND t.payload LIKE '%citation_url%'"
            )):
                outputs = (parsed(payload) or {}).get("outputs") if isinstance(parsed(payload), dict) else None
                if isinstance(outputs, dict) and "citation_url" in outputs and "markdown" not in outputs \
                        and outputs.get("revision") == 1:
                    key = note_at(outputs.get("note_id"), 1)
                    if key:
                        found.setdefault(key, ("workflow", created_by))

        guessed = {key: (origin, by if by in users else None, None) for key, (origin, by) in found.items() if key in unknown}

        def content(snapshot: Any) -> tuple[str, str, str]:
            data = parsed(snapshot)
            data = data if isinstance(data, dict) else {}
            return (str(data.get("title") or ""), str(data.get("markdown") or ""),
                    json.dumps(data.get("sources") or [], ensure_ascii=False, sort_keys=True))

        def moment(value: Any) -> Any:
            from datetime import datetime

            try:
                return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            except ValueError:
                return None

        def paused_between(versions: list[Any], start: int, end: int) -> bool:
            """versions[start] 到 versions[end] 之间有没有一次超过 5 分钟的停笔(说不出时间的算有)。"""
            from datetime import timedelta

            for one, two in zip(versions[start:end], versions[start + 1:end + 1]):
                if one[2] is None or two[2] is None or two[2] - one[2] > timedelta(minutes=5):
                    return True
            return False

        by_note: dict[str, list[tuple[int, tuple[str, str, str], Any]]] = {}
        for note_id, revision, snapshot, _, _, created_at in rows:
            if isinstance(revision, int):
                by_note.setdefault(note_id, []).append((revision, content(snapshot), moment(created_at)))
        for note_id, versions in by_note.items():
            for index, (revision, this, _) in enumerate(versions):
                key = (note_id, revision)
                if key not in unknown or key in guessed or index == 0:
                    continue
                before = versions[index - 1][1]
                if this == before:
                    continue
                earlier = [position for position, (_, other, _) in enumerate(versions[:index - 1]) if other == this]
                if earlier and paused_between(versions, earlier[-1], index):
                    guessed[key] = ("restore", None, versions[earlier[-1]][0])
                    continue
                prefix = before[1] + "\n\n"
                old_sources, new_sources = json.loads(before[2]), json.loads(this[2])
                if before[1] and this[1].startswith(prefix) and len(this[1]) > len(prefix) \
                        and len(new_sources) > len(old_sources) and new_sources[:len(old_sources)] == old_sources:
                    guessed[key] = ("append", None, None)

        for (note_id, revision), (origin, created_by, restored_from) in guessed.items():
            conn.execute(text(
                "UPDATE note_revisions SET origin = :origin, created_by = :by, restored_from = :restored "
                "WHERE note_id = :note AND revision = :revision"
            ), {"origin": origin, "by": created_by, "restored": restored_from, "note": note_id, "revision": revision})
        counts: dict[str, int] = {}
        for origin, _, _ in guessed.values():
            counts[origin] = counts.get(origin, 0) + 1
        logger.info("note revisions: guessed origins for %d old revisions %s", len(guessed), counts)


def _migrate_note_revisions_merge_consecutive_edits() -> None:
    """老库里的碎版本在存储上真正合并,版本号重排成连着的,库里所有指向老版本号的引用改指过去。

    写入时合并(domain/notes/history)只管以后;老库里每次自动保存都落了一行。这一步按同一条判据整理每一篇:
    - 和上一版一模一样的版本(标题、正文、来源都一样:只改了属性,或一口气写了又写回去)删掉,指向它的引用改指到上一版;
    - 连续的手动编辑(同一个人、相邻都是编辑、停笔不到 5 分钟、一版从开始写起不到 30 分钟)合成一版:留下组里最后
      一版的内容和最后保存时间,开始时间取组里第一版的,其余的行删掉。老数据说不出是谁写的,空和空算同一个人;
    - 其余(智能体、恢复、追加、新建、画板、工作流)单独成版;
    - 版本号重排成从 1 起连着的,笔记的当前版本号跟着改;恢复自哪一版也换成新的号;
    - 「相对上一版改了多少」按合并后的上一版重算;
    - 一直并到不能再并为止(并掉一组之后,前后两组可能又挨上、满足判据)。
    然后把库里所有指向老版本号的引用改指到新的号:任何 JSON 里 note_id 旁边的 revision / note_revision、kind 为 note
    的来源(笔记的来源、画板文档格、改笔记确认卡的结果、任务产出、对话记录……),以及任何文字里的笔记引用链接
    `#/notes?note=…&revision=N`(笔记正文、各版快照、对话、提示词……)。指向不存在的版本的原样不动。

    排在补来历那一步之后:恢复出来的版本要单独成版。判据和算法都抄在这里,不引领域层 —— 领域那边日后改了,
    重放这条迁移得到的还该是今天的结果。整理过的库再跑一遍什么都不变(合并后的相邻两版不再满足判据,版本号已经连着)。
    """
    import re
    from datetime import datetime, timedelta
    from difflib import SequenceMatcher
    from urllib.parse import unquote

    pause, span = timedelta(minutes=5), timedelta(minutes=30)
    with engine.begin() as conn:
        tables = {row[0]: row[1] or "" for row in conn.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))}

        def columns(table: str) -> dict[str, str]:
            return {row[1]: (row[2] or "").upper() for row in conn.execute(text(f'PRAGMA table_info("{table}")'))} if table in tables else {}

        needed = {"snapshot", "origin", "created_by", "restored_from", "chars_added", "chars_removed", "title_changed", "started_at"}
        if not needed <= set(columns("note_revisions")) or "revision" not in columns("notes"):
            return

        def visible(value: str) -> int:
            return sum(1 for char in value if not char.isspace())

        def changes(before: str, after: str) -> tuple[int, int]:
            if before == after:
                return 0, 0
            a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
            added = removed = 0
            for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
                if tag == "equal":
                    continue
                old, new = "".join(a[i1:i2]), "".join(b[j1:j2])
                if tag != "replace" or len(old) * len(new) > 4_000_000:
                    removed, added = removed + visible(old), added + visible(new)
                    continue
                for inner, k1, k2, l1, l2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                    if inner != "equal":
                        removed, added = removed + visible(old[k1:k2]), added + visible(new[l1:l2])
            return added, removed

        def moment(value: Any) -> datetime | None:
            try:
                return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            except ValueError:
                return None

        def parsed(value: Any) -> dict:
            try:
                data = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}

        rows = conn.execute(text(
            "SELECT note_id, revision, snapshot, origin, created_by, restored_from, started_at, created_at "
            "FROM note_revisions ORDER BY note_id, revision"
        )).all()
        by_note: dict[str, list[Any]] = {}
        for row in rows:
            by_note.setdefault(row[0], []).append(row)
        moves: dict[str, dict[int, int]] = {}
        totals = {"before": len(rows), "after": 0, "property_only": 0, "merged": 0, "references": 0}
        for note_id, versions in by_note.items():
            if any(not isinstance(row[1], int) for row in versions):
                totals["after"] += len(versions)
                continue
            entries: list[dict[str, Any]] = []
            for _, revision, snapshot, origin, created_by, restored_from, started_at, created_at in versions:
                data = parsed(snapshot)
                entries.append({
                    "members": [revision], "snapshot": snapshot, "data": data, "origin": origin, "created_by": created_by,
                    "restored_from": restored_from, "started_at": started_at or created_at, "created_at": created_at,
                    "began": moment(started_at) or moment(created_at), "saved": moment(created_at),
                    "content": (str(data.get("title") or ""), str(data.get("markdown") or ""),
                                json.dumps(data.get("sources") or [], ensure_ascii=False, sort_keys=True)),
                })
            #: 一直并到不能再并为止:一口气写完的一组,最后可能正好写回上一版的样子(打了又删),
            #: 那一组并掉之后,前后两组又可能挨上、满足判据。一次就收到不动点,重跑才什么都不变。
            while True:
                kept: list[dict[str, Any]] = []
                for entry in entries:
                    last = kept[-1] if kept else None
                    if last is not None and entry["content"] == last["content"]:
                        #: 和上一版一模一样(只改了属性,或写了又写回去):这一版不留,引用改指到上一版。
                        last["members"] += entry["members"]
                        totals["property_only"] += len(entry["members"])
                    elif last is not None and entry["origin"] == "edit" and last["origin"] == "edit" \
                            and entry["created_by"] == last["created_by"] \
                            and entry["began"] and entry["saved"] and last["began"] and last["saved"] \
                            and entry["began"] - last["saved"] <= pause and entry["saved"] - last["began"] <= span:
                        last.update({key: entry[key] for key in ("snapshot", "data", "content", "created_at", "saved")})
                        last["members"] += entry["members"]
                        totals["merged"] += len(entry["members"])
                    else:
                        kept.append(entry)
                if len(kept) == len(entries):
                    break
                entries = kept
            holder = {revision: index for index, entry in enumerate(kept) for revision in entry["members"]}
            mapping = {old: index + 1 for old, index in holder.items()}
            conn.execute(text("DELETE FROM note_revisions WHERE note_id = :note"), {"note": note_id})
            for number, version in enumerate(kept, 1):
                before = kept[number - 2]["data"] if number > 1 else {}
                added, removed = changes(str(before.get("markdown") or ""), str(version["data"].get("markdown") or ""))
                source = version["restored_from"]
                conn.execute(text(
                    "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_by, restored_from, chars_added, "
                    "chars_removed, title_changed, started_at, created_at) VALUES (:note, :revision, :snapshot, :origin, :by, "
                    ":restored, :added, :removed, :title, :started, :saved)"
                ), {
                    "note": note_id, "revision": number, "origin": version["origin"], "by": version["created_by"],
                    "snapshot": version["snapshot"] if isinstance(version["snapshot"], str) else json.dumps(version["data"], ensure_ascii=False),
                    "restored": mapping.get(source) if isinstance(source, int) else None,
                    "added": added, "removed": removed, "started": version["started_at"], "saved": version["created_at"],
                    "title": number > 1 and before.get("title") != version["data"].get("title"),
                })
            conn.execute(text("UPDATE notes SET revision = :revision WHERE id = :note"), {"revision": len(kept), "note": note_id})
            totals["after"] += len(kept)
            moved = {old: new for old, new in mapping.items() if old != new}
            if moved:
                moves[note_id] = moved

        if moves:
            link = re.compile(r"(#/notes\?note=)([^&\s\"'<>()\[\]\\]+)(&(?:amp;)?revision=)(\d+)")

            def target(note_id: Any, revision: Any) -> int | None:
                if not isinstance(note_id, str) or not isinstance(revision, int) or isinstance(revision, bool):
                    return None
                found = moves.get(note_id, {}).get(revision)
                if found is not None:
                    totals["references"] += 1
                return found

            def fix_text(value: str) -> str:
                if "#/notes?note=" not in value:
                    return value

                def swap(match: Any) -> str:
                    found = target(unquote(match.group(2)), int(match.group(4)))
                    return match.group(0) if found is None else f"{match.group(1)}{match.group(2)}{match.group(3)}{found}"

                return link.sub(swap, value)

            def fix(value: Any) -> Any:
                if isinstance(value, dict):
                    out = {key: fix(item) for key, item in value.items()}
                    if isinstance(out.get("note_id"), str):
                        for key in ("revision", "note_revision"):
                            found = target(out["note_id"], out.get(key))
                            if found is not None:
                                out[key] = found
                    if out.get("kind") == "note":
                        found = target(out.get("id"), out.get("revision"))
                        if found is not None:
                            out["revision"] = found
                    return out
                if isinstance(value, list):
                    return [fix(item) for item in value]
                return fix_text(value) if isinstance(value, str) else value

            skip = {"schema_migrations", "record_references", "record_reference_index"}
            for table, definition in tables.items():
                if table in skip or table.startswith("sqlite_") or "WITHOUT ROWID" in definition.upper():
                    continue
                for column, kind in columns(table).items():
                    if kind and not any(word in kind for word in ("TEXT", "CHAR", "JSON", "CLOB")):
                        continue
                    for rowid, value in conn.execute(text(
                        f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" LIKE :needle'
                    ), {"needle": "%revision%"}).all():
                        if not isinstance(value, str):
                            continue
                        changed = value
                        if value.lstrip()[:1] in ("{", "["):
                            try:
                                data = json.loads(value)
                            except ValueError:
                                changed = fix_text(value)
                            else:
                                fixed = fix(data)
                                if fixed != data:
                                    changed = json.dumps(fixed, ensure_ascii=False)
                        else:
                            changed = fix_text(value)
                        if changed != value:
                            conn.execute(text(f'UPDATE "{table}" SET "{column}" = :value WHERE rowid = :rowid'),
                                         {"value": changed, "rowid": rowid})
        logger.info(
            "note revisions: %(before)d rows -> %(after)d (%(property_only)d property-only removed, %(merged)d merged), "
            "%(references)d references moved", totals,
        )


def _migrate_workflow_revisions() -> None:
    """初始化旧工作流的修订历史，并保持当前投影与最新修订一致。

    新表由前一阶段的 ``create-current-schema`` 建好；这里仅补已有 workflows 表不会被
    ``create_all`` 添加的两列，并为每条老数据写首份快照。摘要算法在迁移内自包含，避免将来
    领域实现变化后重放历史迁移得到不同结果。

    启动迁移没有 alembic 的「只执行一次」账本，因此这里必须真正可重入。已有修订时，当前图
    若等于最新快照，只校正 ``workflows`` 的当前指针；若不等，则把当前图追加成恢复修订，绝不
    覆盖用户数据或旧快照。这个校正也会修复曾被旧版迁移错误重置为 v1 的工作流。
    """

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "workflows" not in tables or "workflow_revisions" not in tables:
        return
    # 完整摘要算法是历史迁移格式，留在本函数内；「哪些字段构成一个版本」则是当前领域规则，
    # 启动自愈必须和保存入口共用同一定义，否则一次纯布局保存会在下次启动时被误升成新版本。
    from app.domain.workflows.revisions import revision_digest

    columns = {column["name"] for column in inspector.get_columns("workflows")}
    with engine.begin() as conn:
        if "revision" not in columns:
            conn.execute(text("ALTER TABLE workflows ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"))
        if "graph_hash" not in columns:
            conn.execute(text("ALTER TABLE workflows ADD COLUMN graph_hash VARCHAR(64) NOT NULL DEFAULT ''"))

        rows = conn.execute(text("SELECT id, graph, revision, graph_hash, created_at FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                graph = {}
            canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            stored_graph = raw_graph if isinstance(raw_graph, str) else json.dumps(graph or {}, ensure_ascii=False)
            latest = conn.execute(
                text(
                    "SELECT revision, graph, graph_hash FROM workflow_revisions "
                    "WHERE workflow_id = :id ORDER BY revision DESC LIMIT 1"
                ),
                {"id": row["id"]},
            ).mappings().one_or_none()

            if latest is None:
                conn.execute(
                    text(
                        """
                        INSERT INTO workflow_revisions
                            (id, workflow_id, revision, graph, graph_hash, source, note, created_by, created_at)
                        VALUES
                            (:id, :workflow_id, 1, :graph, :graph_hash, 'migration', '', NULL, :created_at)
                        """
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "workflow_id": row["id"],
                        "graph": stored_graph,
                        "graph_hash": digest,
                        "created_at": row["created_at"] or datetime.now(UTC).replace(tzinfo=None),
                    },
                )
                current_revision = 1
            else:
                latest_raw_graph = latest["graph"]
                try:
                    latest_graph = json.loads(latest_raw_graph) if isinstance(latest_raw_graph, str) else latest_raw_graph
                except (TypeError, ValueError):
                    latest_graph = {}
                latest_canonical = json.dumps(
                    latest_graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                latest_digest = hashlib.sha256(latest_canonical.encode("utf-8")).hexdigest()

                if latest["graph_hash"] == latest_digest and revision_digest(latest_graph) == revision_digest(graph):
                    # 正常重跑、纯布局保存和旧缺陷的自愈都走这里：图不动，只校正当前指针。
                    current_revision = int(latest["revision"])
                else:
                    # 当前投影没有对应的不可变快照。保住用户眼前的图，并把它提升为最新修订。
                    current_revision = int(latest["revision"]) + 1
                    conn.execute(
                        text(
                            """
                            INSERT INTO workflow_revisions
                                (id, workflow_id, revision, graph, graph_hash, source, note, created_by, created_at)
                            VALUES
                                (:id, :workflow_id, :revision, :graph, :graph_hash,
                                 'migration', 'recovered current projection', NULL, :created_at)
                            """
                        ),
                        {
                            "id": uuid.uuid4().hex,
                            "workflow_id": row["id"],
                            "revision": current_revision,
                            "graph": stored_graph,
                            "graph_hash": digest,
                            "created_at": datetime.now(UTC).replace(tzinfo=None),
                        },
                    )
                    logger.warning("工作流 %s 的当前图没有对应修订，已恢复为 v%d", row["id"], current_revision)

            if row["revision"] != current_revision or row["graph_hash"] != digest:
                conn.execute(
                    text("UPDATE workflows SET revision = :revision, graph_hash = :digest WHERE id = :id"),
                    {"revision": current_revision, "digest": digest, "id": row["id"]},
                )


def _migrate_official_workflow_data_bindings() -> None:
    """Turn exact output references in installed official workflows into native data edges.

    Official templates are editable copies, so regenerating them would erase user changes.  The
    canonicalizer changes only the one representation that is provably equivalent and leaves every
    other node, value and layout coordinate intact.  The following revision migration notices the
    semantic graph change and records it as a new immutable revision.
    """

    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.normalization import canonicalize_data_bindings

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict) or (graph.get("meta") or {}).get("source") != "official":
                continue
            normalized = canonicalize_data_bindings(graph, node_types=NODE_TYPES)
            if normalized == graph:
                continue
            conn.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(normalized, ensure_ascii=False), "id": row["id"]},
            )


def _migrate_node_names_are_not_i18n_keys() -> None:
    """把被当成人话写进图里的 `wfNode_*` 节点名清掉。

    `graph_ops.add_node` 此前在没给名字时回退到 `NODE_TYPES[type]["label"]` —— 而那一格存的是
    **i18n key**(目录里存 key、出口才翻)。于是智能体建的节点在画布上从此叫
    `wfNode_scene_render`,而且**随图落库**:这是写进用户数据的错,不只是显示错。

    清成空串就够了:没有名字时显示会回退到**翻译后**的 label,而那正是用户想看到的 ——
    所以这次迁移不是"补一个值",是"把一个不该存在的值拿掉"。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        cleared = 0
        for row in rows:
            raw = row["graph"]
            try:
                graph = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            touched = False
            for node in graph.get("nodes") or []:
                if isinstance(node, dict) and str(node.get("name") or "").startswith("wfNode_"):
                    node["name"] = ""
                    touched = True
            if not touched:
                continue
            conn.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(graph, ensure_ascii=False), "id": row["id"]},
            )
            cleared += 1
        if cleared:
            logger.info("清掉了 %d 个工作流里被写成 i18n key 的节点名", cleared)


def _migrate_called_workflows_declare_their_output() -> None:
    """被别的工作流 `call_workflow` 调用、却没有「输出」节点的图,补上一个输出节点。

    ## 为什么要迁移,而不是留一条兼容分支

    `call_workflow` 此前的返回是

        result.get("output") or result.get("context") or {}

    —— 被调图没有输出节点时,退回**整份上下文**。那份上下文是给人看的快照,过了 `_trim_outputs`
    (长字符串截断、列表只留 200 项、对象只留 100 个字段),于是一份长文案、一段 LLM 回答、
    一串 id 列表经这条退路传上去会**安静地少一截**。而「输出」节点的说明写着:被调用时调用方拿的
    就是这个契约 —— 一个契约不能有"契约给不出东西时换一种形状"的退路。

    这条退路是明写的向后兼容分支,而本仓库的规矩是**不写兼容,改形状带迁移**(ADR-0006)。
    所以退路删掉,老数据在这里补齐:给每个终端节点(没有出边的那些)的每一个输出声明一个名字,
    形如 `{节点id}_{输出名}: "{{节点id.输出名}}"`。**这正是老行为的显式版本** —— 暴露的还是
    那些值,只是从此有名有姓、而且不再被裁剪。

    只改 `workflows.graph`(当前图)。修订是不可变快照,不动它们:拿老修订跑的任务会拿到
    `wfErr_calledWorkflowHasNoOutput` 那句明确的话(「加一个输出节点」),而不是一份少了一截
    的数据 —— **说得出口的失败比悄悄错掉好**。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import NODE_TYPES

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        graphs: dict[str, dict] = {}
        called: set[str] = set()
        for row in rows:
            raw = row["graph"]
            try:
                graph = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            graphs[row["id"]] = graph
            for node in graph.get("nodes") or []:
                if isinstance(node, dict) and node.get("type") == "call_workflow":
                    target = (node.get("config") or {}).get("workflow_id")
                    if isinstance(target, str) and target:
                        called.add(target)

        patched = 0
        for workflow_id in sorted(called):
            graph = graphs.get(workflow_id)
            if graph is None:
                continue
            nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
            if any(node.get("type") == "output" for node in nodes):
                continue
            sources = {
                str(edge.get("source"))
                for edge in (graph.get("edges") or [])
                if isinstance(edge, dict)
            }
            values: dict[str, str] = {}
            for node in nodes:
                nid = str(node.get("id") or "")
                if not nid or nid in sources:
                    continue  # 有出边的不是终端节点
                spec = NODE_TYPES.get(str(node.get("type")))
                for out in (spec or {}).get("outputs") or []:
                    if str(out).startswith("*"):
                        continue  # 运行时才知道名字的,声明不出来
                    values[f"{nid}_{out}"] = f"{{{{{nid}.{out}}}}}"
            if not values:
                continue
            graph["nodes"] = [*nodes, {
                "id": "output_migrated",
                "type": "output",
                "name": "输出",
                "config": {"values": values},
            }]
            graph["edges"] = [*(graph.get("edges") or []), *(
                {"source": nid, "target": "output_migrated"}
                for nid in sorted({key.rsplit("_", 1)[0] for key in values})
                if any(node.get("id") == nid for node in nodes)
            )]
            conn.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(graph, ensure_ascii=False), "id": workflow_id},
            )
            patched += 1
        if patched:
            logger.info("给 %d 个被调用的工作流补上了「输出」节点", patched)


def _migrate_resource_ownership() -> None:
    """五张表补 `owner_user_id`,并给每条已存在的记录建一行「共享给它当前所在的工作区」。

    **升级前后行为完全一致**:今天同工作区的人看得见的,升级之后仍然看得见;而**从此以后新建的
    默认私有**(见 domain/sharing.KINDS)。不这么做的话,升级会把同事的发布账号、浏览器档案、
    对话从他们眼前一次性拿走 —— 那不是收紧权限,那是弄坏了正在用的东西。

    归属回填成**该工作区的 owner**:老数据里没有记谁建的,而工作区的 owner 是现在对它们负责的人。

    ## 共享回填**只能跑一次**,不是「幂等」

    这两件事听起来像一回事,其实相反。共享是**用户随时在改的状态**:第一次跑到这里时「某条记录
    没有共享行」意味着它是拆分之前的老数据、要一次性迁过来;而从此以后,「没有共享行」意味着
    **主人把它收回了**。原先每次启动都补上缺的那些,于是:

      ・新建的账号本该默认私有(domain/sharing.KINDS 明写 False),下次启动就被改成了团队共享;
      ・在界面上点「收回」确实删掉了那一行,重启之后它又回来了 —— 表现为「收回无效」。

    两个症状同一个根因。判据取**这一轮是否真的新加了 `owner_user_id` 列**:加列的那一次就是这台
    机器第一次跑到归属拆分,老数据只在那一刻迁移。全新安装由 create_all 直接建出带列的表,永远
    不走这条路,所以新库里的默认私有是真的默认私有。

    归属回填(owner_user_id)则**照旧每次都跑**:它不是用户可改的状态,是派生值,而 owner 为空的
    记录连主人自己都看不见 —— 那种行该修就修,且修它不会把任何东西暴露给别人。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    kinds = {
        "publish_account": "publish_accounts",
        "browser_profile": "browser_profiles",
        "agent_session": "agent_sessions",
        "generation_session": "generation_sessions",
        "scheduled_task": "scheduled_tasks",
    }
    # 这一轮真正新加了列的表 —— 只有它们的老数据需要一次性迁移共享。
    upgraded: set[str] = set()
    for table in kinds.values():
        if table not in tables:
            continue
        if "owner_user_id" not in {c["name"] for c in inspector.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN owner_user_id VARCHAR(64)"))
            upgraded.add(table)
    if "resource_shares" not in set(inspect(engine).get_table_names()):
        return  # create_all 还没跑到(首次装机),下次启动再补
    with engine.begin() as conn:
        for kind, table in kinds.items():
            if table not in tables:
                continue
            conn.execute(
                text(
                    f"UPDATE {table} SET owner_user_id = ("
                    "SELECT user_id FROM workspace_members "
                    f"WHERE workspace_members.workspace_id = {table}.workspace_id AND role = 'owner' "
                    "LIMIT 1) WHERE owner_user_id IS NULL"
                )
            )
            if table not in upgraded:
                continue  # 列早就在了 = 老数据当年已经迁完;此后的「没有共享行」是主人收回了
            conn.execute(
                text(
                    "INSERT INTO resource_shares (id, kind, resource_id, workspace_id, shared_by, created_at) "
                    f"SELECT lower(hex(randomblob(16))), :kind, {table}.id, {table}.workspace_id, "
                    f"COALESCE({table}.owner_user_id, ''), CURRENT_TIMESTAMP FROM {table} "
                    "WHERE NOT EXISTS (SELECT 1 FROM resource_shares s "
                    f"WHERE s.kind = :kind AND s.resource_id = {table}.id "
                    f"AND s.workspace_id = {table}.workspace_id)"
                ),
                {"kind": kind},
            )


def _migrate_publish_task_options() -> None:
    """publish_tasks 新增 options 列(平台自己的发布选项:可见性、允许评论…)。

    create_all 只建新表,不给已有表补列。老任务留空字典 —— 执行器把「没有这个键」当成用默认值,
    而默认值一律是最保守的那档(可见性 = 私享 / 仅自己可见),所以老数据不会因为升级而突然公开。
    """
    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    if "options" in {c["name"] for c in inspector.get_columns("publish_tasks")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN options JSON NOT NULL DEFAULT '{}'"))


def backfill_dub_tracks() -> None:
    """把**已经存在的**配音轨标出来。

    这个功能上线时已经有人配过音了;不认它们的话,下一次配音会在旁边再建一条,而用户看到的是
    「说好的复用呢」。

    判据是事实,不是猜:一条音频轨上的片段**全部**来自 TTS 产物(asset.source='tts'),且至少
    有一段。BGM / 录音 / 原声轨不会满足;**空轨也不会** —— 空轨恰恰是失败的配音留下的残骸,
    把它认成配音轨等于把垃圾扶正。
    """
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE tracks SET role = 'dub'
            WHERE kind = 'audio'
              AND role = ''
              AND EXISTS (SELECT 1 FROM clips WHERE clips.track_id = tracks.id)
              AND NOT EXISTS (
                    SELECT 1 FROM clips
                    LEFT JOIN assets ON assets.id = clips.asset_id
                    WHERE clips.track_id = tracks.id
                      AND (assets.source IS NULL OR assets.source <> 'tts')
              )
        """))


def _migrate_track_role() -> None:
    """给轨道补 `role` 列。

    配音要能回到**同一条**配音轨上,而不是每配一次多一条空轨。认哪条轨不能靠名字 —— 名字是
    给人看的,用户随时会改成「旁白」「解说」。
    """
    inspector = inspect(engine)
    if "tracks" not in set(inspector.get_table_names()):
        return
    if "role" in {c["name"] for c in inspector.get_columns("tracks")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tracks ADD COLUMN role VARCHAR(24) NOT NULL DEFAULT ''"))
    backfill_dub_tracks()


def _migrate_subtitle_tracks_carry_no_sound() -> None:
    """字幕轨上的独奏 / 闪避标记清掉 —— 字幕轨没有声音,这两个开关在它身上不再存在。

    此前轨道头给字幕轨也摆了独奏按钮。按下去的后果是反的:「有轨在独奏」成立,而字幕轨没有声音,
    于是预览和成片里**所有**声音都被关掉。现在 set_track_state 拒绝给字幕轨设这两个标记,老库里
    已经按下去的那些在这里放回去 —— 结果就是用户本来想要的「什么都没独奏」。
    """
    inspector = inspect(engine)
    if "tracks" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("tracks")}
    if not {"solo", "duck"} <= columns:
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE tracks SET solo = 0, duck = 0 WHERE kind = 'subtitle' AND (solo = 1 OR duck = 1)"))


def _migrate_subtitle_tracks_hide_instead_of_mute() -> None:
    """轨道补 `hidden` 列,字幕轨上的「静音」搬成「隐藏」。

    此前轨道只有一个 `muted`,两个意思:字幕轨借它表示「不显示这条字幕」,视频轨上它除了关声音还顺带
    把花字藏掉 —— 而轨道头上画的是喇叭。现在 `muted` 只管声音,`hidden` 只管字幕显示,字幕轨不再收
    `muted`(set_track_state 拒绝),所以已有的字幕轨静音在这里改记成隐藏,用户看到的效果不变。

    操作日志里记下的轨道状态一起改写(`set_track_state` 的前后两份、`remove_track` 的那一份):不改的话,
    撤销一次老的「字幕轨静音」写回的是一个已经不起作用的字段,而撤销以为自己做完了。改写后每份状态都
    带着 `hidden`,撤销直接读它。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "tracks" not in tables:
        return
    columns = {c["name"] for c in inspector.get_columns("tracks")}
    with engine.begin() as conn:
        if "hidden" not in columns:
            conn.execute(text("ALTER TABLE tracks ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT 0"))
        conn.execute(text("UPDATE tracks SET hidden = 1, muted = 0 WHERE kind = 'subtitle' AND muted = 1"))
        if "sequence_operations" not in tables:
            return
        rows = conn.execute(
            text("SELECT id, kind, payload FROM sequence_operations WHERE kind IN ('set_track_state', 'remove_track')")
        ).all()
        payloads = {row[0]: (row[1], json.loads(row[2]) if isinstance(row[2], str) else dict(row[2] or {})) for row in rows}
        # 被删掉的轨不在 tracks 表里了,它是不是字幕轨只有 remove_track 那份记录知道。
        subtitle_ids = {row[0] for row in conn.execute(text("SELECT id FROM tracks WHERE kind = 'subtitle'"))}
        subtitle_ids |= {
            payload.get("track_id") for kind, payload in payloads.values()
            if kind == "remove_track" and payload.get("kind") == "subtitle"
        }
        for op_id, (kind, payload) in payloads.items():
            if "hidden" in payload:
                continue  # 已经是新形状(重跑,或本版本写下的)
            subtitle = payload.get("track_id") in subtitle_ids
            states = [payload]
            if kind == "set_track_state" and isinstance(payload.get("previous"), dict):
                states.append(payload["previous"])
            for state in states:
                state["hidden"] = bool(state.get("muted")) if subtitle else False
                if subtitle:
                    state["muted"] = False
            conn.execute(
                text("UPDATE sequence_operations SET payload = :payload WHERE id = :id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "id": op_id},
            )


def _migrate_generation_capability_profiles() -> None:
    """建生成参数模板与逐模型、逐 kind 的声明表。

    `_create_current_schema` 会为全新库建好它;这一步是给**已有库**补上的。建表语句从模型本身
    取(`checkfirst=True`),不手写一遍 DDL —— 手写的那份迟早和模型分岔,而分岔的症状是某一列
    在老库上不存在,只有升级过来的人撞得到。
    """
    from app.db.models import GenerationCapabilityDeclaration, GenerationCapabilityProfile

    GenerationCapabilityProfile.__table__.create(bind=engine, checkfirst=True)
    GenerationCapabilityDeclaration.__table__.create(bind=engine, checkfirst=True)


def _migrate_prompt_requirement_becomes_one_field() -> None:
    """用户写下的参数组里,「提示词要不要写」从两个布尔收成一格 `prompt`(见 catalog.PROMPT_MODES)。

    此前是 `requires_prompt`(必须写)和 `prompt_optional`(可以不写)两个布尔,而且只对音频生效;现在
    是一格三值 `required` / `optional` / `none`,各种生成共用。参数组是用户手填的描述符,校验按白名单
    (见 custom_profiles._KNOWN_KEYS),不搬的话老键会让这份参数组**再也存不回去**。

    - `prompt_optional: true` → `prompt: "optional"`;
    - `requires_prompt: true` → 不写(`required` 就是没写时的意思);
    - 两个布尔一律删掉。已经有 `prompt` 的不覆盖。

    幂等:第二次跑时已经没有这两个键。
    """
    if "generation_capability_profiles" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, capabilities FROM generation_capability_profiles")).mappings().all():
            raw = row["capabilities"]
            try:
                capabilities = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if not isinstance(capabilities, dict) or not {"requires_prompt", "prompt_optional"} & set(capabilities):
                continue
            capabilities.pop("requires_prompt", None)
            if capabilities.pop("prompt_optional", None) is True:
                capabilities.setdefault("prompt", "optional")
            conn.execute(
                text("UPDATE generation_capability_profiles SET capabilities = :c WHERE id = :id"),
                {"c": json.dumps(capabilities, ensure_ascii=False), "id": row["id"]},
            )


def _migrate_provider_model_capability_ref() -> None:
    """给模型行补 `generation_capability_ref` 列。

    生成参数此前只能来自静态目录,而目录按 (provider, model, kind) 精确查 —— 用户手填的别名
    (`gpt-image-2-client`)、经另一条中转配的同一个模型,一律查不到,界面上一个参数都没有。
    这一列是用户写下"只有他知道的事"的地方。**回填不做任何猜测**:老行一律留空 = 跟随目录,
    和它现在的行为一模一样。
    """
    inspector = inspect(engine)
    if "provider_models" not in set(inspector.get_table_names()):
        return
    if "generation_capability_ref" in {c["name"] for c in inspector.get_columns("provider_models")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_models ADD COLUMN generation_capability_ref VARCHAR(200)"))


def _migrate_prepared_publish_tasks() -> None:
    """把老的 `prepared` 发布任务迁成 `cancelled`。

    `prepared`(表单填好、等人确认)只由 dry_run 那条路产生,而 dry_run 从来没有任何办法被触发
    ——后端的认领载荷把它写死成 False。整条路已删,`prepared` 随之退出状态枚举。

    库里可能还留着这个状态的行(本机就有两条)。留着它们等于留下一个**没人认得的状态**:
    界面查不到对应文案、任务总线的终态集合也不含它,于是那些行会永远显示成中间态。
    迁成 cancelled 是诚实的:它们当年停在"等人确认"那一步,而现在没有任何东西会再推它们一把。
    """
    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE publish_tasks SET status = 'cancelled' WHERE status = 'prepared'"))


def _migrate_job_message_i18n() -> None:
    """jobs 新增 message_key / message_params / error_key / error_params(任务文案的多语言)。

    老行留空 —— 它们只留下了当年渲染的那句话,反推不出 key。接口见到空 key 就原样返回 message,
    所以历史任务显示成写入时的语言;**新任务从此跟着请求语言走**。这是数据本身的界限,不是兼容分支。
    """
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        if "message_key" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN message_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "message_params" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN message_params JSON NOT NULL DEFAULT '{}'"))
        #: 失败原因同一对。老行同样留空 —— 反推不出 key,接口见到空 key 就原样返回那句话。
        if "error_key" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN error_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "error_params" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN error_params JSON NOT NULL DEFAULT '{}'"))


def _drop_member_perm_overrides() -> None:
    """删掉 workspace_member_perms 整张表(ADR 0008 D4:角色即权限)。

    权限位矩阵退场之后这张表没有读它的代码了 —— 留着一张没人读的表,下一个人会以为它还在起作用,
    而它记录的恰恰是"某人被单独关掉了某项能力"这种最容易被误读的信息。

    删表是不可逆的,但这里可逆的那一半在别处:真需要逐位配置时重新加回来,那时会有真实用例说清楚
    要哪几位 —— 而不是把一张旧形状的表当成需求。
    """
    inspector = inspect(engine)
    if "workspace_member_perms" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE workspace_member_perms"))


def _migrate_deployment_admin() -> None:
    """users 新增 is_deployment_admin,并把**最早创建的账号**提成部署管理员。

    此前「谁对这个部署负责」没有对应物,只能用「在任意工作区里是 admin」去近似 —— 而工作区可以
    自助新建,所以那个近似是自助的。这次把它变成数据。

    回填选最早的账号:单机安装里那就是本人;团队安装里那是当初装起这台后端的人 —— 两种情况下
    都是对的那个人,而且与 `_adopt_orphan_workspaces`(第一个账号继承登录前建的工作区)同一条理由。
    幂等:已经有人持有就不再动(管理员可能已经把它转给了别人)。
    """
    inspector = inspect(engine)
    if "users" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        if "is_deployment_admin" not in {c["name"] for c in inspector.get_columns("users")}:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_deployment_admin BOOLEAN NOT NULL DEFAULT 0")
            )
        already = conn.execute(text("SELECT COUNT(*) FROM users WHERE is_deployment_admin = 1")).scalar()
        if already:
            return
        conn.execute(
            text(
                "UPDATE users SET is_deployment_admin = 1 WHERE id = ("
                "SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1)"
            )
        )


def _migrate_permission_modes() -> None:
    """三档权限模式的两组列(agent_sessions 的模式、tool_confirmations 的留痕)。

    老行取默认值就是正确语义:模式 manual(与此前行为一致)、白名单空、历史卡记为 manual —— 它们
    确实都是人点的,那时还没有自动放行。读取代码里因此不留"有没有这些列"的分支(docs/adr/0006)。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "agent_sessions": [
            ("permission_mode", "ALTER TABLE agent_sessions ADD COLUMN permission_mode VARCHAR(16) NOT NULL DEFAULT 'manual'"),
            ("mode_set_by", "ALTER TABLE agent_sessions ADD COLUMN mode_set_by VARCHAR(64)"),
            ("mode_set_at", "ALTER TABLE agent_sessions ADD COLUMN mode_set_at DATETIME"),
            ("auto_allow_tools", "ALTER TABLE agent_sessions ADD COLUMN auto_allow_tools JSON NOT NULL DEFAULT '[]'"),
        ],
        "tool_confirmations": [
            ("decision_mode", "ALTER TABLE tool_confirmations ADD COLUMN decision_mode VARCHAR(16) NOT NULL DEFAULT 'manual'"),
            ("decided_by", "ALTER TABLE tool_confirmations ADD COLUMN decided_by VARCHAR(64)"),
            ("decision_detail", "ALTER TABLE tool_confirmations ADD COLUMN decision_detail JSON"),
            ("hold_until", "ALTER TABLE tool_confirmations ADD COLUMN hold_until DATETIME"),
        ],
        "workspaces": [
            ("autopilot_rules", "ALTER TABLE workspaces ADD COLUMN autopilot_rules JSON NOT NULL DEFAULT '{}'"),
        ],
    }
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        missing = [sql for name, sql in columns if name not in existing]
        if not missing:
            continue
        with engine.begin() as conn:
            for sql in missing:
                conn.execute(text(sql))


def _migrate_auth_session_expiry() -> None:
    """auth_sessions 新增 kind / expires_at 两列 —— 这张表此前没有过期概念。

    老行分不出哪些是真正的登录、哪些是泄漏的服务令牌(工具通道每次调用留一行,OAuth 刷新、
    查额度、订阅登录也各留一行),所以一律按登录处理,给一个完整周期:**升级不该把任何人踢
    出去**。它们最迟一个周期后自然消失,而增长从这次起就停了。

    `expires_at` 在模型上是 NOT NULL,但这里补列时必须允许为空 —— SQLite 给已有行加 NOT NULL
    列要求常量默认值,而"当前时间 + 周期"不是常量。所以先加列、再回填,回填之后不会再有空值。
    """
    inspector = inspect(engine)
    if "auth_sessions" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("auth_sessions")}
    with engine.begin() as conn:
        if "kind" not in columns:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'login'"))
        if "expires_at" not in columns:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN expires_at DATETIME"))
        # 确认卡的会话归属(§ docs/AGENT_PERMISSION_MODES.md 4.5)。老令牌留空 —— 它们要么是登录
        # 令牌本来就没有会话,要么是上一版铸出来的 turn 令牌,而那些 turn 早就结束了。
        if "agent_session_id" not in columns:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN agent_session_id VARCHAR(64)"))
        # 幂等:只填空值。跑第二次时上面两个分支都不进,这句也改不动任何行。
        horizon = (datetime.now(UTC).replace(tzinfo=None) + LOGIN_SESSION_TTL).isoformat(
            sep=" ", timespec="seconds"
        )
        conn.execute(text("UPDATE auth_sessions SET expires_at = :h WHERE expires_at IS NULL"), {"h": horizon})


def _migrate_tts_pip_index() -> None:
    """tts_config 新增 pip_index 列(装引擎依赖时用的 pip 镜像)。

    create_all 只建新表,不给**已有**表补列——已装机的 tts_config 表没有这列,
    读配置时会直接 OperationalError。加列即可,老行取默认空串(= 官方 PyPI)。
    """
    inspector = inspect(engine)
    if "tts_config" not in set(inspector.get_table_names()):
        return
    if "pip_index" in {c["name"] for c in inspector.get_columns("tts_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tts_config ADD COLUMN pip_index VARCHAR(200) NOT NULL DEFAULT ''"))


def _migrate_provider_capabilities() -> None:
    """加列迁移:provider_profiles 增加 capability_ids(档案级能力覆盖,None=沿用 vendor 默认)。"""
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    if "capability_ids" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE provider_profiles ADD COLUMN capability_ids JSON"))


def _drop_shared_credentials() -> None:
    """去掉 `provider_credentials.shared`。

    这个位是为了让第 4 步的升级无缝而加的:老库里那把大家共用的钥匙,迁移后仍然大家能用。
    但它**没有任何界面**(等于一个只有迁移能置位的隐藏状态),而且和这张表存在的理由自相矛盾 ——
    钥匙归人,正是为了不再「所有人共用一把、花的是同一个人的钱」。

    已经存在的行不动:它们仍然属于那位部署管理员,只是不再对别人生效。
    """
    inspector = inspect(engine)
    if "provider_credentials" not in set(inspector.get_table_names()):
        return
    if "shared" not in {c["name"] for c in inspector.get_columns("provider_credentials")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_credentials DROP COLUMN shared"))


def _migrate_encrypt_secrets() -> None:
    """把老库里明文躺着的密钥就地加密(见 core/secrets_at_rest)。

    哪些列装秘密登记在 `ENCRYPTED_COLUMNS` 一处;这里按那份清单逐列扫。**只在迁移里判断
    "这串是不是已经加密过的"** —— 运行时不做这种判断,那会变成读取期的两路兼容(ADR 0006)。

    幂等:已经是密文的跳过。解不开的也跳过(不是本部署的密钥,再加一层只会更糟)。
    """
    from app.core.secrets_at_rest import ENCRYPTED_COLUMNS, encrypt, looks_encrypted

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table, column in sorted(ENCRYPTED_COLUMNS):
        if table not in tables:
            continue
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            continue
        with engine.begin() as conn:
            # 主键列名各表不同,用 rowid —— SQLite 每张普通表都有。
            rows = conn.execute(
                text(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''")
            ).all()
            for rowid, value in rows:
                raw = str(value)
                if looks_encrypted(raw):
                    continue
                conn.execute(
                    text(f"UPDATE {table} SET {column} = :v WHERE rowid = :r"),
                    {"v": encrypt(raw), "r": rowid},
                )


def _migrate_provider_defaults_per_person() -> None:
    """`provider_defaults` 从「一项能力一行」变成「一个人一项能力一行」。

    老库里那一行是**整个部署共用的默认**,没有主人。它曾被搬成 `owner_user_id = ''`(那时还有
    "部署默认"这一档),而那一档已经删掉了 —— 所以这里**不搬**:一行没有主人的默认,找不到
    任何一个人可以诚实地记在他名下。搬给所有人等于替每个人做了一次他没做过的选择,正是删掉
    这一档要避免的事。升级后每个人第一次用时自己选一个(见 domain/providers/defaults.get_row)。

    SQLite 改不了主键,所以按重建表的老办法:建新表 → 换名。
    """
    inspector = inspect(engine)
    if "provider_defaults" not in set(inspector.get_table_names()):
        return
    if "owner_user_id" in {c["name"] for c in inspector.get_columns("provider_defaults")}:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE provider_defaults_new ("
                "capability VARCHAR(24) NOT NULL, owner_user_id VARCHAR(64) NOT NULL DEFAULT '', "
                "provider_profile_id VARCHAR(64), model VARCHAR(120) NOT NULL DEFAULT '', "
                "provider_model_id VARCHAR(64), updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (capability, owner_user_id))"
            )
        )
        conn.execute(text("DROP TABLE provider_defaults"))
        conn.execute(text("ALTER TABLE provider_defaults_new RENAME TO provider_defaults"))


def _migrate_capability_defaults_name_builtins() -> None:
    """能力的默认可以是一个内置实现(ADR 0032 §1):`plugin_capability_defaults` 加 `builtin_id`,`instance_id` 改成可空。

    降噪有三个本机引擎,点名自动用的那个之外的(RNNoise)是一次真的选择,此前只能存插件连接 id,选了报「没有这个连接」。
    老行都是插件连接,原样搬;指向已删连接的悬空行不搬(本来就不作数)。SQLite 改不了列的可空性,所以按重建表的老办法:建新表 → 搬行 → 换名。
    """
    inspector = inspect(engine)
    if "plugin_capability_defaults" not in set(inspector.get_table_names()):
        return
    if "builtin_id" in {c["name"] for c in inspector.get_columns("plugin_capability_defaults")}:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE plugin_capability_defaults_new ("
                "owner_user_id VARCHAR(64) NOT NULL, capability VARCHAR(40) NOT NULL, "
                "instance_id VARCHAR(64) REFERENCES plugin_instances (id) ON DELETE CASCADE, "
                "builtin_id VARCHAR(80), updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (owner_user_id, capability), "
                "CONSTRAINT ck_capability_default_one_provider CHECK ((instance_id IS NULL) != (builtin_id IS NULL)))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO plugin_capability_defaults_new (owner_user_id, capability, instance_id, builtin_id, updated_at) "
                "SELECT owner_user_id, capability, instance_id, NULL, updated_at FROM plugin_capability_defaults "
                "WHERE instance_id IN (SELECT id FROM plugin_instances)"
            )
        )
        conn.execute(text("DROP TABLE plugin_capability_defaults"))
        conn.execute(text("ALTER TABLE plugin_capability_defaults_new RENAME TO plugin_capability_defaults"))


def _migrate_hash_session_tokens() -> None:
    """把老库里明文存着的会话令牌就地换成哈希。

    令牌就是这个人本人 —— 一次库泄露(或一份被拷走的数据目录)里,所有还没过期的令牌都能直接
    拿去用,受害者这边不会有任何痕迹。密码早就只存哈希了,令牌此前不是。

    **人不掉线**:他手上那串没变,校验时再哈希一次就对得上。

    判据是前缀 `sha256:`,不是长度 —— 原始令牌本身就是 64 位十六进制(token_hex(32)),和裸哈希
    长得一模一样。迁移每次启动都会跑,认错一次就是把所有人哈希两遍、全部掉线。
    """
    if "auth_sessions" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT token FROM auth_sessions")).fetchall()
        for (stored,) in rows:
            if str(stored).startswith(f"{TOKEN_SCHEME}:"):
                continue
            conn.execute(
                text("UPDATE auth_sessions SET token = :hashed WHERE token = :raw"),
                {"hashed": token_digest(str(stored)), "raw": stored},
            )


def _migrate_connections_get_an_owner() -> None:
    """给每条供应商连接补上主人。

    老库里连接是部署级的、没有主人。**归给这台部署的管理员** —— 因为建连接一直需要部署管理员
    权限,所以现存的每一条都是某个管理员建的。多个管理员时取最早那个:库里没记 creator,而"最早
    的那个管理员"是唯一还能猜的答案,猜错的代价也只是他要把连接让给同事(而不是谁的钥匙串了)。

    钥匙本来就是按人的,所以这一步不会让任何人拿到别人的钥匙:连接归了 A,B 在那条连接上的钥匙
    行还在,只是 B 从此看不到那条连接 —— 这正是要的效果(见 tests/test_connections_belong_to_a_person)。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("provider_profiles")}
    with engine.begin() as conn:
        if "owner_user_id" not in columns:
            conn.execute(
                text("ALTER TABLE provider_profiles ADD COLUMN owner_user_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        admin = conn.execute(
            text("SELECT id FROM users WHERE is_deployment_admin = 1 ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin:
            conn.execute(
                text("UPDATE provider_profiles SET owner_user_id = :uid WHERE owner_user_id = ''"),
                {"uid": admin},
            )


def _migrate_drop_the_knowledge_base() -> None:
    """删掉知识库留下的表和向量库文件。

    功能整块删了(见 tests/test_the_knowledge_base_is_gone)。**表不留**:一张没人读的表不是
    "以后可能有用",是下一个人打开数据库时的一个问号 —— 而它还带着用户以为自己存好了的文档。

    向量库是数据目录下的单文件(milvus-lite),一并删掉;删不掉只记日志,它不该挡住启动。
    """
    names = ("kb_chunks_fts", "kb_chunks", "kb_documents", "kb_datasets", "kb_embedding_config")
    existing = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for name in names:
            if name in existing or name.endswith("_fts"):
                conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
    # **milvus-lite 建的是目录,不是文件** —— 名字叫 kb_vectors.db 很容易看成单文件,而
    # `unlink()` 对目录抛 IsADirectoryError(OSError 的子类),正好被这里的 except 吃掉:
    # 表删干净了、目录原封不动留着。拿真实数据目录验过才发现。
    import shutil

    stale = settings.data_dir / "kb_vectors.db"
    try:
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)
    except OSError:
        logger.warning("删不掉遗留的向量库:%s", stale)


def _migrate_plugin_instances_get_an_owner() -> None:
    """给每个插件接入补上主人 —— 和连接那条同一个道理(见 _migrate_connections_get_an_owner)。

    老库里接入是部署级的,建它一直需要部署管理员权限,所以现存的每一个都是某个管理员配的。
    多个管理员时取最早那个。
    """
    inspector = inspect(engine)
    if "plugin_instances" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("plugin_instances")}
    with engine.begin() as conn:
        if "owner_user_id" not in columns:
            conn.execute(
                text("ALTER TABLE plugin_instances ADD COLUMN owner_user_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        admin = conn.execute(
            text("SELECT id FROM users WHERE is_deployment_admin = 1 ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin:
            conn.execute(
                text("UPDATE plugin_instances SET owner_user_id = :uid WHERE owner_user_id = ''"),
                {"uid": admin},
            )


def _migrate_drop_deployment_defaults() -> None:
    """删掉「部署默认模型」那些行 —— 这一档不存在了。

    它看起来温和:只在你没设过时生效。但造成的正是这个应用里反复出现的那种误解 —— 界面上你
    没选过任何模型,回答却来自某个你不知道的模型,花的是你的额度、用的是你的钥匙,而你从没
    同意过。**替人做的选择必须是他自己做的。**

    **不把它下发给每个人**:那样所有人都会"已经有一个默认",而那个默认仍然不是他选的 ——
    只是把同一个问题从一处挪到了每一处。删掉之后他会看到"还没选好模型,去选一个",这句话
    他看得懂,而且知道下一步做什么。

    针对的是已经做过按人拆分那一步的库(比如已经在跑的部署);更老的库在上一个迁移里就不搬了。
    """
    inspector = inspect(engine)
    if "provider_defaults" not in set(inspector.get_table_names()):
        return
    if "owner_user_id" not in {c["name"] for c in inspector.get_columns("provider_defaults")}:
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM provider_defaults WHERE owner_user_id = ''"))


def _migrate_deployment_config() -> None:
    """建部署配置行,并用**环境变量播一次种**。

    老部署可能显式设过 `MOSAEL_OPEN_REGISTRATION=0`,那是它的选择,不该在升级时被默认值
    冲掉。播种只发生一次:库里有行之后环境变量再变也不影响 —— 唯一真相是库。
    """
    import os

    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return  # create_all 还没跑到(首次装机),下次启动再补
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM deployment_config WHERE id = 'default'")).scalar()
        if exists:
            return
        raw = (os.environ.get("MOSAEL_OPEN_REGISTRATION") or "").strip().lower()
        seeded = 0 if raw in ("0", "false", "no", "off") else 1
        conn.execute(
            text(
                "INSERT INTO deployment_config (id, open_registration, updated_at) "
                "VALUES ('default', :open, :now)"
            ),
            {"open": seeded, "now": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")},
        )


def _migrate_client_version() -> None:
    """`auth_sessions` 补 `client_version` / `last_seen_at`:这个人跑的是哪一版、还在不在用。"""
    inspector = inspect(engine)
    if "auth_sessions" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(auth_sessions)"))}
        if "client_version" not in existing:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN client_version VARCHAR(32) NOT NULL DEFAULT ''"))
        if "last_seen_at" not in existing:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN last_seen_at DATETIME"))


def _drop_reviews_table() -> None:
    """删掉 `reviews` —— 一个**完整的后端功能,而界面上零入口**。

    表、领域、路由、测试都在,而前端、i18n、MCP 工具、智能体工具**没有任何一处**碰过它:
    `listReviews` / `requestReview` / `decideReview` 三个客户端函数全仓零调用。
    它是由 `test_api_fields_reach_the_screen`(ReviewOut 的六个字段没人读)顺出来的。

    留着的代价和 `linked_clip_id` 一样:下一个人读到它会以为评审已经做好,去查"为什么点不到"。
    2026-09-23 与用户确认后整条删;真要做评审时按那时的需求重新建模,而不是继承一份没人用过
    的形状。活动流里已有的 `review.requested` / `review.decided` 记录**原样留着** ——
    那是发生过的事,不因为功能没了就抹掉。
    """
    inspector = inspect(engine)
    if "reviews" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE reviews"))


def _migrate_browser_action_leases() -> None:
    """`browser_actions` 补 ADR-0002 的租约三件套(lease_worker / lease_token / lease_expires_at)。

    这条通道此前一条都没落:认领不记谁领的、回报不校验令牌、心跳只说"我还在"。单执行器下
    工作正常,而多执行器或执行器崩溃时没有任何东西保证正确 —— 隔壁两条通道都有。

    老行(升级那一刻还停在 queued/running 的)**直接判失败**:它们是上一个进程留下的,
    执行器视图早随那个进程消失了,留着只会让调用方一直等到超时。不给它们补一个空租约 ——
    那等于在读路径上留一条"租约为空怎么办"的永久分支(见 jobs.expire_worker_leases 里记的
    那次教训)。
    """
    inspector = inspect(engine)
    if "browser_actions" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(browser_actions)"))}
        for name, ddl in (
            ("lease_worker", "VARCHAR(64)"),
            ("lease_token", "VARCHAR(64)"),
            ("lease_expires_at", "DATETIME"),
        ):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE browser_actions ADD COLUMN {name} {ddl}"))
        conn.execute(
            text(
                "UPDATE browser_actions SET status = 'failed', error = '后端升级导致中断' "
                "WHERE status IN ('queued', 'running')"
            )
        )


def _drop_clip_linked_clip_id() -> None:
    """`clips` 去掉 `linked_clip_id` —— 这一列在**每一台机器上都是 null**。

    它本来要装的是"分离音频之后两段是链接的"(拖一个另一个跟着走、删一个另一个一起删),
    数据形状、接口出参、前端生成类型、撤销还原清单五处都为它让了路 —— 而
    `detach_clip_audio` 那个本该建立配对的操作从头到尾没设过它,全仓零赋值。

    这比没有这个字段更贵:下一个人读到它会以为链接已经实现,去查"为什么没生效",
    而真相是从来没人写过它。功能要做的时候按真实需求重新建模,不留这个空承诺。
    """
    inspector = inspect(engine)
    if "clips" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}
        if "linked_clip_id" in existing:
            conn.execute(text("ALTER TABLE clips DROP COLUMN linked_clip_id"))


def _drop_publish_account_profile_name() -> None:
    """`publish_accounts` 去掉 `profile_name` —— 这一列在**每一台机器上都是 NULL**。

    后端收它、落库、放进 `PublishAccountOut`;而桌面执行器那侧的 `patchAccount` 签名里
    **根本没有这个字段**,从来没人发过。一列永远为空的数据,和一条写在出参里的空承诺。

    按仓库规矩,死字段是删掉而不是留着 —— 留着的代价是下一个人会以为它有数据,照它写
    分支。SQLite 3.35+ 支持 DROP COLUMN;没有这一列的老库(它本来就是后加的)也不需要
    额外分支,下面那句 `in existing` 就是判据。
    """
    inspector = inspect(engine)
    if "publish_accounts" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(publish_accounts)"))}
        if "profile_name" in existing:
            conn.execute(text("ALTER TABLE publish_accounts DROP COLUMN profile_name"))


def _migrate_client_surface() -> None:
    """`auth_sessions` 补 `client_surface`:自报身份里「哪个界面」那一半。

    此前只有一栏 `client_version`,而浏览器扩展往里塞的是产品名 `browser-extension` ——
    管理页照着渲染 `v{...}`,于是那一行写着「vbrowser-extension」。两个问题挤一栏,总会有
    一个客户端把它读成另一个意思。

    老行留空:它们报的是旧语法(裸版本号),新语法认不出来 —— 而"不知道"本来就是这一栏
    的合法状态。用户的客户端升上来之后,下一个请求就把两栏一起写对。
    """
    inspector = inspect(engine)
    if "auth_sessions" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(auth_sessions)"))}
        if "client_surface" not in existing:
            conn.execute(
                text("ALTER TABLE auth_sessions ADD COLUMN client_surface VARCHAR(32) NOT NULL DEFAULT ''")
            )


def _migrate_job_actor() -> None:
    """`jobs` 补 `created_by`:这活儿**替谁干**。

    后台线程手里只有一个 job,没有这一栏就答不出该用谁的钥匙、花谁的额度(见 domain/jobs.create_job
    与 domain/providers/credentials)。老任务回填成 NULL —— 它们跑完了,而"当初是谁要的"这件事
    老数据里确实没有记过,编一个出来比留空更糟。
    """
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if "created_by" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN created_by VARCHAR(64)"))


def _encrypted(value: object) -> str | None:
    """迁移里往加密列写值时用。空值原样返回(空不是秘密)。"""
    from app.core.secrets_at_rest import encrypt, looks_encrypted

    if value is None or value == "":
        return value if value is None else ""
    raw = value if isinstance(value, str) else str(value)
    return raw if looks_encrypted(raw) else encrypt(raw)


def _migrate_provider_credentials() -> None:
    """钥匙从 `provider_profiles` 搬到 `provider_credentials`,并把那几列删掉。

    升级前所有人共用档案行上那把钥匙。迁移把它归到**最早那位部署管理员**名下 —— 有主人,而且
    只有他能用。别人各配各的(见 domain/providers/credentials:没有"共享钥匙"这回事,它没有界面,
    而且回退到别人的钥匙正是这张表要消灭的东西)。

    **搬走而不是并存**:密钥列留在档案行上,就等于留着一条不经过解析、读到别人钥匙的路。
    列删掉之后,漏改的读取点会当场炸,而不是悄悄读到不该读的东西。

    `auth_type` 留在档案上 —— 它说的是这条连接怎么鉴权,不是谁的钥匙。幂等:列没了就直接返回。

    **先给 provider_credentials 补列再搬**:`create_all` 只建缺失的**表**,从不给已存在的表加列
    —— 一个装过中途版本的库里,这张表可能已经存在但少几列,直接往里插会当场 OperationalError。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "provider_profiles" not in tables:
        return
    if "provider_credentials" in tables:
        # 查列与加列必须在**同一个连接**上:inspect 可能从池里另一条连接读,而那条连接看到的
        # schema 未必是刚刚 DDL 之后的(tests/util.py 里记过同一种症状 —— duplicate column)。
        with engine.begin() as conn:
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_credentials)"))}
            for name, ddl in (
                ("api_key", "ALTER TABLE provider_credentials ADD COLUMN api_key VARCHAR(500) NOT NULL DEFAULT ''"),
                ("oauth_credential", "ALTER TABLE provider_credentials ADD COLUMN oauth_credential JSON"),
                ("secrets", "ALTER TABLE provider_credentials ADD COLUMN secrets JSON NOT NULL DEFAULT '{}'"),
                ("model_catalog", "ALTER TABLE provider_credentials ADD COLUMN model_catalog JSON"),
                (
                    "credential_version",
                    "ALTER TABLE provider_credentials ADD COLUMN credential_version INTEGER NOT NULL DEFAULT 0",
                ),
                ):
                if name not in existing:
                    conn.execute(text(ddl))
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    if "auth_type" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE provider_profiles ADD COLUMN auth_type VARCHAR(20) NOT NULL DEFAULT 'api_key'")
            )
    movable = [c for c in ("api_key", "oauth_credential", "credential_version", "model_catalog") if c in columns]
    if not movable:
        return  # 已经搬过了
    if "provider_credentials" not in tables or "users" not in tables:
        return  # create_all 还没跑到(首次装机),下次启动再补

    with engine.begin() as conn:
        admin = conn.execute(
            text("SELECT id FROM users WHERE is_deployment_admin = 1 ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin is None:
            admin = conn.execute(text("SELECT id FROM users ORDER BY created_at LIMIT 1")).scalar()
        if admin is not None:
            select_cols = ", ".join(movable)
            rows = conn.execute(text(f"SELECT id, {select_cols} FROM provider_profiles")).mappings().all()
            for row in rows:
                api_key = (row.get("api_key") or "") if "api_key" in movable else ""
                oauth = row.get("oauth_credential") if "oauth_credential" in movable else None
                if not api_key and not oauth:
                    continue  # 从来没配过钥匙的连接不用建凭据行
                conn.execute(
                    text(
                        "INSERT OR IGNORE INTO provider_credentials "
                        "(profile_id, owner_user_id, api_key, oauth_credential, secrets, model_catalog, "
                        " credential_version, created_at, updated_at) "
                        "VALUES (:pid, :uid, :key, :oauth, '{}', :catalog, :version, :now, :now)"
                    ),
                    {
                        "pid": row["id"],
                        "uid": admin,
                        # 目标列是加密列(见 core/secrets_at_rest):这条迁移自己写密文,
                        # 而不是指望后面那趟 _migrate_encrypt_secrets 来补 —— 每条迁移
                        # 跑完之后库都该是自洽的。
                        "key": _encrypted(api_key),
                        "oauth": _encrypted(row.get("oauth_credential")) if "oauth_credential" in movable else None,
                        "catalog": row.get("model_catalog") if "model_catalog" in movable else None,
                        "version": row.get("credential_version") or 0 if "credential_version" in movable else 0,
                        "now": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
                    },
                )
        for column in movable:
            conn.execute(text(f"ALTER TABLE provider_profiles DROP COLUMN {column}"))


def _migrate_agent_thinking_level() -> None:
    """加列迁移:agent_sessions 增加 thinking_level。老会话留 'off',与此前行为一致。"""
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("agent_sessions")}
    if "thinking_level" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN thinking_level VARCHAR(10) NOT NULL DEFAULT 'off'"))


def _merge_split_vendors() -> None:
    """把被人为拆开的同一家供应商合回去(只改 vendor 值,档案本身不合并)。

    图像/视频、对话/语音此前各占一个 vendor,理由写在旧注释里:"一处改动不牵连另一处" ——
    那在"一个档案只有一套能力、一个默认模型"的年代成立。供应商⇄模型重构之后一条连接能挂
    任意多个模型、各自带能力,拆分只剩代价:同一把 Key 填两遍,设置页里一个账号占两行。

    **不合并档案本身**:用户可能真的想把图像和视频分开管(不同 Key、不同区域端点),
    那是他的选择;这里只是让"火山方舟"重新变成一个 vendor,两个档案照样并存。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    merges = {
        "bytedance-image": "bytedance",
        # 语音那两个的 vendor id 同时是**持久化的语音引擎 id**,所以合并要连着改
        # tts_config.engine 与历史任务载荷 —— 见 _merge_openai_tts_engine。
        "openai-tts": "openai",
        # openai-compatible-tts 整个退场:它存在的唯一理由是"要填自定义 endpoint",
        # 而 openai 档案本来就有 base_url 字段。
        "openai-compatible-tts": "openai",
    }
    with engine.begin() as conn:
        for old_vendor, new_vendor in merges.items():
            conn.execute(
                text("UPDATE provider_profiles SET vendor=:new WHERE vendor=:old"),
                {"new": new_vendor, "old": old_vendor},
            )


def _merge_openai_tts_engine() -> None:
    """语音引擎 id `openai-tts` / `openai-compatible-tts` → `openai`。

    引擎 id 不只是个显示名:domain/voices/voices.py 拿它当 vendor 去 resolve_connection,所以它同时
    存在于**三处**——tts_config.engine、历史任务的 payload、以及任务结果里记录的"实际用了
    哪个引擎"。只改预设不改这三处,已有配置会在下次合成时找不到档案。

    迁移在启动时跑完,读取代码里因此**不留旧 id 的别名** —— 那种别名是一笔永久的税
    (见 docs/adr/0006),而这里三处都改到了,没有第四处会读到旧串。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    legacy = ("openai-tts", "openai-compatible-tts")
    with engine.begin() as conn:
        if "tts_config" in tables:
            conn.execute(
                text("UPDATE tts_config SET engine='openai' WHERE engine IN ('openai-tts','openai-compatible-tts')")
            )
        if "jobs" in tables:
            # 载荷是 JSON 字符串,SQLite 的 json_set 能就地改;比读出来再写回省一趟,
            # 也不必把整张 jobs 表读进内存。
            for column in ("payload", "result"):
                for old_id in legacy:
                    conn.execute(
                        text(
                            f"UPDATE jobs SET {column} = json_set({column}, '$.engine', 'openai') "
                            f"WHERE json_valid({column}) AND json_extract({column}, '$.engine') = :old"
                        ),
                        {"old": old_id},
                    )


def _adopt_deepseek_vendor() -> None:
    """把明确指向 api.deepseek.com 的「OpenAI 兼容端点」档案改挂 deepseek 预设。

    通用预设为了覆盖各种自建网关声明了 chat/image/embedding,而模型行没显式设能力时会把三样
    全继承 —— DeepSeek 的对话模型于是会出现在「AI 绘图」的可选项里。判据取 base_url 而不是
    名字:域名是确定的,名字是用户随便起的。只改 vendor,base_url/密钥/模型行一概不动。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE provider_profiles SET vendor='deepseek' "
                "WHERE vendor='openai-compatible' AND base_url LIKE '%api.deepseek.com%'"
            )
        )


def _drop_generation_models() -> None:
    """删表:generation_models 退场。

    它曾是"有哪些模型可以生成"的第二个答案 —— 设置页看 provider_models、生成页看这张表,
    两边永远对不齐(ComfyUI 的工作流只在这张表里,而且是个叫 `workflow` 的假模型 id)。
    表里的行全部由 BUILTIN_MODELS 播种、用户改不了,所以直接删,没有需要保留的用户数据;
    那份"某模型支持哪些生成参数"的知识退化成 domain/generation/catalog.capabilities_for
    的一张查表(它本来就是关于供应商 API 的静态知识,不是用户配置)。
    """
    inspector = inspect(engine)
    if "generation_models" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE generation_models"))


def _migrate_generation_job_message_keys() -> None:
    """把生成任务里那句**被当成 key 的英文**换成真正的 key。

    `create_job(message=...)` 收的是 i18n key,而生成流程一直传的是字面量
    "Queued for generation provider" —— 它被原样存进 message_key,而接口是按 key 重翻的,
    于是这些任务**从建出来到跑完**返回的都是这一句:任务早就成功了,界面还写着"已提交给
    生成服务"。用户据此以为任务卡在排队里(真机反馈)。

    新任务由代码修好了(runner 全部走 say());这里把已经落库的那些按终态补上正确的 key。
    只认那一句字面量,认不出的不动 —— 别人手写的自由文本本来就该原样留着。
    """
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("jobs")}
    if "message_key" not in columns:
        return
    mapping = {
        "succeeded": "jobMsg_generationDone",
        "failed": "jobMsg_generationFailed",
        "running": "jobMsg_generationRunning",
        "queued": "jobMsg_generationQueued",
    }
    with engine.begin() as conn:
        for status, key in mapping.items():
            conn.execute(
                text(
                    "UPDATE jobs SET message_key = :key "
                    "WHERE message_key = 'Queued for generation provider' AND status = :status"
                ),
                {"key": key, "status": status},
            )


def _migrate_agent_session_groups() -> None:
    """agent_sessions 新增 group_id —— 会话分组。

    **必须排在 create_all 之前**没有硬要求(它只加一列),但排在前面语义更顺:create_all 建出
    agent_session_groups 那张新表时,成员列已经在了。

    列上**不加外键**:老库用 ALTER TABLE 加列,SQLite 没法事后补约束,新老两种库会长得不一样。
    删分组时由领域层显式把成员置空(见 domain/session_groups.delete_group),两种库行为一致。
    """
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("agent_sessions")}
    if "group_id" in existing:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN group_id VARCHAR(64)"))


def _migrate_session_groups_serve_both() -> None:
    """分组从「对话专属」变成「会话通用」:表改名 + 加 kind,生成会话补 group_id。

    **必须排在 create_all 之前**:否则 create_all 会照新模型建一张空的 session_groups,
    旧的 agent_session_groups 原地留着没人认领 —— 用户建过的分组当场消失。

    kind 的回填是 "agent":这张表此前只装对话分组,没有第二种可能。生成分组是从此刻起
    才建得出来的东西。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "agent_session_groups" in tables:
            # 两张表同时在:说明有谁先跑了 create_all(开发时的 --reload 就会),建出一张空的
            # session_groups,而真正的分组还在旧表里。空表没有任何东西可丢,扔掉它再改名。
            # **不能用「新表不存在才改名」当守卫** —— 那样这些分组会安安静静地留在一张
            # 再没人查的表里,界面上表现为「我建的分组不见了」,而迁移本身一声不吭地成功了。
            if "session_groups" in tables:
                if conn.execute(text("SELECT count(*) FROM session_groups")).scalar_one():
                    raise RuntimeError(
                        "session_groups 和 agent_session_groups 同时有数据 —— 拒绝猜哪份是真的,请人工合并"
                    )
                conn.execute(text("DROP TABLE session_groups"))
            conn.execute(text("ALTER TABLE agent_session_groups RENAME TO session_groups"))
            tables = {"session_groups"} | (tables - {"agent_session_groups"})
        if "session_groups" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("session_groups")}
            if "kind" not in columns:
                conn.execute(text("ALTER TABLE session_groups ADD COLUMN kind VARCHAR(24) NOT NULL DEFAULT 'agent'"))
        if "generation_sessions" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("generation_sessions")}
            if "group_id" not in columns:
                conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN group_id VARCHAR(64)"))


def _migrate_source_assets_get_a_role() -> None:
    """生成请求里的 `source_asset_ids` → `source_assets`,每一项带上角色。

    此前是一个裸 id 列表,谁是首帧靠「第 0 个」这条约定,于是尾帧/参考视频没地方放。
    老数据的角色按 kind 还原成它当初**实际被当成什么用**:视频那边取的是首帧
    (providers/contracts/generation.first_frame_value 读 source_files[0]),图片那边当的是参考图
    (seedream / qwen-edit / openai-edit 都是这么用的)。这不是猜,是把当时的行为写明。
    """
    inspector = inspect(engine)
    if "generation_jobs" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, kind, request FROM generation_jobs")).fetchall()
        for row in rows:
            try:
                request = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(request, dict) or "source_asset_ids" not in request:
                continue
            ids = request.pop("source_asset_ids") or []
            role = "first_frame" if row[1] == "video" else "reference_image"
            request["source_assets"] = [{"asset_id": str(one), "role": role} for one in ids if str(one).strip()]
            conn.execute(
                text("UPDATE generation_jobs SET request = :request WHERE id = :id"),
                {"request": json.dumps(request, ensure_ascii=False), "id": row[0]},
            )


def _migrate_workflow_source_assets() -> None:
    """工作流 generate 节点的 `source_asset_ids` 配置项 → `source_assets`。

    和上面同一件事的另一半:节点配置里存的也是裸 id(模板字段,可能是换行分隔的字符串)。
    只改键名 —— 值的形态解析器两种都认(见 domain/generation/operations.parse_source_assets),
    角色按节点自己的 kind 兜底,和迁移前的行为一致。
    """
    inspector = inspect(engine)
    if "workflows" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).fetchall()
        for row in rows:
            try:
                graph = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            except (TypeError, ValueError):
                continue
            nodes = graph.get("nodes") if isinstance(graph, dict) else None
            if not isinstance(nodes, list):
                continue
            touched = False
            for node in nodes:
                config = node.get("config") if isinstance(node, dict) else None
                if isinstance(config, dict) and "source_asset_ids" in config:
                    config["source_assets"] = config.pop("source_asset_ids")
                    touched = True
            if touched:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(graph, ensure_ascii=False), "id": row[0]},
                )


def _migrate_plugin_registry_url() -> None:
    """deployment_config 新增 plugin_registry_url(插件市场索引地址)。

    create_all 只建新表,不给**已有**表补列。空串 = 用内置默认。
    """
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "plugin_registry_url" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN plugin_registry_url VARCHAR(500) NOT NULL DEFAULT ''"))


def _migrate_shared_host_folders() -> None:
    """deployment_config 新增 shared_host_folders(管理员共享给成员的本机文件夹)。

    create_all 只建新表,不给**已有**表补列。空列表 = 一个都没共享:非管理员读不到本机任何路径,
    只能用素材库里的文件(见 domain/host_files)—— 升级前谁都能填本机路径,那正是要收的口子。
    """
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "shared_host_folders" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN shared_host_folders JSON NOT NULL DEFAULT '[]'"))


def _migrate_outbound_allowlist() -> None:
    """deployment_config 新增 outbound_allowlist(用户给的地址可以去的内网地址,见 core/outbound_guard)。

    空列表 = 只许公网:升级前 HTTP 请求节点、fetch_url 能打本机回环、局域网和云元数据,那正是要收的口子。
    """
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "outbound_allowlist" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN outbound_allowlist JSON NOT NULL DEFAULT '[]'"))


def _migrate_entity_voices_name_their_engine() -> None:
    """人物资产的音色写明是哪个配音引擎的(`attributes.voice_engine`)。

    此前人物的音色只能挑音色库(本地克隆)里的一把嗓子,`voice_id` 就是音色库的 id;现在任何配音引擎的音色
    都能挑,一把嗓子是「引擎 + 那个引擎里的 id」。老的那些都来自音色库:补上 `clone`。
    """
    inspector = inspect(engine)
    if "entities" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, attributes FROM entities WHERE kind = 'character'")).all()
        for entity_id, raw in rows:
            try:
                attributes = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(attributes, dict) or not attributes.get("voice_id") or attributes.get("voice_engine"):
                continue
            attributes["voice_engine"] = "clone"
            conn.execute(
                text("UPDATE entities SET attributes = :attributes WHERE id = :id"),
                {"attributes": json.dumps(attributes, ensure_ascii=False), "id": entity_id},
            )


def _migrate_entity_reference_roles_follow_kind() -> None:
    """参考图的角度按资产种类分开(人物、场景、道具不是一个模板):场景的角度是机位(全景 / 反打 / 俯视),
    没有「正面 / 侧面 / 表情」;道具没有全身和表情。此前三种共用一张表,场景的图可能标成了正面、侧面。

    标得不对的换成这种资产里意思最近的那个(场景的正面 → 全景、侧面 / 背面 → 反打、特写 → 细节);
    表里没有的落到这种资产的缺省角度。词表在这里抄一份定下来 —— 迁移跑的是当时的规矩,不随 catalog 以后变。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "entities" not in tables or "entity_references" not in tables:
        return
    allowed = {
        "character": {"front", "side", "back", "turnaround", "closeup", "full_body", "expression", "concept", "detail"},
        "location": {"wide", "reverse", "overhead", "concept", "detail"},
        "prop": {"front", "side", "back", "turnaround", "closeup", "concept", "detail"},
    }
    nearest = {
        "character": {"wide": "full_body", "reverse": "back", "overhead": "concept"},
        "location": {"front": "wide", "full_body": "wide", "turnaround": "wide", "side": "reverse", "back": "reverse",
                     "closeup": "detail", "expression": "concept"},
        "prop": {"full_body": "front", "expression": "concept", "wide": "concept", "reverse": "back",
                 "overhead": "concept"},
    }
    fallback = {"character": "front", "location": "concept", "prop": "front"}
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT r.entity_id, r.asset_id, r.role, e.kind FROM entity_references r JOIN entities e ON e.id = r.entity_id"
        )).all()
        for entity_id, asset_id, role, kind in rows:
            if kind not in allowed or role in allowed[kind]:
                continue
            conn.execute(
                text("UPDATE entity_references SET role = :role WHERE entity_id = :entity AND asset_id = :asset"),
                {"role": nearest[kind].get(role, fallback[kind]), "entity": entity_id, "asset": asset_id},
            )


def _migrate_blender_models_are_named_after_their_scene() -> None:
    """从 Blender 接回来的模型此前一律叫「Blender model」:模型归工作区、道具的 3D 模型下拉里也列着它们,
    一排同名的分不出是哪一次接回来的。改成「<用它的那个场景> · Blender」;没有场景用它的,按工作区编号(Blender 1、2……)。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "scene_3d_models" not in tables or "scenes_3d" not in tables:
        return
    with engine.begin() as conn:
        models = conn.execute(text(
            "SELECT id, workspace_id FROM scene_3d_models WHERE name = 'Blender model' ORDER BY id"
        )).all()
        if not models:
            return
        used_by: dict[str, str] = {}
        for scene_name, raw in conn.execute(text("SELECT name, content FROM scenes_3d ORDER BY created_at")).all():
            try:
                content = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            for obj in (content or {}).get("objects") or []:
                if isinstance(obj, dict) and obj.get("model_id") and obj["model_id"] not in used_by:
                    used_by[obj["model_id"]] = str(scene_name or "")
        unused: dict[str, int] = {}
        for model_id, workspace_id in models:
            scene = used_by.get(model_id, "").removesuffix(" · Blender").strip()
            if scene:
                name = f"{scene} · Blender"
            else:
                unused[workspace_id] = unused.get(workspace_id, 0) + 1
                name = f"Blender {unused[workspace_id]}"
            conn.execute(text("UPDATE scene_3d_models SET name = :name WHERE id = :id"), {"name": name[:160], "id": model_id})


def _migrate_board_documents_can_be_written() -> None:
    """画板上的文档格也会「让 AI 写」(写出一篇笔记):每一格还没写明产出者的文档格写明 `write`。

    新放下的文档格由 normalize 按 producer_ids.SLOT_PRODUCERS 补;存着的画布在这里补一次,面板照它挂 ——
    不补的话老画板上的文档格没有这个按钮,直到哪一次保存碰巧把它补上。改到的板版本号 +1。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") != "document":
                    continue
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                if form.get("producer"):
                    continue
                item["form"] = {**form, "producer": "write"}
                changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_board_scene_cells_hold_no_image() -> None:
    """3D 场景格不再存图(ADR 0029 §1):摘掉每一格场景格上的 `asset_id`。

    那是编辑器「生成素材」时导出的一帧,格子上此前画它、连到下游时当图片喂出去。现在格子上画场景的全景白模(现渲),
    连到下游给的是场景;那一帧素材本身还在素材库里,当初也一起放下了一格图片。改到的板版本号 +1。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                if isinstance(item, dict) and item.get("kind") == "scene" and "asset_id" in item:
                    del item["asset_id"]
                    changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_board_failures_keep_their_original_error() -> None:
    """画板上失败的格子:`run.error` 换成给人看的那一句,原文搬进 `run.error_detail`(UC-06,见 domain/failure_summary)。

    此前回执把任务的原文截 300 字放在 `run.error`,格子上照贴 —— 一串 httpx 的英文、一条带签名的地址、一截「For more
    information check」。现在回执存两样:摘出来的那一句和原文。老格子上只有原文、没有 key,按同一套清理规则摘一句
    (认不出类别,但去掉了套话、地址和尾巴);两样一样(本来就是一句人话)就不动。改到的板版本号 +1。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    from app.core.i18n import DEFAULT_LOCALE
    from app.domain.failure_summary import summarize

    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                run = item.get("run") if isinstance(item, dict) else None
                if not isinstance(run, dict) or run.get("status") != "failed" or "error_detail" in run:
                    continue
                original = run.get("error")
                if not isinstance(original, str) or not original.strip():
                    continue
                summary = summarize(original, "", {}, DEFAULT_LOCALE)
                if summary and summary != original.strip():
                    run["error"] = summary[:300]
                    run["error_detail"] = original.strip()
                    changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_boards_remember_their_project() -> None:
    """画板记着自己的项目(`boards.project_id`,ADR 0030):时间线格背后的时间线放在那里。老画板没有,第一次放
    时间线格时才建 —— 这里只加列。**必须在 SCHEMA 之前**:create_all 不会给已有的表补列。"""
    inspector = inspect(engine)
    if "boards" not in set(inspector.get_table_names()):
        return
    if "project_id" in {column["name"] for column in inspector.get_columns("boards")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE boards ADD COLUMN project_id VARCHAR(64)"))


def _migrate_board_documents_keep_the_note_they_became() -> None:
    """「转为笔记」之后又被补回原件的文档格:留着笔记(`note_id`),摘掉 `asset_id`。

    文档格引用一篇笔记**或**一份文档素材,二选一(normalize 的 boardErr_documentNoteOrAsset)。此前保存时
    「运行态和产出归服务端」把客户端去掉的 `asset_id` 又补了回来,不再校验就落了库 —— 这张板从此每一次保存
    都被拒。用户最后一步做的是「转为笔记」,所以留笔记。改到的板版本号 +1。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                if isinstance(item, dict) and item.get("kind") == "document" and item.get("note_id") and "asset_id" in item:
                    del item["asset_id"]
                    changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_board_sequence_cells_name_their_producer() -> None:
    """时间线格挂导出(ADR 0030 §4,`sequence_export`):已经放下的时间线格写明它的产出者,面板照它挂。

    新写入的由 normalize 按 SLOT_PRODUCERS 补;这里补的是还没被写过一次的那些。改到的板版本号 +1。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") != "sequence":
                    continue
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                if form.get("producer") is None:
                    item["form"] = {**form, "producer": "sequence_export"}
                    changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_job_receipts_get_their_own_role() -> None:
    """后台任务的回执从「用户消息」改成自己的角色 `job_receipt`(见 domain/agent/host.JOB_RECEIPT_ROLE)。

    此前回执借用户的名义进会话:role=user,来源记在 payload.from_job;会话正忙时还带着 queued / queued_by
    进了排队 —— 输入框上方排出一串「已完成」,带着 Steer 和删除。现在:
      · 交给过智能体的(没有 queued)→ `{job_id}`;
      · 还排着的(queued)→ `{job_id, undelivered: true, deliver_as: <queued_by>}`,下一轮收尾时一并交出去。
    回执消息的 payload 里没有别的东西(引用、正文文档、上下文都是人发的消息才有),所以整个换掉。
    不是回执的用户消息(含另一个会话发来的通知)不动。重跑:已经换过的不再是 role=user,什么都不做。
    """
    if "agent_messages" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, payload FROM agent_messages WHERE role = 'user' AND payload LIKE '%from_job%'")
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row.payload) if isinstance(row.payload, str) else (row.payload or {})
            except ValueError:
                continue
            if not isinstance(payload, dict) or not payload.get("from_job"):
                continue
            receipt: dict[str, Any] = {"job_id": str(payload["from_job"])}
            if payload.get("queued"):
                receipt["undelivered"] = True
                if payload.get("queued_by"):
                    receipt["deliver_as"] = str(payload["queued_by"])
            conn.execute(
                text("UPDATE agent_messages SET role = 'job_receipt', payload = :p WHERE id = :i"),
                {"p": json.dumps(receipt, ensure_ascii=False), "i": row.id},
            )


def _migrate_agent_session_titles_drop_attachment_tokens() -> None:
    """会话标题里的附件标记去掉:此前标题直接截首条消息的前 60 个字,挂了附件的会话标题里就是一截
    `[附件 asset_id=… 名称=…`。照首条用户消息重算 —— 附件标记、文本附件的围栏块都不算;只发了附件的用附件名。
    只动标题里带着那截标记的会话(用户自己改过的标题不会长这样)。规则抄一份在这里:迁移不跟着领域代码变。
    """
    import re

    attached = re.compile(r"\[附件 asset_id=(\S+) 名称=(.*?) 类型=([a-z]+)\]")
    fenced = re.compile(r"\[[^\]\n]+\]\n```.*?(```|$)", re.S)
    if "agent_sessions" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id FROM agent_sessions WHERE title LIKE :marker"),
                            {"marker": "%[附件 asset_id=%"}).fetchall()
        for (session_id,) in rows:
            first = conn.execute(
                text("SELECT content FROM agent_messages WHERE session_id = :id AND role = 'user' "
                     "ORDER BY created_at, id LIMIT 1"),
                {"id": session_id},
            ).scalar()
            if not first:
                continue
            names = [name.strip() for _id, name, _kind in attached.findall(first) if name.strip()]
            said = " ".join(fenced.sub(" ", attached.sub(" ", first)).split())
            title = (said or (names[0] if names else first.strip()))[:60]
            conn.execute(text("UPDATE agent_sessions SET title = :title WHERE id = :id"), {"title": title, "id": session_id})


def _migrate_generation_jobs_keep_their_failure() -> None:
    """generation_jobs 补失败原因三列(`error` / `error_key` / `error_params`,和 jobs 同形)。

    此前失败原因只在任务上,而任务会被任务中心的「清空已结束」删掉(生成记录的 job_id 随之置空)—— 清过一次,
    AI 工作台的失败卡就只剩一句「生成失败」。加列必须在 SCHEMA 之前:之后 ORM 上的 GenerationJob 已经指望它们在了。
    已有记录的回填在 AFTER_SCHEMA 的 backfill-generation-failures:它要读 jobs.error_key,那一列在很老的库上
    是 AFTER_SCHEMA 才补上的。
    """
    inspector = inspect(engine)
    if "generation_jobs" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("generation_jobs")}
    with engine.begin() as conn:
        if "error" not in columns:
            conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN error TEXT"))
        if "error_key" not in columns:
            conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN error_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "error_params" not in columns:
            conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN error_params JSON NOT NULL DEFAULT '{}'"))


def _backfill_generation_failures() -> None:
    """已经失败、任务还在的生成记录,把任务上的失败原因抄过来(key、参数、原话一起)。

    任务已经被清掉的那些找不回原因了 —— 它们照旧显示「生成失败」。有产出的不动(那是成功的),已经有原因的不动。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"generation_jobs", "jobs"} <= tables:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE generation_jobs SET "
                "error = (SELECT jobs.error FROM jobs WHERE jobs.id = generation_jobs.job_id), "
                "error_key = (SELECT jobs.error_key FROM jobs WHERE jobs.id = generation_jobs.job_id), "
                "error_params = (SELECT jobs.error_params FROM jobs WHERE jobs.id = generation_jobs.job_id) "
                "WHERE result_asset_id IS NULL AND error IS NULL "
                "AND job_id IN (SELECT id FROM jobs WHERE status = 'failed')"
            )
        )


def _migrate_generation_sessions_know_their_kind() -> None:
    """每条生成会话都记下种类:AI 工作台按它分页 —— 图像 / 视频在「生成」页,音乐 / 音效在「音频」页。

    此前 kind 只在用户在选择器里点过模型时才写,从画板、工作流、智能体、定时任务开出来的会话一律是空的;而音频模型
    此前和图像、视频挤在同一个选择器里,一条会话可以先出图、后出歌。规则:会话记着的就是它**最后一次生成**用的那个
    (连接、模型、种类)—— 只在会话没记种类、或记着的和最后一次生成不在同一页时改写(一页之内换过模型的不动,
    那是用户的选择);从没生成过又没记种类的归「生成」页。先出图后出歌的会话整条跟着最后那一次走,历史一条不少。
    """
    if "generation_sessions" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        sessions = conn.execute(text("SELECT id, kind FROM generation_sessions")).all()
        for session_id, kind in sessions:
            latest = conn.execute(
                text(
                    "SELECT kind, model, provider_profile_id FROM generation_jobs WHERE session_id = :id "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"id": session_id},
            ).first()
            if latest is None:
                if not kind:
                    conn.execute(text("UPDATE generation_sessions SET kind = 'image' WHERE id = :id"), {"id": session_id})
                continue
            if kind and (kind == "audio") == (latest[0] == "audio"):
                continue
            conn.execute(
                text(
                    "UPDATE generation_sessions SET kind = :kind, model = :model, provider_profile_id = :profile "
                    "WHERE id = :id"
                ),
                {"kind": latest[0], "model": latest[1], "profile": latest[2], "id": session_id},
            )


def _migrate_generation_prompts_drop_the_source_legend() -> None:
    """生成记录里的提示词拆开:用户写的留在 `prompt`,画板替他补的「本次提供的素材:…」挪进 `prompt_notes`。

    画板此前在前端把这段对照拼进提示词再提交,于是记录里存的是拼过的字,AI 工作台的用户气泡原样画出来。现在这段由
    生成漏斗补(generation.operations.source_legend),记在 `prompt_notes` 里,交给供应商时再接上 —— 模型收到的
    和原来一字不差。切分依据是前端那条文案的中英原文(`boardPromptLegend`,自加进来就没改过),连同它前面那个空行;
    它后面的(上游文档、3D 参考的说明、资产描述)原样跟着挪过去。任务上那份请求副本和任务标题一起改。
    """
    markers = ("\n\n本次提供的素材:", "\n\nMaterials provided with this request:")

    def split(request: dict[str, Any]) -> dict[str, Any] | None:
        prompt = request.get("prompt")
        if not isinstance(prompt, str):
            return None
        found = [index for index in (prompt.find(marker) for marker in markers) if index >= 0]
        if not found:
            return None
        cut = min(found)
        notes = [one for one in request.get("prompt_notes") or [] if isinstance(one, str)]
        return {**request, "prompt": prompt[:cut], "prompt_notes": [prompt[cut + 2:], *notes]}

    def _json_object(raw: Any) -> dict[str, Any]:
        """JSON 列读出来的一个对象;空的、坏的、不是对象的当它什么都没有(没有提示词可拆)。"""
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return {}
        return dict(value) if isinstance(value, dict) else {}

    tables = set(inspect(engine).get_table_names())
    if "generation_jobs" not in tables:
        return
    with engine.begin() as conn:
        for generation_id, raw in conn.execute(text("SELECT id, request FROM generation_jobs")).all():
            changed = split(_json_object(raw))
            if changed is not None:
                conn.execute(
                    text("UPDATE generation_jobs SET request = :request WHERE id = :id"),
                    {"request": json.dumps(changed, ensure_ascii=False), "id": generation_id},
                )
        if "jobs" not in tables:
            return
        for job_id, raw in conn.execute(text("SELECT id, payload FROM jobs WHERE kind = 'ai_generation'")).all():
            payload = _json_object(raw)
            request = payload.get("request")
            changed = split(request) if isinstance(request, dict) else None
            if changed is not None:
                payload = {**payload, "request": changed, "subject": changed["prompt"][:80]}
                conn.execute(
                    text("UPDATE jobs SET payload = :payload WHERE id = :id"),
                    {"payload": json.dumps(payload, ensure_ascii=False), "id": job_id},
                )


def _migrate_generation_prompts_drop_the_reference_documents() -> None:
    """生成记录里的提示词再拆一刀:画板替用户拼进去的上游文档(「Reference documents (source material):」起)挪进
    `prompt_notes`,排在已有补充的最前面。

    画板此前在前端把连进来的文档整篇拼进提示词再提交,AI 工作台的用户气泡把文档正文当成他说的话画出来。现在文档由
    生成漏斗补(generation.operations.documents_note)。切分依据是前端那条抬头的原文(自加进来就没改过、没翻译过),
    连同它前面那个空行;模型收到的顺序不变(提示词、文档、原有的补充)。上一步迁移已经把「素材对照 + 它后面的文档」
    整段挪走的记录里找不到这条抬头,不动。任务上那份请求副本和任务标题一起改。
    """
    marker = "\n\nReference documents (source material):"

    def split(request: dict[str, Any]) -> dict[str, Any] | None:
        prompt = request.get("prompt")
        if not isinstance(prompt, str):
            return None
        cut = prompt.find(marker)
        if cut < 0:
            return None
        notes = [one for one in request.get("prompt_notes") or [] if isinstance(one, str)]
        return {**request, "prompt": prompt[:cut], "prompt_notes": [prompt[cut + 2:], *notes]}

    def _json_object(raw: Any) -> dict[str, Any]:
        """JSON 列读出来的一个对象;空的、坏的、不是对象的当它什么都没有(没有提示词可拆)。"""
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return {}
        return dict(value) if isinstance(value, dict) else {}

    tables = set(inspect(engine).get_table_names())
    if "generation_jobs" not in tables:
        return
    with engine.begin() as conn:
        for generation_id, raw in conn.execute(text("SELECT id, request FROM generation_jobs")).all():
            changed = split(_json_object(raw))
            if changed is not None:
                conn.execute(
                    text("UPDATE generation_jobs SET request = :request WHERE id = :id"),
                    {"request": json.dumps(changed, ensure_ascii=False), "id": generation_id},
                )
        if "jobs" not in tables:
            return
        for job_id, raw in conn.execute(text("SELECT id, payload FROM jobs WHERE kind = 'ai_generation'")).all():
            payload = _json_object(raw)
            request = payload.get("request")
            changed = split(request) if isinstance(request, dict) else None
            if changed is not None:
                payload = {**payload, "request": changed, "subject": changed["prompt"][:80]}
                conn.execute(
                    text("UPDATE jobs SET payload = :payload WHERE id = :id"),
                    {"payload": json.dumps(payload, ensure_ascii=False), "id": job_id},
                )


def _migrate_asset_extractions_remember_page_images() -> None:
    """文档的解析结果记下按页的页面图(`asset_extractions.page_images`,ADR 0031:「原版」那一栏照它排)。

    先前的解析把页面图只挂在各段上(outline),Word 那种段和页对不上的就没处放。已有的行从 outline 里把页面图
    抄过来。**必须在 SCHEMA 之前**:create_all 不会给已有的表补列。
    """
    inspector = inspect(engine)
    if "asset_extractions" not in set(inspector.get_table_names()):
        return
    if "page_images" in {column["name"] for column in inspector.get_columns("asset_extractions")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE asset_extractions ADD COLUMN page_images JSON NOT NULL DEFAULT '[]'"))
        for row_id, raw in conn.execute(text("SELECT id, outline FROM asset_extractions")).fetchall():
            try:
                outline = json.loads(raw) if isinstance(raw, str) else (raw or [])
            except (TypeError, ValueError):
                continue
            images = [str(one["image"]) for one in outline if isinstance(one, dict) and one.get("image")]
            if images:
                conn.execute(text("UPDATE asset_extractions SET page_images = :images WHERE id = :id"),
                             {"images": json.dumps(images), "id": row_id})


def _migrate_voices_declare_consent() -> None:
    """克隆音色加授权声明(ADR 0028 §5):`consent_kind` / `consent_by` / `consent_at`。

    已有的音色一律写成 `undeclared`(「未声明」)—— 当初建的时候没问过这把嗓子是谁的,替用户补一个「本人」
    就是替他声明。未声明的音色照常能配音,用于数字人(让它说话、对口型)之前要在配音库里补上。
    **必须在 SCHEMA 之前**:create_all 不会给已有的表补列,而之后 ORM 上的 Voice 已经指望这几列在了。
    """
    inspector = inspect(engine)
    if "voices" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("voices")}
    with engine.begin() as conn:
        if "consent_kind" not in existing:
            conn.execute(text("ALTER TABLE voices ADD COLUMN consent_kind VARCHAR(16) NOT NULL DEFAULT 'undeclared'"))
        if "consent_by" not in existing:
            conn.execute(text("ALTER TABLE voices ADD COLUMN consent_by VARCHAR(64)"))
        if "consent_at" not in existing:
            conn.execute(text("ALTER TABLE voices ADD COLUMN consent_at DATETIME"))


def _migrate_cloned_speech_remembers_its_voice() -> None:
    """克隆音色配出来的音频素材记下是哪把嗓子配的:`assets.media_info.voice_id`。

    数字人生成的漏斗要照它查音色的授权声明(generation.operations.check_digital_human_rights):此前只有数字人工作流
    节点查,AI 工作台、画板、智能体拿一段用未声明的克隆音色配的音就能做数字人。新配的音登记时就记上(voices 的克隆
    合成);已有的从当初那一单配音任务补 —— 任务的 payload 记着 `voice_id`,result 记着产出的 `asset_id`。
    `voice_id` 对得上一行克隆音色才补(引擎自带的嗓子不是谁的克隆)。幂等:已经记着的不动。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"jobs", "assets", "voices"} <= tables:
        return

    def loaded(raw: Any) -> dict[str, Any]:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    with engine.begin() as conn:
        voices = set(conn.execute(text("SELECT id FROM voices")).scalars())
        rows = conn.execute(text("SELECT payload, result FROM jobs WHERE kind = 'tts' AND status = 'succeeded'")).fetchall()
        for raw_payload, raw_result in rows:
            voice_id = str(loaded(raw_payload).get("voice_id") or "")
            asset_id = str(loaded(raw_result).get("asset_id") or "")
            if voice_id not in voices or not asset_id:
                continue
            #: 素材已经删了的:查回 None,UPDATE 也碰不到任何一行。
            info = loaded(conn.execute(text("SELECT media_info FROM assets WHERE id = :a"), {"a": asset_id}).scalar_one_or_none())
            if info.get("voice_id"):
                continue
            conn.execute(
                text("UPDATE assets SET media_info = :m WHERE id = :a"),
                {"m": json.dumps({**info, "voice_id": voice_id}, ensure_ascii=False), "a": asset_id},
            )


def _migrate_board_scene_render_drops_project() -> None:
    """画板 3D 场景格的渲白模不再有「项目」(归档进哪个项目):摘掉存着的 `form.config.project_id`。

    渲出来的首尾帧、运镜视频本来就落成右边的几格,归档没有意义,面板上也不再给这一项(boards.producers 的
    SCENE_RENDER_FIELDS)。留着的话它是一份没人读、也改不了的值。改到的板版本号 +1。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                form = item.get("form") if isinstance(item, dict) and item.get("kind") == "scene" else None
                config = form.get("config") if isinstance(form, dict) else None
                if isinstance(config, dict) and "project_id" in config:
                    del config["project_id"]
                    changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_drop_the_community_integration() -> None:
    """把桌面端接入社区时加的东西删掉 —— 社区能力整体从应用里拿掉了(2026-09-27,维护者:「先把资产库做好」)。

    接入时加过:部署的社区地址(`deployment_config.community_url`)、画板分享用的随机 id(`boards.board_key`)、
    工作流发布后的 slug(`workflows.community_slug`)、资产的社区来源(`entities.community`),两张表
    `community_accounts`(社区账号的刷新令牌)和 `board_shares`(画板分享的本机记忆),以及画板分享任务
    (`jobs.kind = 'board_share'`,它的提示文案随功能一起没了,留着只会显示成一串 key)。

    那几条加列的迁移从没随版本发出去,已经从计划里拿掉;这一条只为跑过它们的库(开发机)收尾,
    新装机和从 1.7.0 升上来的库上什么都不做。以后重新接入社区时按那时的需求重新建模。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns = {
        "deployment_config": "community_url",
        "boards": "board_key",
        "workflows": "community_slug",
        "entities": "community",
    }
    with engine.begin() as conn:
        for table in ("board_shares", "community_accounts"):
            if table in tables:
                conn.execute(text(f"DROP TABLE {table}"))
        if "jobs" in tables:
            conn.execute(text("DELETE FROM jobs WHERE kind = 'board_share'"))
        for table, column in columns.items():
            if table in tables and column in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def _backfill_workflow_revision_authors() -> None:
    """给说不出作者的工作流修订补上作者:这条工作流的创建者,找不到就是它所在工作区的 owner。

    一次运行用私有发布账号 / 浏览器档案 / 本机文件时,被执行那一版的作者(或认可过它的人)也得
    用得了(见 domain/authority)。此前 `created_by` 可空:迁移、官方模板改写落下的修订都没有作者,
    更早的版本里写入路径也不总是填它 —— 不补的话,升级之后每条老工作流的定时任务都会停下来
    要人认可,而单机用户根本不知道在认可什么。

    「创建者」取这条工作流**最早一版里有记录的作者**;一版都没有记录时取工作区 owner(最早加入的
    那位)。都找不到的留空 —— 那一版没有担保人,借不到任何人的私有资源,直到有人认可它。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"workflow_revisions", "workflows", "workspace_members"} <= tables:
        return
    with engine.begin() as conn:
        workflows = conn.execute(
            text(
                "SELECT DISTINCT w.id, w.workspace_id FROM workflows w "
                "JOIN workflow_revisions r ON r.workflow_id = w.id WHERE r.created_by IS NULL"
            )
        ).all()
        for workflow_id, workspace_id in workflows:
            author = conn.execute(
                text(
                    "SELECT r.created_by FROM workflow_revisions r JOIN users u ON u.id = r.created_by "
                    "WHERE r.workflow_id = :id ORDER BY r.revision LIMIT 1"
                ),
                {"id": workflow_id},
            ).scalar()
            if author is None:
                author = conn.execute(
                    text(
                        "SELECT user_id FROM workspace_members WHERE workspace_id = :ws AND role = 'owner' "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"ws": workspace_id},
                ).scalar()
            if author is None:
                continue
            conn.execute(
                text("UPDATE workflow_revisions SET created_by = :author WHERE workflow_id = :id AND created_by IS NULL"),
                {"author": author, "id": workflow_id},
            )


def _cleanup_orphan_resource_shares() -> None:
    """清掉指向已删资源的共享记录。

    `resource_shares.resource_id` 是多态引用(同一列指向五张表),建不了外键、也就没有级联,
    而删除路径此前没人清 —— 记录留在库里指向一个不存在的 id,越攒越多。真库里撞见的时候,
    19 条 generation_session 记录里有 16 条是这样的。

    删除路径现在都会清了(由 tests/test_sharing_forgets_on_delete.py 钉住),这一条只处理
    存量。**每次启动都跑**:它按 kind 逐张表反查,没有孤儿时是几条空查询。
    """
    tables = {
        "publish_account": "publish_accounts",
        "browser_profile": "browser_profiles",
        "agent_session": "agent_sessions",
        "generation_session": "generation_sessions",
        "scheduled_task": "scheduled_tasks",
    }
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    if "resource_shares" not in present:
        return
    with engine.begin() as conn:
        for kind, table in tables.items():
            if table not in present:
                continue
            removed = conn.execute(
                text(
                    f"DELETE FROM resource_shares WHERE kind = :kind "  # noqa: S608 — 表名来自上面那张常量表
                    f"AND resource_id NOT IN (SELECT id FROM {table})"
                ),
                {"kind": kind},
            ).rowcount
            if removed:
                logger.info("清掉 %d 条指向已删 %s 的共享记录", removed, kind)


def _migrate_agent_notice_envelope_out_of_content() -> None:
    """把跨会话通知的**信封**从正文里剥出来,来源改记进 payload。

    这句信封(「【来自另一个智能体会话的通知】发起会话 id:<32位>」)是写给模型的,此前被拼进
    了 content —— 而 content 正是用户在对话里看到的那一份,于是界面上就多出一行方括号标签
    加一串十六进制。现在信封只在拼提示词时加(见 domain/agent/prompt.agent_notice_envelope),
    「谁发来的」在库里只留一个表示:payload.from_agent_session。

    存量这么写的消息在这里一次性改正,而不是让前端去认那个前缀 —— 靠字符串匹配认信封,正是
    这件事一开始就该避免的做法。
    """
    import json
    import re

    inspector = inspect(engine)
    if "agent_messages" not in set(inspector.get_table_names()):
        return
    pattern = re.compile(r"^【来自另一个智能体会话的通知】发起会话 id:(\S+)\n\n", re.S)
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, content, payload FROM agent_messages WHERE role='user' AND content LIKE '【来自另一个智能体会话的通知】%'")
        ).fetchall()
        for row in rows:
            match = pattern.match(row.content or "")
            if not match:
                continue
            origin = match.group(1)
            payload = {}
            if row.payload:
                try:
                    payload = json.loads(row.payload) or {}
                except (TypeError, ValueError):
                    payload = {}
            # id 未知的那批(工具当时取不到自己的会话)只剥前缀,不编一个来源出来。
            if origin != "(未知)":
                payload["from_agent_session"] = origin
            conn.execute(
                text("UPDATE agent_messages SET content=:c, payload=:p WHERE id=:i"),
                {"c": row.content[match.end():], "p": json.dumps(payload, ensure_ascii=False), "i": row.id},
            )


def _migrate_agent_session_order() -> None:
    """删掉 agent_sessions.sort_order —— 对话不再支持手动拖排序。

    这一列曾经存"手动拖出来的位次",列表按 (sort_order, updated_at desc) 取。拖排序这个能力
    去掉之后它就没有读者了,顺序回落到纯粹的「最近更新在前」;留着一个没人读的列,下次有人看到
    它只会去猜它还有没有用。

    SQLite 从 3.35 起支持 DROP COLUMN;删不掉就跳过 —— 一个没人读的列不影响任何行为(同
    provider_profiles 那几处的取舍)。
    """
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    if "sort_order" not in {c["name"] for c in inspector.get_columns("agent_sessions")}:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agent_sessions DROP COLUMN sort_order"))
    except Exception:  # noqa: BLE001 —— 老 SQLite 不支持,留着无害
        pass


def _migrate_agent_session_plan() -> None:
    """加列迁移:agent_sessions 增加 plan(任务计划)。老会话留 NULL = 还没有计划。"""
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    if "plan" in {col["name"] for col in inspector.get_columns("agent_sessions")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN plan JSON"))


def _backfill_provider_models() -> None:
    """把「一档案一模型」的老数据搬成模型行。

    每个已有档案生成一行 provider_models:model_id 取它的 default_model,能力取档案上的覆盖
    (为空则留空列表,由后续解析回落 vendor 预设,语义一致)。迁移后用户看到的是"连接展开后
    有一个模型",一比一,没有任何东西消失。

    只在表为空时跑一次 —— 这是一次性的形状迁移,不是每次启动的同步。default_model 为空的
    档案不生成行:凭空造一个空模型只会让选择器里多出一个选不了的条目。

    **用裸 SQL 而不是 ORM 构造**,与本文件其它回填一致:迁移不属于任何领域,直接 new 领域
    模型会绕过归属约束(见 domain/ownership.py 与数据归属棘轮测试)。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "provider_models" not in tables or "provider_profiles" not in tables:
        return
    # 只有**老库**才有 default_model 这列可读。新库由 create_all 直接建成没有它的形状,
    # 此时无从回填也无需回填 —— 不加这道判断,全新安装会在启动时直接崩在这条 SELECT 上。
    if "default_model" not in {col["name"] for col in inspector.get_columns("provider_profiles")}:
        return
    from app.db.models import new_id

    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM provider_models LIMIT 1")).first() is not None:
            return
        rows = conn.execute(
            text("SELECT id, default_model, capability_ids FROM provider_profiles WHERE default_model != ''")
        ).fetchall()
        for row in rows:
            capabilities = row[2] if isinstance(row[2], str) else json.dumps(row[2] or [], ensure_ascii=False)
            conn.execute(
                text(
                    "INSERT INTO provider_models "
                    "(id, provider_profile_id, model_id, display_name, capability_ids, enabled, source, created_at, updated_at) "
                    "VALUES (:id, :pid, :model, '', :caps, 1, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": new_id(), "pid": row[0], "model": row[1], "caps": capabilities},
            )


def _migrate_provider_default_model_fk() -> None:
    """provider_defaults 增加 provider_model_id 并回填。

    老行存的是 (provider_profile_id, model) 这一对字符串 —— 行为一致,但没法引用、没法查询
    "哪一行是 image 的默认"。回填时按这对去 provider_models 里找对应行;找不到就留空,由
    resolve_default 退回"该能力下第一个可用模型",不会变成未配置。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "provider_defaults" not in tables or "provider_models" not in tables:
        return
    columns = {col["name"] for col in inspector.get_columns("provider_defaults")}
    with engine.begin() as conn:
        if "provider_model_id" not in columns:
            conn.execute(text("ALTER TABLE provider_defaults ADD COLUMN provider_model_id VARCHAR(64)"))
        if "provider_profile_id" in columns and "model" in columns:
            conn.execute(
                text(
                    "UPDATE provider_defaults SET provider_model_id = ("
                    "  SELECT pm.id FROM provider_models pm"
                    "  WHERE pm.provider_profile_id = provider_defaults.provider_profile_id"
                    "    AND pm.model_id = provider_defaults.model"
                    ") WHERE provider_model_id IS NULL"
                )
            )
            # 搬完就删:同一件事留两份,总有一份会漂移成错的。
            for legacy in ("provider_profile_id", "model"):
                conn.execute(text(f"ALTER TABLE provider_defaults DROP COLUMN {legacy}"))


def _drop_legacy_profile_columns() -> None:
    """删掉 provider_profiles 上退役的 default_model / capability_ids。

    两者都是"一档案一模型"时代的字段:default_model 不区分能力(对话档案的默认模型被拿去当
    生图模型用过),capability_ids 挂在连接上导致同一个端点只能二选一。能力与模型现在都在
    provider_models 行上,读取点已全部切走(见 domain/providers/models)。

    SQLite 从 3.35 起支持 DROP COLUMN;删不掉就跳过 —— 留着一个没人读的列不影响任何行为,
    而在启动路径上抛异常会让应用起不来。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    for name in ("default_model", "capability_ids", "model_overrides"):
        if name not in columns:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE provider_profiles DROP COLUMN {name}"))
        except Exception:  # noqa: BLE001 — 老版本 SQLite 不支持;留着无害
            logger.info("provider_profiles.%s 未能删除(SQLite 版本不支持 DROP COLUMN),留着无害", name)


def _migrate_job_parent() -> None:
    """加列迁移:jobs 增加 parent_job_id —— 工作流派生的子任务归到父工作流下,
    任务中心不再把子任务与父工作流平铺成两行。老行留 NULL 即顶层任务,语义正确。"""
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    if "parent_job_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN parent_job_id VARCHAR(64)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_parent_job_id ON jobs (parent_job_id)"))


def _migrate_browser_pool() -> None:
    """浏览器池:browser_sessions / publish_accounts 增加 profile_id(加列,保留既有数据)。
    browser_profiles 表本身由 create_all 建;发布账号→档案的回填在 create_all 之后跑
    (见 _backfill_browser_pool),那时表才存在。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "browser_sessions" in tables:
            if "profile_id" not in {c["name"] for c in inspector.get_columns("browser_sessions")}:
                conn.execute(text("ALTER TABLE browser_sessions ADD COLUMN profile_id VARCHAR(64)"))
        if "publish_accounts" in tables:
            if "profile_id" not in {c["name"] for c in inspector.get_columns("publish_accounts")}:
                conn.execute(text("ALTER TABLE publish_accounts ADD COLUMN profile_id VARCHAR(64)"))


def _backfill_browser_pool() -> None:
    """给还没挂档案的发布账号,按其分区 persist:<prefix>-<id> 建一个 browser_profiles 档案并
    回填 profile_id。组合(不合并):发布账号表保留,只多一个指针。幂等——只处理 profile_id 为空的
    账号。分区与 Electron 的约定一致 → 打开同一分区,发布登录态不丢。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "publish_accounts" not in tables or "browser_profiles" not in tables:
        return
    from app.db.models import new_id

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, workspace_id, name, proxy, enabled FROM publish_accounts WHERE profile_id IS NULL")
        ).fetchall()
        for acc in rows:
            pid = new_id()
            conn.execute(
                text(
                    'INSERT INTO browser_profiles (id, workspace_id, name, "partition", proxy, enabled, created_at, updated_at) '
                    "VALUES (:id, :ws, :name, :part, :proxy, :enabled, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": pid, "ws": acc.workspace_id, "name": acc.name, "part": f"persist:{PARTITION_PREFIX}-{acc.id}", "proxy": acc.proxy, "enabled": acc.enabled},
            )
            conn.execute(
                text("UPDATE publish_accounts SET profile_id = :pid WHERE id = :aid"),
                {"pid": pid, "aid": acc.id},
            )


def _migrate_drop_local_publish_accounts() -> None:
    """清掉 platform 为 folder / webhook 的「发布账号」及其空壳浏览器档案。

    这两个从来不是账号:没有登录身份、没有平台、没有风控,却因为 create_account 无条件建档,
    每存在一个就在浏览器池里留一个永远不会有登录态的空壳,还占一个永远不会被使用的 Chromium
    分区名。它们代表的能力(拷到目录 / POST 给外部自动化)已从产品中移除,所以这里直接清理,
    而不是搬到别处。

    幂等:匹配不到就什么都不做,可反复跑。
    """
    inspector = inspect(engine)
    if "publish_accounts" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, profile_id FROM publish_accounts WHERE platform IN ('folder', 'webhook')")
        ).mappings().all()
        if not rows:
            return
        for row in rows:
            if row["profile_id"]:
                conn.execute(text("DELETE FROM browser_profiles WHERE id = :pid"), {"pid": row["profile_id"]})
        conn.execute(text("DELETE FROM publish_accounts WHERE platform IN ('folder', 'webhook')"))
        logger.info("清理 %d 个 folder/webhook 发布账号及其空壳浏览器档案", len(rows))


def _rewrite_scene_shots_as_cameras(content: dict) -> bool:
    """把一份场景内容里的 `shots[].frames` 搬成相机物体的 `track`。改了返回 True。

    每个镜头长出一台同名的相机物体:静态位置取第一帧(没有轨的时候按它渲),`track` 就是原来
    那串 frames。镜头只留 `camera_id`。
    """
    from uuid import uuid4

    shots = content.get("shots")
    objects = content.get("objects")
    if not isinstance(shots, list) or not isinstance(objects, list):
        return False
    if not any(isinstance(shot, dict) and "frames" in shot for shot in shots):
        return False
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        frames = shot.pop("frames", None) or [{}]
        first = frames[0] if isinstance(frames[0], dict) else {}
        camera_id = uuid4().hex
        objects.append({
            "id": camera_id,
            "name": shot.get("name") or "机位",
            "kind": "camera",
            "position": first.get("position", [8, 5, 8]),
            "target": first.get("target", [0, 1, 0]),
            "fov": first.get("fov", 45),
            # 单帧的镜头是"固定机位":没有运动就不必留一条轨,静态位置已经说完了。
            "track": frames if len(frames) > 1 else [],
        })
        shot["camera_id"] = camera_id
    return True


def _migrate_scene_cameras_become_objects() -> None:
    """相机从「镜头里的一串关键帧」变成**场景里的物体**。

    此前 `shots` 和 `objects` 是两个平行数组,而整份内容里唯一带 time 的字段是
    `shots[].frames[].time` —— 于是"随时间变化"只有相机享受得到,相机自己又不是物体:
    在视口里选不中、拖不动、不能编组。见 docs/design/scene-time-and-cameras.md。

    **历史版本的快照也要一起改写。** 它们平时是原样返回的(不过校验),但"恢复某个版本"
    会把快照送回保存那条路 —— 不改写的话,升级之后所有旧版本都恢复不了,而报错会出现在
    很远的地方(一次 422,说的是 shots 缺 camera_id)。

    读取代码里不保留"老形状"这条分支(ADR-0006):迁移跑完,`shots[].frames` 就不存在了。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "scenes_3d" not in tables:
        return
    scenes = 0
    with engine.begin() as conn:
        for scene_id, raw in conn.execute(text("SELECT id, content FROM scenes_3d")).fetchall():
            try:
                content = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(content, dict) or not _rewrite_scene_shots_as_cameras(content):
                continue
            conn.execute(text("UPDATE scenes_3d SET content = :c WHERE id = :i"),
                         {"c": json.dumps(content, ensure_ascii=False), "i": scene_id})
            scenes += 1
        if "scene_3d_revisions" in tables:
            rows = conn.execute(text("SELECT scene_id, revision, snapshot FROM scene_3d_revisions")).fetchall()
            for scene_id, revision, raw in rows:
                try:
                    snapshot = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), dict):
                    continue
                if not _rewrite_scene_shots_as_cameras(snapshot["content"]):
                    continue
                conn.execute(
                    text("UPDATE scene_3d_revisions SET snapshot = :s WHERE scene_id = :i AND revision = :r"),
                    {"s": json.dumps(snapshot, ensure_ascii=False), "i": scene_id, "r": revision})
    if scenes:
        logger.info("把 %d 个 3D 场景的镜头改写成了相机物体", scenes)


def _migrate_scene_models_to_disk() -> None:
    """把 3D 模型的字节从 `scene_3d_models.data` 挪到磁盘。

    留在库里的代价是实测出来的:一份 100 MB 的模型进出一次约 400 MB 峰值 RSS、300 MB 的约
    1.6 GB —— 字节要经过 Python bytes、sqlite3 绑定、页缓存、再读回,每一步一份。而下载那条
    此前是 `Response(model.data)`,整份进内存、**每个并发请求各付一次**。

    **一行一行搬**,不要 `SELECT id, data FROM …` 一次拿完:那等于把所有模型同时读进内存,
    正是这次要消除的那个毛病。峰值因此只被最大的那一份模型限制住。

    文件落在 `media/scene-models/<workspace>/<scene>/<model>.<fmt>` —— 在 media 下面是因为
    备份打包的正是它(BACKUP_DIRECTORIES),另起顶层目录会让备份悄悄不含 3D 模型。

    搬完才 DROP 那一列:中途失败的话,下次启动重跑,已经写好的文件被原样覆盖(内容一样),
    没有半个状态。
    """
    #: 当年那一版的目录形状,**照抄在这里**:后来模型改归工作区、目录不再按场景分
    #: (见 _migrate_scene_models_to_workspace),而迁移写的是它那个年代的布局 ——
    #: 跟着 paths.py 变的话,这一步会把老数据搬到一个下一步不认识的地方。
    def legacy_slot(workspace_id: str, scene_id: str) -> Path:
        return settings.media_dir / "scene-models" / workspace_id / scene_id

    inspector = inspect(engine)
    if "scene_3d_models" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("scene_3d_models")}
    if "data" not in columns:
        return
    with engine.begin() as conn:
        for name, ddl in (("file_key", "TEXT NOT NULL DEFAULT ''"), ("size", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                conn.execute(text(f"ALTER TABLE scene_3d_models ADD COLUMN {name} {ddl}"))

    rows = [
        (row[0], row[1], row[2])
        for row in engine.connect().execute(text(
            "SELECT m.id, m.format, s.workspace_id || '/' || s.id FROM scene_3d_models m "
            "JOIN scenes_3d s ON s.id = m.scene_id"
        ))
    ]
    moved = 0
    for model_id, fmt, location in rows:
        workspace_id, _, scene_id = location.partition("/")
        with engine.connect() as conn:   # 一次一份,避免把所有模型同时读进内存
            data = conn.execute(text("SELECT data FROM scene_3d_models WHERE id = :id"), {"id": model_id}).scalar()
        if data is None:
            continue
        directory = legacy_slot(workspace_id, scene_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{model_id}.{fmt}").write_bytes(data)
        key = str(Path("media") / "scene-models" / workspace_id / scene_id / f"{model_id}.{fmt}")
        with engine.begin() as conn:
            conn.execute(text("UPDATE scene_3d_models SET file_key = :key, size = :size WHERE id = :id"),
                         {"key": key, "size": len(data), "id": model_id})
        moved += 1
        del data
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE scene_3d_models DROP COLUMN data"))
    if moved:
        logger.info("把 %d 份 3D 模型的字节从数据库挪到了 %s", moved, settings.media_dir / "scene-models")


def _migrate_scene_models_to_workspace() -> None:
    """3D 模型从「归场景」改成「归工作区」:表上的 scene_id → workspace_id,文件从
    `media/scene-models/<ws>/<scene>/` 提到 `media/scene-models/<ws>/`。

    为什么要改:模型挂在场景下面时,同一件道具在每个场景里都得重新导一份,而**工作流每跑
    一次都新建一个场景** —— 于是在 Blender 里建好的产品模型永远进不了自动成片的布景:那个
    场景还不存在,模型就没处挂。工作区才是它真正的边界(和素材、字体、LUT 一样)。

    顺序是**先搬文件再换表**:文件搬到一半崩了,下次启动重跑,已经在新位置的那些按
    "在新位置就跳过"处理,没有半个状态;表还没换,所以旧的 file_key 仍然指得到东西。

    scene 已经不在了的孤儿行跟着丢掉 —— 它们的场景没了,没有任何入口能再看到它们。
    """
    inspector = inspect(engine)
    if "scene_3d_models" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("scene_3d_models")}
    if "scene_id" not in columns:   # 已经搬过了
        return

    with engine.connect() as conn:
        rows = list(conn.execute(text(
            "SELECT m.id, m.format, m.file_key, s.workspace_id FROM scene_3d_models m "
            "JOIN scenes_3d s ON s.id = m.scene_id"
        )))
    keys: dict[str, str] = {}
    for model_id, fmt, file_key, workspace_id in rows:
        target_dir = settings.media_dir / "scene-models" / workspace_id
        target = target_dir / f"{model_id}.{fmt}"
        keys[model_id] = str(Path("media") / "scene-models" / workspace_id / f"{model_id}.{fmt}")
        if target.is_file():
            continue
        source = settings.data_dir / file_key if file_key else None
        if source is None or not source.is_file():
            continue   # 文件本来就不在了;行照样搬,界面上会说"模型文件已不在,请重新导入"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE scene_3d_models_new ("
            " id VARCHAR(64) NOT NULL PRIMARY KEY,"
            " workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,"
            " name VARCHAR(160) NOT NULL,"
            " format VARCHAR(10) NOT NULL,"
            " file_key VARCHAR(512) NOT NULL DEFAULT '',"
            " size INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text(
            "INSERT INTO scene_3d_models_new (id, workspace_id, name, format, file_key, size) "
            "SELECT m.id, s.workspace_id, m.name, m.format, m.file_key, m.size FROM scene_3d_models m "
            "JOIN scenes_3d s ON s.id = m.scene_id"
        ))
        for model_id, key in keys.items():
            conn.execute(text("UPDATE scene_3d_models_new SET file_key = :key WHERE id = :id"),
                         {"key": key, "id": model_id})
        conn.execute(text("DROP TABLE scene_3d_models"))
        conn.execute(text("ALTER TABLE scene_3d_models_new RENAME TO scene_3d_models"))
        conn.execute(text("CREATE INDEX ix_scene_3d_models_workspace_id ON scene_3d_models (workspace_id)"))

    # 空下来的按场景分的目录收掉,免得备份里留着一堆空壳。
    root = settings.media_dir / "scene-models"
    if root.is_dir():
        for workspace in root.iterdir():
            if not workspace.is_dir():
                continue
            for leftover in workspace.iterdir():
                if leftover.is_dir() and not any(leftover.iterdir()):
                    leftover.rmdir()
    if rows:
        logger.info("把 %d 份 3D 模型从「归场景」改成了「归工作区」", len(rows))


def init_db() -> None:
    """Prepare storage, then execute the validated startup migration plan."""

    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    plan = migration_plan()
    # **先问要不要拍快照,再跑。** 判据是"有没有待跑的一次性迁移",不是版本号相不相等 ——
    # 后者要人记得改一个常量,而它整整十四个迁移没被改过(见 db/safety 顶上那段)。
    snapshot_before_upgrade(
        settings.db_path, target_version=DATABASE_SCHEMA_VERSION, pending=len(plan.pending())
    )
    plan.run()
    mark_database_version(settings.db_path, DATABASE_SCHEMA_VERSION)


def _migrate_board_canvas_state() -> None:
    """Move pre-``run`` board state into the current node shape.

    Board JSON is owned data, so it is upgraded in place rather than forcing every current reader
    to understand top-level ``job_id``/``error`` forever. This historical transform intentionally
    carries its own old-shape rules instead of depending on the evolving domain validator.
    """
    inspector = inspect(engine)
    if "boards" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, canvas FROM boards")).fetchall()
        for row in rows:
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict):
                    continue
                if item.get("run") is None:
                    job_id = item.get("job_id")
                    error = item.get("error")
                    if isinstance(job_id, str) and job_id.strip():
                        item["run"] = {"status": "running", "job_id": job_id.strip()}
                        touched = True
                    elif isinstance(error, str):
                        run: dict[str, str] = {"status": "failed"}
                        if error.strip():
                            run["error"] = error.strip()[:300]
                        item["run"] = run
                        touched = True
                if item.get("form") is None and item.get("kind") in {"image", "video", "audio"}:
                    prompt = item.get("text")
                    if isinstance(prompt, str) and prompt:
                        item["form"] = {"prompt": prompt}
                        touched = True
                for legacy_key in ("job_id", "error"):
                    if legacy_key in item:
                        item.pop(legacy_key)
                        touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_trim_slots_record_their_source() -> None:
    """画板上截出来的那一格,把「截的是哪一份、哪一段」记到表单的 `trim` 上。

    此前截取只在表单里记了 `parameters: {start, end, mute}`,没记截的是哪份素材。截挂了的那一格
    于是和一格生成挂了的视频/音频长得一样:选中它挂的是生成面板,而要重截也不知道截的是哪一份。
    现在截取写的是 `form.trim = {asset_id, start, end, mute}`(见 boards.actions.trim_on_board)。

    **来历按任务认,不按参数长相猜**:截取任务的 payload 里记着原素材(`asset_id`)和回执落在哪张板
    的哪一格。找得到那一格、它表单上正是这次截取的范围,才改;任务已经被清掉的,没法知道截的是
    哪一份,原样留着(那几格要么已经有产出,要么本来就只剩一个空槽)。
    """
    tables = set(inspect(engine).get_table_names())
    if "boards" not in tables or "jobs" not in tables:
        return

    def loads(raw: Any) -> Any:
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return None

    with engine.begin() as conn:
        sources: dict[tuple[str, str], str] = {}
        for row in conn.execute(text("SELECT payload FROM jobs WHERE kind = 'trim'")).fetchall():
            payload = loads(row[0])
            receipt = payload.get("receipt") if isinstance(payload, dict) else None
            if not isinstance(receipt, dict) or receipt.get("kind") != "board_item":
                continue
            asset_id = payload.get("asset_id")
            if isinstance(asset_id, str) and asset_id and receipt.get("board_id") and receipt.get("item_id"):
                sources[(str(receipt["board_id"]), str(receipt["item_id"]))] = asset_id
        boards = {board_id for board_id, _ in sources}
        for board_id in boards:
            row = conn.execute(text("SELECT canvas FROM boards WHERE id = :id"), {"id": board_id}).fetchone()
            canvas = loads(row[0]) if row else None
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict):
                    continue
                asset_id = sources.get((board_id, str(item.get("id"))))
                form = item.get("form")
                parameters = form.get("parameters") if isinstance(form, dict) else None
                if not asset_id or not isinstance(parameters, dict) or "trim" in form:
                    continue
                start, end = parameters.get("start"), parameters.get("end")
                if not all(isinstance(one, (int, float)) and not isinstance(one, bool) for one in (start, end)):
                    continue
                rest = {key: value for key, value in parameters.items() if key not in ("start", "end", "mute")}
                trimmed = {key: value for key, value in form.items() if key != "parameters"}
                if rest:
                    trimmed["parameters"] = rest
                trimmed["trim"] = {
                    "asset_id": asset_id,
                    "start": float(start),
                    "end": float(end),
                    "mute": parameters.get("mute") is True,
                }
                item["form"] = trimmed
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": board_id},
                )


def _migrate_board_sources_record_their_upstream() -> None:
    """表单槽位里顺着连线挂上的那几份素材,记下是从哪一格来的(`from`)。

    「哪一份是从上游来的」此前只活在前端:每次画布变化拿「上一次每一格从连线拿到什么」去比,
    断开的那份才摘掉。服务端不知道这件事 —— 智能体删掉上游那一格、删掉一根线,下游表单里那份
    引用原样留着。现在出处记在那一份自己身上,由服务端一处判定(见 boards.canvas._drop_detached_bindings)。

    这里按**迁移前前端的口径**补:下游某一份的素材,正是一根连进来的线另一端那一格给出的素材
    (图片/视频/音频/3D 场景那一格上的 asset_id),就记成从那一格来的 —— 和前端当时把它当成
    「从连线来」的判据相同。连不上的照旧当手动挂的。这份口径是迁移那一刻的快照,不跟着领域层走。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    offers = {"image", "video", "audio", "scene"}
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            items = [item for item in canvas["items"] if isinstance(item, dict)]
            by_id = {str(item.get("id")): item for item in items}
            #: 每一格顺着线能拿到的素材 → 给出它的那一格(按线的先后,先连的算)。
            upstream: dict[str, dict[str, str]] = {}
            for edge in canvas.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                source = by_id.get(str(edge.get("source")))
                if not source or source.get("kind") not in offers or not source.get("asset_id"):
                    continue
                upstream.setdefault(str(edge.get("target")), {}).setdefault(str(source["asset_id"]), str(source["id"]))
            touched = False
            for item in items:
                form = item.get("form")
                sources = form.get("source_assets") if isinstance(form, dict) else None
                fed = upstream.get(str(item.get("id")))
                if not isinstance(sources, list) or not fed:
                    continue
                for one in sources:
                    if isinstance(one, dict) and "from" not in one and str(one.get("asset_id")) in fed:
                        one["from"] = fed[str(one["asset_id"])]
                        touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_frame_names_become_titles() -> None:
    """分组框的名字从 `text` 搬到每一格都有的 `title`。

    此前只有分组框能起名,名字借住在 `text` 里;现在每一格都能起名,名字统一放在 `title`
    (见 boards.canvas.normalize_canvas)。搬过去时按 title 的口径收拾:空白收成单个空格、
    首尾去掉、超过 120 字截断(这份口径是迁移那一刻的快照,不跟着领域层走)——
    不截的话,这张板下一次保存会被「名字太长」整个拒掉。搬空的(只有空白)就是没起名。
    分组框身上不再留 `text`:它没有正文。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") != "frame" or "text" not in item:
                    continue
                name = item.pop("text")
                touched = True
                if isinstance(name, str) and not item.get("title"):
                    title = " ".join(name.split())[:120]
                    if title:
                        item["title"] = title
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_forms_name_their_producer() -> None:
    """画板上每一格的表单写明是哪个产出者的(`form.producer`,ADR 0021)。

    此前挂哪块面板由前端按种类猜(boardItemState.composerFor):便签挂写字;图片/视频/音频
    还没产出时,表单上记着 trim 的挂截取,否则音频挂念字、图片视频挂生成。现在产出者是一格自己的
    事实,面板照 `form.producer` 挂,推断删掉 —— 所以已有的格子要按**当时的那条推断**写上
    (这份口径是迁移那一刻的快照,不跟着领域层走):

    · 有表单的便签/图片/视频/音频:note → write;表单上有 trim → trim;audio → speak;
      image/video → generate;
    · 没表单、但此前会挂面板的(便签;还没产出的图片/视频/音频):补一张只写着产出者的表单。

    已经写了 producer 的不动(幂等)。`producer` 排在表单最后,和服务端摆占位时写的位置一致。

    **改到的板版本号 +1**:升级那一刻还开着这张板的客户端手里是没写产出者的旧快照,它存回来
    该撞 409、拉最新的那份,而不是把刚写上的产出者整张盖掉。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    by_kind = {"note": "write", "audio": "speak", "image": "generate", "video": "generate"}
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") not in by_kind:
                    continue
                kind = item["kind"]
                form = item.get("form")
                if isinstance(form, dict):
                    if "producer" in form:
                        continue
                    producer = by_kind[kind] if kind == "note" or form.get("trim") is None else "trim"
                    item["form"] = {**form, "producer": producer}
                    touched = True
                elif form is None and (kind == "note" or not item.get("asset_id")):
                    item["form"] = {"producer": by_kind[kind]}
                    touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_empty_slots_name_their_producer() -> None:
    """升级之后新建的、还没写明产出者的空槽,补上产出者。

    `migrate-board-forms-name-their-producer` 只跑过一次;它之后,3D 场景页「拿去生成」建的画板自己拼格子,
    生成那一格带着提示词和参考却没写 `form.producer` —— 选中了什么面板都不挂。现在画布的每一次写入都由
    normalize_canvas 补齐(boards.producer_ids.missing_slot_producer),可已经存进库、之后再没存过的板不会
    经过它,所以这里按**同一条规则**补一遍(这份口径是迁移那一刻的快照,不跟着领域层走):

    · 便签、以及还没有产出(没有 asset_id)的图片/视频/音频,表单上没写 producer 的:
      note → write、audio → speak、image/video → generate(截取那一格一向由服务端写明 trim,不在此列);
    · 没有表单的就补一张只写着产出者的表单。

    已经写了 producer 的、有了产出的媒体格不动(幂等)。`producer` 排在表单最后,和 normalize 补的位置一致。
    **改到的板版本号 +1**:升级那一刻还开着这张板的客户端手里是旧快照,存回来该撞 409、拉最新的那份。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    by_kind = {"note": "write", "audio": "speak", "image": "generate", "video": "generate"}
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") not in by_kind:
                    continue
                kind = item["kind"]
                if kind != "note" and item.get("asset_id"):
                    continue
                form = item.get("form")
                if form is None:
                    form = {}
                if not isinstance(form, dict) or form.get("producer") is not None:
                    continue
                item["form"] = {**form, "producer": by_kind[kind]}
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_wiring_tools_become_notes() -> None:
    """画板上跑流程控制 / 数据处理节点的工具格,改成一张写明「这一步归工作流」的便签(ADR 0021 修订)。

    画板上只放内容变换:调用工作流、HTTP 请求、文本模板、JSON 提取、文本处理、检索笔记不再是
    画板上的工具(它们撤掉了 `surfaces: ["board"]`)。已经摆在画板上的这几种工具格,跑是跑不了了
    (注册表里没有它们,运行时回 boardErr_nodeNotOnBoard),留着就是一格永远「用不了」的死格子。

    **改成便签,不删**:
    · 同一个 id、同一个位置和大小、起过的名字照留 —— 连进来的线(上游 → 它)和它连出去的线
      (它 → 跑出来的那几格产出)都还连得上,不留一根悬空的线;便签能当上游,也能被连;
    · 它跑出来的产出(右边那几格)本来就是独立的格子,一格不动;
    · 正文写明这一步挪去了工作流,并把原来的设置(节点配置)照原样附在后面 —— 模板里写的字、
      请求的地址、检索的关键词不丢,要在工作流里重搭时照着抄。绑定(接的是哪几格上游)由保留的
      连线看得出来,不另记。
    · 挂上便签的产出者(`write`),和手放的便签一样能让 AI 改写。

    文字用部署缺省的中文(迁移时没有请求,也就没有读的人的语言,见 core/i18n 开头那段);节点名
    和那句话是迁移那一刻的快照,不跟着领域层走。插件工具不在这里:它合不合格随清单变(连接、
    ComfyUI 上的工作流),运行时由注册表说清楚为什么(boardErr_toolNotOnBoard)。

    改到的板版本号 +1:升级那一刻还开着这张板的客户端,手里的旧快照要撞 409,不能把工具格存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    labels = {
        "node:call_workflow": "调用工作流",
        "node:http_request": "HTTP 请求",
        "node:template": "文本模板",
        "node:json_extract": "JSON 提取",
        "node:text_transform": "文本处理",
        "node:note_search": "检索笔记",
    }
    limit = 20_000
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for index, item in enumerate(canvas["items"]):
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                label = labels.get(str(form.get("producer") or ""))
                if label is None:
                    continue
                body = f"「{label}」这一步已经不在画板上了:画板只放把内容变成新内容的工具,流程控制和数据处理归工作流 —— 需要的话在工作流里用它。"
                config = form.get("config")
                if isinstance(config, dict) and config:
                    body += "\n\n原来的设置:\n" + json.dumps(config, ensure_ascii=False, indent=2)
                if len(body) > limit:
                    body = body[: limit - 1] + "…"
                note = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
                canvas["items"][index] = {**note, "kind": "note", "text": body, "form": {"producer": "write"}}
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_scene_render_shot_is_picked() -> None:
    """画板上「渲染白模参考」的镜头和项目不再接便签 / 文档,改成从清单里挑。

    这两格此前是随手写字的模板字段,于是能接便签和文档的字(画板的 binding_sink 按「能写字」判)——
    必填的镜头还会**默认接上第一张连进来的便签**。现在它们声明了选项来源(场景的镜头、工作区的
    项目),不再是写字的地方:存着的这种绑定运行时一律不认(tools.resolve_bindings 跳过接不了的字段),
    面板上却还显示成「已接上游」,点开是一排接不上的空芯片。

    · 绑定摘掉(只摘这两格,别的字段、连线一概不动);
    · 镜头绑的是便签、表单里又没手填过镜头的,把便签上那段字(去掉两头空白)填进表单 ——
      那正是上次运行时它取到的值,摘了绑定照样渲同一个镜头。文档的正文当不了镜头 id,不搬;
      项目也不搬(接便签的项目本来就填不对,留空 = 不归档)。

    改到的板版本号 +1:升级那一刻还开着这张板的客户端要撞 409,不能把旧绑定存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    fields = ("shot_id", "project_id")
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            items = {str(item.get("id")): item for item in canvas["items"] if isinstance(item, dict)}
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                form = item.get("form")
                if not isinstance(form, dict) or form.get("producer") != "node:scene_render":
                    continue
                bindings = form.get("bindings")
                if not isinstance(bindings, dict) or not any(key in bindings for key in fields):
                    continue
                config = dict(form.get("config")) if isinstance(form.get("config"), dict) else {}
                refs = bindings.get("shot_id") if isinstance(bindings.get("shot_id"), list) else []
                if not str(config.get("shot_id") or "").strip():
                    for ref in refs:
                        source = items.get(str(ref.get("from") if isinstance(ref, dict) else ""))
                        written = str((source or {}).get("text") or "").strip() if (source or {}).get("kind") == "note" else ""
                        if written:
                            config["shot_id"] = written
                            break
                item["form"] = {
                    **form,
                    "config": config,
                    "bindings": {key: value for key, value in bindings.items() if key not in fields},
                }
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_scene_cells_render_themselves() -> None:
    """画板上渲白模改成 3D 场景格自己做的事,「渲染白模参考」工具格撤掉。

    此前一格场景格(引用一个场景、导出缩略图)旁边还要放一格工具格(`node:scene_render`),在工具格上挑
    场景、挑镜头、挑渲什么 —— 同一件事分成两半摆在桌上。现在场景格挂内置产出者 `scene_render`
    (和视频 / 音频格上的「剪一段」同一个样子),工作流节点撤掉了 `surfaces: ["board"]`。存着的画布:

    · **每一格场景格写明产出者** `scene_render`(面板照它挂;新放下的场景格由 normalize 补,见
      producer_ids.SLOT_PRODUCERS)。
    · 工具格的场景**接的是**(绑定、且那根线还在)或**填的是**这张板上某一格场景格的场景:它的设置(镜头、
      渲什么、归档项目;`{{…}}` 引用、不在选项里的值不搬)写进那一格场景格的 `form.config`,工具格删掉。
      它跑出来的产出一格不动,**连向产出的线改从场景格连出**(同一对已经连着就不再多一根);连进工具格的线
      随它去掉。一格场景格被好几格工具格接着时,第一格的设置搬过去;后面设置不同的那几格照下一条改成便签
      (它们的镜头选择不能悄悄丢)。
    · 其余(没接、没填,或填的场景这张板上没有格子):**改成一张便签**,同一个 id、位置、大小、名字,正文
      写明渲染挪到了场景格上并附上原来的设置 —— 和 `migrate-board-wiring-tools-become-notes` 同一种做法:
      进出它的线都还连得上,产出不动。

    文字用部署缺省的中文(迁移时没有读的人的语言)。改到的板版本号 +1:升级那一刻还开着这张板的客户端
    手里的旧快照要撞 409,不能把工具格存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    fields = ("shot_id", "render", "project_id")
    renders = ("stills", "video", "both")
    limit = 20_000

    def settings_of(config: dict) -> dict:
        out = {}
        for key in fields:
            value = config.get(key)
            if not isinstance(value, str) or not value.strip() or "{{" in value:
                continue
            if key == "render" and value.strip() not in renders:
                continue
            out[key] = value.strip()
        return out

    def note_of(item: dict, config: dict) -> dict:
        body = ("「渲染白模参考」这一格不在画板上了:渲白模现在是 3D 场景格自己会做的事 —— 把场景放上画板,"
                "选中它,挑一个镜头就能渲出首尾帧或运镜视频。")
        if config:
            body += "\n\n原来的设置:\n" + json.dumps(config, ensure_ascii=False, indent=2)
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        kept = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
        return {**kept, "kind": "note", "text": body, "form": {"producer": "write"}}

    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            items = [item for item in canvas["items"] if isinstance(item, dict)]
            edges = [edge for edge in canvas.get("edges") or [] if isinstance(edge, dict)]
            by_id = {str(item.get("id")): item for item in items}
            wired = {(str(edge.get("source")), str(edge.get("target"))) for edge in edges}
            scenes = [item for item in items if item.get("kind") == "scene"]
            touched = False

            for scene in scenes:
                form = scene.get("form") if isinstance(scene.get("form"), dict) else {}
                if not form.get("producer"):
                    scene["form"] = {**form, "producer": "scene_render"}
                    touched = True

            moved: dict[str, str] = {}
            filled: set[str] = set()
            for index, item in enumerate(canvas["items"]):
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                if form.get("producer") != "node:scene_render":
                    continue
                touched = True
                item_id = str(item.get("id"))
                config = form.get("config") if isinstance(form.get("config"), dict) else {}
                bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
                host = None
                for ref in bindings.get("scene_id") if isinstance(bindings.get("scene_id"), list) else []:
                    source = str(ref.get("from") if isinstance(ref, dict) else "")
                    if (by_id.get(source) or {}).get("kind") == "scene" and (source, item_id) in wired:
                        host = by_id[source]
                        break
                wanted = config.get("scene_id")
                if host is None and isinstance(wanted, str) and wanted.strip():
                    host = next((one for one in scenes if one.get("scene_id") == wanted.strip()), None)
                settings = settings_of(config)
                if host is not None:
                    host_id = str(host.get("id"))
                    host_form = host.get("form") if isinstance(host.get("form"), dict) else {}
                    current = host_form.get("config") if isinstance(host_form.get("config"), dict) else {}
                    if host_id not in filled and not current:
                        rest = {key: value for key, value in host_form.items() if key not in ("config", "producer")}
                        host["form"] = {**rest, **({"config": settings} if settings else {}), "producer": "scene_render"}
                        filled.add(host_id)
                        moved[item_id] = host_id
                        continue
                    if settings == current or (not settings and not current):
                        moved[item_id] = host_id
                        continue
                canvas["items"][index] = note_of(item, config)

            if moved:
                taken = {str(edge.get("id")) for edge in edges}
                pairs = {(str(edge.get("source")), str(edge.get("target"))) for edge in edges}
                kept_edges = []
                for edge in edges:
                    source, target = str(edge.get("source")), str(edge.get("target"))
                    if target in moved:
                        continue
                    if source not in moved:
                        kept_edges.append(edge)
                        continue
                    host_id = moved[source]
                    if target == host_id or target in moved or (host_id, target) in pairs:
                        continue
                    edge_id = f"{host_id}->{target}"
                    suffix = 1
                    while edge_id in taken:
                        suffix += 1
                        edge_id = f"{host_id}->{target}-{suffix}"
                    taken.add(edge_id)
                    pairs.add((host_id, target))
                    kept_edges.append({**edge, "id": edge_id, "source": host_id})
                canvas["edges"] = kept_edges
                canvas["items"] = [item for item in canvas["items"]
                                   if not (isinstance(item, dict) and str(item.get("id")) in moved)]
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_tool_cells_become_abilities() -> None:
    """画板上不再有单独的工具格(`action`):把内容变成新内容的工具是**内容格自己的能力**,凭空出图出片的生成器是
    **空格子的一种填法**(ADR 0025 修订「能力住在内容格上」,和「剪一段」挂在视频 / 音频格上、3D 场景格自己渲白模
    同一个样子)。存着的每一格工具格:

    · 工具声明了和某个生成模型是同一件事(`mirrors`)、连接的主人用得上那个模型:改成那种素材的**生成**空格子,
      和对账对空格子上的生成器做的是同一件事(boards.plugin_references 的「被生成取代的生成器」)。
    · 工具是一项**能力**(按它此刻的声明,boards.transforms.board_role),它吃内容的那个字段**接着**(绑定、且那根线
      还在)或**填的是**(素材 id / 场景 id 对得上)这张板上一格收得下它的内容格:设置(去掉宿主那个字段 —— 它就是
      宿主)写进那一格的 `form.abilities[产出者]`,工具格删掉。它跑出来的产出一格不动,**连向产出的线改从宿主连出**;
      接着别的字段的上游(多输入的工具)改连进宿主,绑定照留;连进工具格的别的线随它去掉。
    · 工具是一个**生成器**(不吃画板内容,按参数出一种素材):同一个 id、位置、大小、名字,改成它产出的那种素材的
      **空格子**,`form.producer` 就是它,设置和绑定照留(接提示词的便签线还在)。
    · 其余 —— 工具此刻认不出(插件卸了、没有哪条连接报得出它)、不再是内容变换、能力找不到宿主、宿主上已经存着
      这一项的另一套设置:**改成一张便签**,同一个 id、位置、大小、名字,正文写明工具现在挂在内容格上并附上原来的
      设置,和 `migrate-board-wiring-tools-become-notes` 同一种做法 —— 进出它的线都还连得上,产出不动。

    **判法读工具的声明**:内置节点读 NODE_TYPES,插件工具读每条连接报出的清单(plugins.tools.all_tools:清单里声明的
    加缓存的动态工具,不连网)—— 所以排在装好随包插件、对账之后。之后插件的清单再变,存下的是能力 / 生成器的名字和
    设置:注册表每次现算,改名由对账(rewrite-replaced-plugin-tools)跟上;工具格不会再出现,这一步只要一次。

    运行态不带(升级那一刻在跑的任务随进程没了)。文字用部署缺省的中文(迁移时没有读的人的语言)。改到的板版本号
    +1:升级那一刻还开着这张板的客户端手里的旧快照要撞 409,不能把工具格存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    from sqlalchemy.orm import Session

    from app.core.i18n import t
    from app.domain.boards.plugin_references import as_generation_slot, mirrors
    from app.domain.boards.transforms import ABILITY, board_hosts, board_role, content_transform_gap, host_fields
    from app.domain.workflows import NODE_TYPES

    limit = 20_000
    kind_names = {"note": "便签", "document": "文档", "image": "图片", "video": "视频", "audio": "音频", "scene": "3D 场景"}
    plugins_known = "plugin_instances" in set(inspect(engine).get_table_names())

    def tool_meta(db: Session, producer: str) -> tuple[dict | None, str]:
        """(声明, 名字)。声明认不出、或不是画板上的内容变换时声明是 None。"""
        node_type = producer[len("node:"):] if producer.startswith("node:") else ""
        if not node_type:
            return None, producer
        if not node_type.startswith("plugin."):
            meta = NODE_TYPES.get(node_type)
            label = t(str(meta.get("label") or node_type), "zh") if meta else node_type
            if meta is None or "board" not in (meta.get("surfaces") or ()) or content_transform_gap(meta) is not None:
                return None, label
            return meta, label
        if not plugins_known:
            return None, node_type
        from app.db.models import PluginInstance
        from app.domain.plugins.errors import PluginDomainError
        from app.domain.plugins.nodes import node_meta, parse_node_type
        from app.domain.plugins.tools import all_tools

        parsed = parse_node_type(node_type)
        if parsed is None:
            return None, node_type
        package_id, tool_name = parsed
        for instance in db.query(PluginInstance).filter(PluginInstance.package_id == package_id):
            try:
                tools = all_tools(db, instance)
            except PluginDomainError:
                continue
            for tool in tools:
                if tool.get("name") != tool_name:
                    continue
                label = str(tool.get("label") or tool_name)
                meta = node_meta({**tool, "package_id": package_id})
                if tool.get("internal") or content_transform_gap(meta) is not None:
                    return None, label
                return meta, label
        return None, tool_name

    def note_of(item: dict, label: str, config: dict, why: str) -> dict:
        body = f"「{label}」这一格不在画板上了:{why}"
        #: 选的连接是本机事实(一串 id),不抄进正文。
        config = {key: value for key, value in config.items() if key != "instance_id"}
        if config:
            body += "\n\n原来的设置:\n" + json.dumps(config, ensure_ascii=False, indent=2)
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        kept = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
        return {**kept, "kind": "note", "text": body, "form": {"producer": "write"}}

    retired = "画板只放把内容变成新内容的工具,它们现在是内容格自己会做的事 —— 需要的话在工作流里用它。"

    def fresh_id(taken: set[str], source: str, target: str) -> str:
        edge_id = f"{source}->{target}"
        suffix = 1
        while edge_id in taken:
            suffix += 1
            edge_id = f"{source}->{target}-{suffix}"
        taken.add(edge_id)
        return edge_id

    def ability_note(label: str, kinds: tuple[str, ...]) -> str:
        names = "、".join(kind_names.get(kind, kind) for kind in kinds) or "内容"
        return (f"它现在是{names}格子自己会做的事 —— 选中一格,在它上方的操作条里点「{label}」。"
                "这一格原来没接着能用的内容,所以改成了这张便签。")

    with Session(engine) as db:
        mirrored = mirrors(db) if plugins_known else []
        for row in db.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            if not any(isinstance(item, dict) and item.get("kind") == "action" for item in canvas["items"]):
                continue
            items = canvas["items"]
            edges = [edge for edge in canvas.get("edges") or [] if isinstance(edge, dict)]
            by_id = {str(item.get("id")): item for item in items if isinstance(item, dict)}
            wired = {(str(edge.get("source")), str(edge.get("target"))) for edge in edges}
            #: 工具格 id → (宿主 id, 改连进宿主的那几格上游)。
            moved: dict[str, tuple[str, set[str]]] = {}
            for index, item in enumerate(items):
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                item_id = str(item.get("id"))
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                producer = str(form.get("producer") or "")
                config = dict(form.get("config") or {}) if isinstance(form.get("config"), dict) else {}
                bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
                as_generation = as_generation_slot({**item, "run": {}}, by_id, mirrored, any_kind=True) if mirrored else None
                if as_generation is not None:
                    items[index] = as_generation
                    continue
                meta, label = tool_meta(db, producer)
                if meta is None:
                    items[index] = note_of(item, label, config, retired)
                    continue
                if board_role(meta) != ABILITY:
                    #: 生成器:改成它产出的那种素材的空格子,设置照留。
                    kind = board_hosts(meta)[0]
                    kept = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
                    items[index] = {**kept, "kind": kind,
                                    "form": {"config": config, "bindings": bindings, "producer": producer}}
                    continue
                fields = host_fields(meta)
                host = None
                for field in dict.fromkeys(fields.values()):
                    for ref in bindings.get(field) or []:
                        source = str(ref.get("from") if isinstance(ref, dict) else "")
                        candidate = by_id.get(source)
                        if candidate is not None and fields.get(str(candidate.get("kind"))) == field \
                                and (source, item_id) in wired:
                            host = candidate
                            break
                    if host is None and isinstance(config.get(field), str) and config[field].strip():
                        wanted = config[field].strip()
                        host = next((one for one in by_id.values() if fields.get(str(one.get("kind"))) == field
                                     and wanted in (one.get("asset_id"), one.get("scene_id"))), None)
                    if host is not None:
                        break
                if host is None:
                    items[index] = note_of(item, label, config, ability_note(label, tuple(fields)))
                    continue
                host_id = str(host.get("id"))
                host_key = fields[str(host.get("kind"))]
                others = {
                    field: [ref for ref in refs if isinstance(ref, dict)
                            and str(ref.get("from")) not in (host_id, item_id)
                            and (str(ref.get("from")), item_id) in wired]
                    for field, refs in bindings.items() if field != host_key and isinstance(refs, list)
                }
                others = {field: refs for field, refs in others.items() if refs}
                entry = {"config": {key: value for key, value in config.items() if key != host_key},
                         "bindings": others}
                host_form = dict(host.get("form") or {}) if isinstance(host.get("form"), dict) else {}
                abilities = dict(host_form.get("abilities") or {})
                if producer in abilities and abilities[producer] != entry:
                    items[index] = note_of(item, label, config,
                                           f"它现在是{kind_names.get(str(host.get('kind')), '内容')}格子自己会做的事,"
                                           f"而「{host_id}」上已经存着这一项的另一套设置 —— 这一套附在下面。")
                    continue
                abilities[producer] = entry
                own = host_form.pop("producer", None)
                host_form.pop("abilities", None)
                host["form"] = {**host_form, "abilities": abilities, **({"producer": own} if own is not None else {})}
                moved[item_id] = (host_id, {str(ref["from"]) for refs in others.values() for ref in refs})

            if moved:
                taken = {str(edge.get("id")) for edge in edges}
                pairs = {(str(edge.get("source")), str(edge.get("target"))) for edge in edges}
                kept_edges = []
                for edge in edges:
                    source, target = str(edge.get("source")), str(edge.get("target"))
                    if source in moved and target in moved:
                        continue
                    if target in moved:
                        host_id, upstream = moved[target]
                        if source in upstream and source != host_id and (source, host_id) not in pairs:
                            pairs.add((source, host_id))
                            kept_edges.append({**edge, "id": fresh_id(taken, source, host_id), "target": host_id})
                        continue
                    if source in moved:
                        host_id = moved[source][0]
                        if target != host_id and (host_id, target) not in pairs:
                            pairs.add((host_id, target))
                            kept_edges.append({**edge, "id": fresh_id(taken, host_id, target), "source": host_id})
                        continue
                    kept_edges.append(edge)
                canvas["edges"] = kept_edges
                canvas["items"] = [item for item in items
                                   if not (isinstance(item, dict) and str(item.get("id")) in moved)]
            db.execute(
                text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
            )
        db.commit()


def _migrate_board_revision() -> None:
    """Add the optimistic concurrency token to existing boards.

    ``create_all`` creates it for new databases but cannot alter an existing table. Existing
    projections all start at revision 1; the first accepted write advances them to 2.
    """

    inspector = inspect(engine)
    if "boards" not in set(inspector.get_table_names()):
        return
    if "revision" in {column["name"] for column in inspector.get_columns("boards")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE boards ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"))


def _migrate_confirmation_summary_i18n() -> None:
    """已装机的库补上 `tool_confirmations.summary_key` / `summary_params`。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 少了这一步,新装机一切正常,
    升级的机器上后端起不来(no such column)。

    **存量卡不回填。** 它们的 `summary` 就是当时那句话,而当时那句话是中文写死的 —— 没有
    key 可以反推。出口见到 key 为空就原样返回它(和 `JobOut` 对老任务的处理一字不差:
    历史记录保持它当时的原话,而从此以后新写的都是 key)。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("tool_confirmations")}
    with engine.begin() as conn:
        if "summary_key" not in columns:
            conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN summary_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "summary_params" not in columns:
            conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN summary_params JSON NOT NULL DEFAULT '{}'"))


def _migrate_publish_task_claimed_by() -> None:
    """已装机的库补上 publish_tasks.claimed_by。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 少了这一步,新装机一切正常,
    升级的机器上后端起不来(no such column)。
    """

    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("publish_tasks")}
    if "claimed_by" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN claimed_by VARCHAR(64) NOT NULL DEFAULT ''"))


def _migrate_publish_task_post() -> None:
    """已装机的库补上 publish_tasks.post(发出去的那条作品的平台 ID 与链接)。

    `create_all` 只建缺失的**表**,从不给已存在的表加列。老任务发的时候没记,这一列就是空 dict ——
    那些作品的 ID 当时没抓,事后补不出来,不假装有。
    """

    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("publish_tasks")}
    if "post" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN post JSON NOT NULL DEFAULT '{}'"))


def _migrate_agent_pending_view() -> None:
    """已装机的库补上 agent_sessions.pending_view。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 少了这一步,新装机一切正常,
    升级的机器上后端起不来(no such column)。
    """

    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("agent_sessions")}
    if "pending_view" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN pending_view VARCHAR(96) NOT NULL DEFAULT ''"))


def _migrate_comment_canvas_context() -> None:
    """Preserve spatial anchors and rich-text documents for existing comment tables."""

    inspector = inspect(engine)
    if "comments" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("comments")}
    with engine.begin() as conn:
        if "anchor" not in columns:
            conn.execute(text("ALTER TABLE comments ADD COLUMN anchor JSON NOT NULL DEFAULT '{}'"))
        if "body_document" not in columns:
            conn.execute(text("ALTER TABLE comments ADD COLUMN body_document JSON NOT NULL DEFAULT '{}'"))


def _backfill_activity_events() -> None:
    """Project existing actor-bearing history into the unified workspace activity stream.

    The source pair is unique, so startup remains idempotent. The original rows stay authoritative
    for workflow replay, sequence undo and job execution; ActivityEvent is their human-facing audit
    projection, not a replacement for domain history.
    """

    tables = set(inspect(engine).get_table_names())
    if "activity_events" not in tables:
        return
    with engine.begin() as conn:
        if {"workflows", "workflow_revisions"}.issubset(tables):
            conn.execute(
                text(
                    """
                    INSERT INTO activity_events
                        (id, workspace_id, actor_id, action, subject_type, subject_id, summary,
                         payload, source_type, source_id, created_at)
                    SELECT lower(hex(randomblob(16))), w.workspace_id, r.created_by,
                           'workflow.revision_created', 'workflow', r.workflow_id,
                           CASE WHEN r.source = 'restore' THEN '恢复了工作流版本' ELSE '保存了工作流版本' END,
                           json_object('revision', r.revision, 'source', r.source),
                           'workflow_revision', r.id, r.created_at
                    FROM workflow_revisions r JOIN workflows w ON w.id = r.workflow_id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_events e
                        WHERE e.source_type = 'workflow_revision' AND e.source_id = r.id
                    )
                    """
                )
            )
        if "sequence_operations" in tables:
            conn.execute(
                text(
                    """
                    INSERT INTO activity_events
                        (id, workspace_id, actor_id, action, subject_type, subject_id, summary,
                         payload, source_type, source_id, created_at)
                    SELECT lower(hex(randomblob(16))), o.workspace_id, o.actor_id,
                           'sequence.operation', 'sequence', o.sequence_id, '编辑了时间线',
                           json_object('kind', o.kind, 'revision_before', o.revision_before,
                                       'revision_after', o.revision_after),
                           'sequence_operation', o.id, o.created_at
                    FROM sequence_operations o
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_events e
                        WHERE e.source_type = 'sequence_operation' AND e.source_id = o.id
                    )
                    """
                )
            )
        if "jobs" in tables:
            conn.execute(
                text(
                    """
                    INSERT INTO activity_events
                        (id, workspace_id, actor_id, action, subject_type, subject_id, summary,
                         payload, source_type, source_id, created_at)
                    SELECT lower(hex(randomblob(16))), j.workspace_id, j.created_by,
                           'job.created', 'job', j.id, '发起了任务',
                           json_object('kind', j.kind, 'status', j.status),
                           'job', j.id, j.created_at
                    FROM jobs j
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_events e
                        WHERE e.source_type = 'job' AND e.source_id = j.id
                    )
                    """
                )
            )


def _migrate_shared_venvs() -> None:
    """一个引擎一个运行环境。分开之前那个共用 venv 搬到它实际服务的引擎名下 —— 不留兼容路径,
    因为"一个环境被两个引擎装东西"正是「装一边弄坏另一边」的机制本身。"""

    # **在函数里 import,不在模块顶层。** 这两个迁移动作住在被迁移的那一侧(venv 归运行时管),
    # 而 db 是比它们更底的一层 —— 顶层 import 会让"加载一个迁移模块"连带拉起半个应用
    # (实测:app.ai / app.ai.runtime / app.domain / app.domain.voices 全被带起来)。
    # 迁移只在 init_db 那一刻跑一次,它对上层的需要是**运行时的**,不该固化成加载时的绑定。
    from app.ai.runtime import asr_models, config as tts_config

    tts_config.migrate_shared_venv()
    asr_models.migrate_shared_venv()


def _migrate_thumbnails_keep_transparency() -> None:
    """缩略图从 JPEG 换成 WebP(JPEG 没有透明通道,透明 PNG 的缩略图四角发黑、边缘起毛)。

    逐个素材换掉旧文件;做法住在 media/thumbnails(同 _migrate_shared_venvs 的理由,函数内 import)。
    """
    from app.media.paths import resolve_key
    from app.media.thumbnails import migrate_jpeg_thumbnail

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT kind, file_key FROM assets WHERE file_key IS NOT NULL AND file_key != ''")).all()
    for kind, file_key in rows:
        source = resolve_key(file_key)
        migrate_jpeg_thumbnail(source, kind, source.parent)


def _migrate_mov_videos_become_mp4() -> None:
    """已经在库里的 .mov 视频原样换成 .mp4 容器(不重编码),与导入时的做法一致。

    为什么换见 media/probe.repackage_as_mp4:QuickTime 容器在界面里拖进度条会卡好几秒。
    文件换好了才改行;换好了但行还没改(上次中途断了)时,下次看到同名 .mp4 就只改行。
    """
    from app.media.paths import resolve_key
    from app.media.probe import REPACKAGED_SUFFIXES, repackage_as_mp4

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, original_filename, file_key FROM assets WHERE kind = 'video' AND file_key != ''")
        ).all()
    for asset_id, name, original, file_key in rows:
        key = Path(file_key)
        if key.suffix.lower() not in REPACKAGED_SUFFIXES:
            continue
        source = resolve_key(file_key)
        target = source.with_suffix(".mp4")
        if source.is_file() and repackage_as_mp4(source) is None:
            continue  # 编码放不进 mp4(ProRes 之类):留着 .mov
        if not target.is_file():
            continue
        renamed = str(Path(original or key.name).with_suffix(".mp4"))
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE assets SET file_key = :key, original_filename = :original, name = :name WHERE id = :id"),
                {
                    "key": str(key.with_suffix(".mp4")),
                    "original": renamed,
                    # 名字还是默认的文件名时一起换;用户改过的名字不动。
                    "name": renamed if name == original else name,
                    "id": asset_id,
                },
            )


def _migrate_documents_are_not_videos() -> None:
    """此前认不出的文件一律当成视频入库(ADR 0031):按扩展名是文档的,改回 `document`。

    media_info 换成文档那一份(格式、大小 —— 页数、封面等解析时写);当视频探出来的时长、帧率本来就是空的或瞎编的。
    视频那一侧留下的派生文件(ffmpeg 取不出帧,一般没有)不动 —— 文档不读它们。
    """
    from app.media.paths import resolve_key
    from app.media.probe import DOCUMENT_EXTENSIONS

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, original_filename, file_key FROM assets WHERE kind = 'video' AND file_key != ''")
        ).all()
    for asset_id, original, file_key in rows:
        suffix = Path(original or file_key).suffix.lower()
        if suffix not in DOCUMENT_EXTENSIONS:
            continue
        path = resolve_key(file_key)
        info = {"format": suffix.lstrip("."), **({"size_bytes": path.stat().st_size} if path.is_file() else {})}
        with engine.begin() as conn:
            conn.execute(text("UPDATE assets SET kind = 'document', media_info = :info WHERE id = :id"),
                         {"info": json.dumps(info), "id": asset_id})


def _migrate_frame_rate_is_not_a_time_base() -> None:
    """浏览器录的 webm 以毫秒计时,此前探测把 1000/1 当成了帧率(素材详情写着「1000fps」)。

    帧率超过 media/probe.MAX_PLAUSIBLE_FPS 的视频按现在的探测重算一遍;重算不出来就去掉这个值,
    界面上不显示比显示一个错的好。
    """
    from app.media.paths import resolve_key
    from app.media.probe import MAX_PLAUSIBLE_FPS, probe_media

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, file_key, media_info FROM assets WHERE kind = 'video' AND file_key != ''")).all()
    for asset_id, file_key, raw in rows:
        info = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        fps = info.get("fps")
        if not isinstance(fps, (int, float)) or fps <= MAX_PLAUSIBLE_FPS:
            continue
        source = resolve_key(file_key)
        fixed = probe_media(source).get("fps") if source.is_file() else None
        if fixed is None:
            info.pop("fps", None)
        else:
            info["fps"] = fixed
        with engine.begin() as conn:
            conn.execute(text("UPDATE assets SET media_info = :info WHERE id = :id"),
                         {"info": json.dumps(info, ensure_ascii=False), "id": asset_id})


def _drop_venvs_built_on_another_python() -> None:
    """托管 venv 是用另一个次版本的解释器建的,就删掉,让引擎回到「未安装」。

    随包的解释器会随应用升级换次版本(这一次是 3.12 → 3.13),而 venv 不能跨次版本用 —— 留着它,
    引擎看起来「装好了」却一跑就炸。这是**对账**不是一次性迁移:下一次换次版本时同样的事会
    再发生,判据(venv 的版本 ≠ 现在建 venv 用的解释器的版本)也不随哪一次升级而变。
    """
    from app.ai.runtime import asr_models, config as tts_config, separation_models
    from app.core.interpreter import drop_venvs_built_on_another_python

    for venv in drop_venvs_built_on_another_python((
        tts_config.MANAGED_TTS_ROOT, asr_models.MANAGED_ASR_ROOT, separation_models.MANAGED_SEPARATION_ROOT,
    )):
        logger.info("删掉用另一个 Python 次版本建的托管运行环境,用到时按现在的解释器重装:%s", venv)


def _migrate_browser_boolean_options() -> None:
    """三个浏览器节点的是非选项从「否 / 是」迁成「false / true」。

    选项**值**会原样存进图里,也会原样显示在下拉框上 —— 目录里其余选项一律是中性标识符
    (`true` `GET` `image` `precise`),只有这三处写的是中文,于是英文界面上那三个下拉框
    永远是「否 / 是」,而且没有任何出口能把它翻掉:那是值,不是文案。

    值本身改掉之后,库里已有的图还留着旧值 —— 在这里迁,而不是让读取端认两套。
    **对里写死**是有意的:迁移是历史的快照,不该跟着后面还会变的目录走。
    """
    inspector = inspect(engine)
    if "workflows" not in set(inspector.get_table_names()):
        return
    pairs = {("browser_click", "exact"), ("browser_extract", "all"), ("browser_wait", "gone")}

    def fix(graph: Any) -> bool:
        """→ 改动过没有。子图(循环体 / 子流程)也要走进去。"""
        touched = False
        if not isinstance(graph, dict):
            return False
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            config = node.get("config")
            if not isinstance(config, dict):
                continue
            for field in [key for key in config if (node.get("type"), key) in pairs]:
                if config[field] in ("是", "否"):
                    config[field] = "true" if config[field] == "是" else "false"
                    touched = True
            for value in config.values():
                if isinstance(value, dict) and value.get("nodes") is not None:
                    touched = fix(value) or touched

        return touched

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).fetchall()
        for row in rows:
            try:
                graph = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if fix(graph):
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(graph, ensure_ascii=False), "id": row[0]},
                )


def _migrate_comfyui_connections_become_plugin_instances() -> None:
    """ComfyUI 从内核供应商搬成随应用发的插件(ADR 0020):每条 `comfyui` 连接 → 同一个人的 ComfyUI
    插件实例,**连接原地改成插件连接**,存着的引用改成新写法。

    **连接 id 不变**,于是模型行、默认模型、生成历史、用量、定价这些挂在连接上的外键一个都不用动。
    连接上的地址和粘贴的模板搬进实例配置(`server_url` / `api_workflow`),`network:comfyui` 直接授予
    —— 他早就配过这台服务器,升级不该让他再点一次。

    模型与引用的新写法(和插件目录说的是同一套 id):

    - 选过 ComfyUI 里保存的工作流(`parameters.workflow` = 路径)→ **那个工作流就是模型**,
      动态参数表 `workflow_params: {节点: {输入: 值}}` 拍平成 `<节点>.<输入>`;
    - 假模型 `workflow`:连接粘过模板的 → `api-workflow`;没粘的图像 → `builtin:txt2img`(内置文生图);
      没粘模板的视频原来就跑不了(没有内置视频图),**保持原样**,运行时明确报「这个模型不可用」;
    - 指向旧目录档案的参数声明(`comfyui-image` / `comfyui-video` / `model:comfyui/workflow`)和这些连接上
      的参数模板删掉:那是对旧 Adapter 的断言,插件连接的参数由插件目录说。

    改写的地方:生成任务与任务表里的回执、产出记录、用量与定价、生成会话、定时任务、画板上的生成格、
    工作流(连同循环体 / 子图;改过的追加一版修订,作者和认可人沿用上一版 —— 机械改写不换担保人)。
    引用到的模型行不在就补上,插件目录刷新时再对齐。

    幂等:第二次跑时已经没有 `comfyui` 连接、也没有 `comfyui` 的引用。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"provider_profiles", "provider_models", "plugin_instances", "plugin_packages"} <= tables:
        return
    package_id = "dev.mosael.comfyui"
    vendor = f"plugin:{package_id}"
    obsolete_refs = ("profile:comfyui-image", "profile:comfyui-video", "model:comfyui/workflow")

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    # 和 SQLAlchemy 的 DateTime 在 SQLite 里存的是同一种写法;直接传 datetime 走的是已弃用的默认适配器。
    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    with engine.begin() as conn:
        profiles = conn.execute(text(
            "SELECT id, owner_user_id, name, base_url, extra, enabled FROM provider_profiles WHERE vendor = 'comfyui'"
        )).mappings().all()
        if profiles and conn.execute(text("SELECT 1 FROM plugin_packages WHERE id = :id"), {"id": package_id}).first() is None:
            raise RuntimeError("the bundled ComfyUI plugin is not installed; ComfyUI connections cannot be migrated yet")

        #: 这次搬过的连接 → 它有没有粘过模板(决定假模型 `workflow` 改成什么)。
        templated: dict[str, bool] = {}
        for profile in profiles:
            extra = loads(profile["extra"], {}) or {}
            template = str(extra.get("workflow_template") or "").strip()
            templated[profile["id"]] = bool(template)
            instance_id = uuid.uuid4().hex
            config = {"server_url": (profile["base_url"] or "").strip() or "http://127.0.0.1:8188", "api_workflow": template}
            conn.execute(
                text(
                    "INSERT INTO plugin_instances (id, owner_user_id, package_id, name, enabled, config,"
                    " discovered_tools, capability_status, created_at, updated_at)"
                    " VALUES (:id, :owner, :package, :name, :enabled, :config, '[]', '{}', :now, :now)"
                ),
                {"id": instance_id, "owner": profile["owner_user_id"] or "", "package": package_id,
                 "name": profile["name"], "enabled": int(bool(profile["enabled"])), "config": dumps(config), "now": stamp},
            )
            conn.execute(
                text(
                    "INSERT INTO plugin_permission_grants (instance_id, permission, granted, created_at, updated_at)"
                    " VALUES (:id, 'network:comfyui', 1, :now, :now)"
                ),
                {"id": instance_id, "now": stamp},
            )
            conn.execute(
                text(
                    "UPDATE provider_profiles SET vendor = :vendor, plugin_instance_id = :instance, base_url = '',"
                    " extra = '{}' WHERE id = :id"
                ),
                {"vendor": vendor, "instance": instance_id, "id": profile["id"]},
            )
            # 免密钥的连接不该有钥匙行;有的话(随手敲过几个字骗过旧判据)也没有任何意义了。
            conn.execute(text("DELETE FROM provider_credentials WHERE profile_id = :id"), {"id": profile["id"]})
            if "generation_capability_declarations" in tables:
                conn.execute(
                    text(
                        "DELETE FROM generation_capability_declarations WHERE provider_model_id IN"
                        " (SELECT id FROM provider_models WHERE provider_profile_id = :id)"
                    ),
                    {"id": profile["id"]},
                )
            if "generation_capability_profiles" in tables:
                conn.execute(text("DELETE FROM generation_capability_profiles WHERE provider_profile_id = :id"),
                             {"id": profile["id"]})
            conn.execute(text("UPDATE provider_models SET generation_capability_ref = NULL WHERE provider_profile_id = :id"),
                         {"id": profile["id"]})
            # 假模型 `workflow` 改名。目标那一行已经在(用户早就加过)就把默认模型挪过去再删掉这一行。
            for row in conn.execute(
                text("SELECT id, capability_ids FROM provider_models WHERE provider_profile_id = :id AND model_id = 'workflow'"),
                {"id": profile["id"]},
            ).mappings().all():
                capabilities = loads(row["capability_ids"], []) or []
                if template:
                    target = "api-workflow"
                elif "image" in capabilities or not capabilities:
                    target = "builtin:txt2img"
                else:
                    continue  # 没有模板的视频:原来就跑不了,保持原样
                existing = conn.execute(
                    text("SELECT id FROM provider_models WHERE provider_profile_id = :p AND model_id = :m"),
                    {"p": profile["id"], "m": target},
                ).scalar()
                if existing:
                    if "provider_defaults" in tables:
                        conn.execute(text("UPDATE provider_defaults SET provider_model_id = :new WHERE provider_model_id = :old"),
                                     {"new": existing, "old": row["id"]})
                    conn.execute(text("DELETE FROM provider_models WHERE id = :id"), {"id": row["id"]})
                else:
                    conn.execute(text("UPDATE provider_models SET model_id = :m, source = 'plugin' WHERE id = :id"),
                                 {"m": target, "id": row["id"]})

        if "generation_capability_declarations" in tables:
            conn.execute(
                text("DELETE FROM generation_capability_declarations WHERE catalog_ref IN (:a, :b, :c)"),
                dict(zip(("a", "b", "c"), obsolete_refs)),
            )
        conn.execute(
            text("UPDATE provider_models SET generation_capability_ref = NULL WHERE generation_capability_ref IN (:a, :b, :c)"),
            dict(zip(("a", "b", "c"), obsolete_refs)),
        )

        #: 引用里用到、而连接下还没有行的模型:(连接, 模型 id) → 种类。最后补上。
        wanted: dict[tuple[str, str], str] = {}

        def rewrite(ref: dict[str, Any]) -> dict[str, Any] | None:
            """一份存着的引用 `{provider?, provider_profile_id?, model, kind?, parameters?}` → 新写法;
            跟 ComfyUI 无关的回 None(不动它)。"""
            profile_id = str(ref.get("provider_profile_id") or "")
            if ref.get("provider") != "comfyui" and profile_id not in templated:
                return None
            out = dict(ref)
            if "provider" in out:
                out["provider"] = vendor
            parameters = dict(out.get("parameters") or {}) if isinstance(out.get("parameters"), dict) else {}
            workflow = str(parameters.pop("workflow", "") or "").strip()
            nested = parameters.pop("workflow_params", None)
            if isinstance(nested, dict):
                for node_id, inputs in nested.items():
                    if isinstance(inputs, dict):
                        for name, value in inputs.items():
                            parameters[f"{node_id}.{name}"] = value
            kind = str(out.get("kind") or "image")
            model = str(out.get("model") or "")
            if workflow and workflow not in ("builtin", "custom"):
                model = workflow
            elif model == "workflow" and templated.get(profile_id):
                model = "api-workflow"
            elif model == "workflow" and kind == "image":
                model = "builtin:txt2img"
            out["model"] = model
            if "parameters" in out or parameters:
                out["parameters"] = parameters
            if profile_id and model and model != "workflow":
                wanted.setdefault((profile_id, model), kind)
            return out

        # 生成任务:列上的 provider / model,请求里的参数。
        if "generation_jobs" in tables:
            for row in conn.execute(text(
                "SELECT id, provider, provider_profile_id, model, kind, request FROM generation_jobs"
                " WHERE provider = 'comfyui' OR provider_profile_id IN (SELECT id FROM provider_profiles WHERE vendor = :v)"
            ), {"v": vendor}).mappings().all():
                request = loads(row["request"], {}) or {}
                changed = rewrite({"provider": row["provider"], "provider_profile_id": row["provider_profile_id"],
                                   "model": row["model"], "kind": row["kind"], "parameters": request.get("parameters") or {}})
                if changed is None:
                    continue
                conn.execute(
                    text("UPDATE generation_jobs SET provider = :p, model = :m, request = :r WHERE id = :id"),
                    {"p": changed["provider"], "m": changed["model"],
                     "r": dumps({**request, "parameters": changed["parameters"]}), "id": row["id"]},
                )
        if "jobs" in tables:
            for row in conn.execute(text("SELECT id, payload FROM jobs WHERE kind = 'ai_generation'")).mappings().all():
                payload = loads(row["payload"], {}) or {}
                request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
                changed = rewrite({"provider": payload.get("provider"), "provider_profile_id": payload.get("provider_profile_id"),
                                   "model": payload.get("model"), "kind": payload.get("kind"),
                                   "parameters": request.get("parameters") or {}})
                if changed is None:
                    continue
                payload.update(provider=changed["provider"], model=changed["model"])
                if request:
                    payload["request"] = {**request, "parameters": changed["parameters"]}
                conn.execute(text("UPDATE jobs SET payload = :p WHERE id = :id"), {"p": dumps(payload), "id": row["id"]})
        for table in ("generated_assets", "provider_usage_events", "provider_pricing_rules"):
            if table in tables:
                conn.execute(text(f"UPDATE {table} SET provider = :v WHERE provider = 'comfyui'"), {"v": vendor})
        if "generation_sessions" in tables:
            for row in conn.execute(text(
                "SELECT id, provider_profile_id, model, kind FROM generation_sessions WHERE model = 'workflow'"
                " AND provider_profile_id IN (SELECT id FROM provider_profiles WHERE vendor = :v)"
            ), {"v": vendor}).mappings().all():
                changed = rewrite({"provider_profile_id": row["provider_profile_id"], "model": row["model"], "kind": row["kind"]})
                if changed is not None and changed["model"] != row["model"]:
                    conn.execute(text("UPDATE generation_sessions SET model = :m WHERE id = :id"),
                                 {"m": changed["model"], "id": row["id"]})
        if "scheduled_tasks" in tables:
            for row in conn.execute(text("SELECT id, payload FROM scheduled_tasks")).mappings().all():
                payload = loads(row["payload"], {}) or {}
                if not isinstance(payload, dict) or not ("provider" in payload or "provider_profile_id" in payload):
                    continue
                changed = rewrite(payload)
                if changed is not None and changed != payload:
                    conn.execute(text("UPDATE scheduled_tasks SET payload = :p WHERE id = :id"),
                                 {"p": dumps(changed), "id": row["id"]})
        if "boards" in tables:
            board_columns = {column["name"] for column in inspect(conn).get_columns("boards")}
            for row in conn.execute(text("SELECT id, canvas FROM boards")).mappings().all():
                canvas = loads(row["canvas"], None)
                if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                    continue
                touched = False
                for item in canvas["items"]:
                    form = item.get("form") if isinstance(item, dict) else None
                    if not isinstance(form, dict):
                        continue
                    changed = rewrite({**form, "kind": item.get("kind")})
                    if changed is not None:
                        changed.pop("kind", None)
                        if changed != form:
                            item["form"] = changed
                            touched = True
                if touched:
                    bump = ", revision = revision + 1" if "revision" in board_columns else ""
                    conn.execute(text(f"UPDATE boards SET canvas = :c{bump} WHERE id = :id"),
                                 {"c": dumps(canvas), "id": row["id"]})
        if "workflows" in tables:

            def rewrite_graph(graph: Any) -> Any:
                if not isinstance(graph, dict):
                    return graph
                nodes = []
                for node in graph.get("nodes") or []:
                    if not isinstance(node, dict):
                        nodes.append(node)
                        continue
                    config = dict(node.get("config") or {})
                    if node.get("type") == "ai_generate":
                        changed = rewrite(config)
                        if changed is not None:
                            config = changed
                    for key, value in config.items():
                        if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                            config[key] = rewrite_graph(value)
                    nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
                return {**graph, "nodes": nodes}

            def digest(graph: Any) -> str:
                canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            has_revisions = "workflow_revisions" in tables
            for row in conn.execute(text("SELECT id, graph FROM workflows")).mappings().all():
                graph = loads(row["graph"], None)
                if not isinstance(graph, dict):
                    continue
                rewritten = rewrite_graph(graph)
                if rewritten == graph:
                    continue
                if not has_revisions:
                    conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                                 {"g": dumps(rewritten), "id": row["id"]})
                    continue
                latest = conn.execute(
                    text("SELECT id, revision, created_by FROM workflow_revisions WHERE workflow_id = :id"
                         " ORDER BY revision DESC LIMIT 1"),
                    {"id": row["id"]},
                ).mappings().first()
                revision = int(latest["revision"]) + 1 if latest else 1
                revision_id = uuid.uuid4().hex
                conn.execute(
                    text(
                        "INSERT INTO workflow_revisions (id, workflow_id, revision, graph, graph_hash, source, note,"
                        " created_by, created_at) VALUES (:id, :workflow, :revision, :graph, :hash, 'migration',"
                        " 'ComfyUI 搬进插件:模型与参数改成插件的写法', :author, :now)"
                    ),
                    {"id": revision_id, "workflow": row["id"], "revision": revision, "graph": dumps(rewritten),
                     "hash": digest(rewritten), "author": latest["created_by"] if latest else None, "now": stamp},
                )
                if latest and "workflow_revision_attestations" in tables:
                    for attester in conn.execute(
                        text("SELECT user_id FROM workflow_revision_attestations WHERE revision_id = :id"),
                        {"id": latest["id"]},
                    ).scalars().all():
                        conn.execute(
                            text("INSERT INTO workflow_revision_attestations (id, revision_id, user_id, created_at)"
                                 " VALUES (:id, :revision, :user, :now)"),
                            {"id": uuid.uuid4().hex, "revision": revision_id, "user": attester, "now": stamp},
                        )
                conn.execute(
                    text("UPDATE workflows SET graph = :g, revision = :r, graph_hash = :h WHERE id = :id"),
                    {"g": dumps(rewritten), "r": revision, "h": digest(rewritten), "id": row["id"]},
                )

        # 引用到的模型在连接下还没有行的,补上 —— 否则插件目录刷新之前,那些画板和工作流选不到它。
        for (profile_id, model), kind in wanted.items():
            known = conn.execute(
                text("SELECT 1 FROM provider_models WHERE provider_profile_id = :p AND model_id = :m"),
                {"p": profile_id, "m": model},
            ).first()
            is_plugin = conn.execute(
                text("SELECT 1 FROM provider_profiles WHERE id = :p AND vendor = :v"), {"p": profile_id, "v": vendor}
            ).first()
            if known or not is_plugin:
                continue
            conn.execute(
                text(
                    "INSERT INTO provider_models (id, provider_profile_id, model_id, display_name, capability_ids, enabled,"
                    " source, created_at, updated_at) VALUES (:id, :p, :m, :name, :caps, 1, 'plugin', :now, :now)"
                ),
                {"id": uuid.uuid4().hex, "p": profile_id, "m": model[:160],
                 "name": (model[:-5] if model.endswith(".json") else model)[:160],
                 "caps": dumps([kind if kind in ("image", "video") else "image"]), "now": stamp},
            )
    if profiles:
        logger.info("把 %d 条 ComfyUI 连接搬成了 ComfyUI 插件的连接", len(profiles))


def _migrate_comfyui_connections_drop_the_api_template() -> None:
    """ComfyUI 连接的配置里删掉「API 模板」`api_workflow`(插件 1.17.0 撤掉了这一项)。

    它是转换认不出的工作流的退路:在 ComfyUI 里「导出 (API)」,把 JSON 粘进连接,模型列表里多一项「API 模板」。现在
    导出的 API 格式 JSON 直接导进工作流库就会转成界面格式(插件 workflow_import),是一张普通的保存的工作流 —— 这一项
    没用了,清单里删了。存着的连接上这个键再留着就是一个没人读、也没人能改的变量,照旧被注入插件进程,所以这里摘掉。
    粘过内容的(删掉就丢了)记一句日志,说是哪几条连接。**写死包 id 与配置键**:迁移是历史的快照。幂等。
    """
    if "plugin_instances" not in set(inspect(engine).get_table_names()):
        return
    dropped: list[str] = []
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, name, config FROM plugin_instances WHERE package_id = 'dev.mosael.comfyui'")
        ).fetchall()
        for instance_id, name, raw in rows:
            try:
                config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(config, dict) or "api_workflow" not in config:
                continue
            if str(config.pop("api_workflow") or "").strip():
                dropped.append(str(name or instance_id))
            conn.execute(text("UPDATE plugin_instances SET config = :c WHERE id = :i"),
                         {"c": json.dumps(config, ensure_ascii=False), "i": instance_id})
    if dropped:
        logger.warning("ComfyUI 连接的「API 模板」撤掉了,这几条连接上粘过的模板随之删掉:%s", "、".join(dropped))


def _migrate_blender_host_is_ipv4() -> None:
    """Blender 连接的主机 `::1` 改成 `127.0.0.1`。

    清单里原先有 `::1` 这一项,而它从来连不上:mcp-for-blender 2.0.3 的 MCP 服务和 Blender 里的 Add-on
    两头都开 IPv4 套接字(`socket.AF_INET`),拿 `::1` 去连报「nodename nor servname provided」,界面上
    说的却是「Add-on 没开」。这一项删了;存着它的连接改成同一台机器的 IPv4 回环 —— 用户选 `::1` 的意思
    正是「本机」。**写死包 id 与取值**:迁移是历史的快照,不跟着清单走。幂等。
    """
    if "plugin_instances" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, config FROM plugin_instances WHERE package_id = 'dev.mosael.blender'")
        ).fetchall()
        for instance_id, raw in rows:
            try:
                config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (TypeError, ValueError):
                continue
            if isinstance(config, dict) and config.get("BLENDER_HOST") == "::1":
                config["BLENDER_HOST"] = "127.0.0.1"
                conn.execute(text("UPDATE plugin_instances SET config = :c WHERE id = :i"),
                             {"c": json.dumps(config, ensure_ascii=False), "i": instance_id})


def _remove_minimax_music_models() -> None:
    """MiniMax 音乐撤掉(见 ADR 0022 的补充):它 2026-08-20 起不再向新用户开放,接口留着只会让新用户配好之后
    在第一次付费调用时被对面拒掉。代码里的 Adapter、目录里的三个模型和两份能力档案都删了,这里清掉**存着的指向**。

    - 模型行(`minimax` 连接下的 `music-3.0` / `music-2.6` / `music-cover`)删掉,连同它们的参数声明、指着它们的
      默认模型(置空 = 没设)和这三个模型的价格规则;
    - 别的模型行上指向已删档案 / 模型的「参数按什么来」(`profile:minimax-music*`、`model:minimax/music-*`)清空,
      指着它们的参数声明删掉 —— 留着的话解析回 None,界面显示成「还没认出来」,不如直接回到跟随目录;
    - 存着的**模型选择**清掉:生成会话(AI 工作台)、画板上的生成格、工作流的 `ai_generate` 节点(连同循环体 / 子图,
      改过的追加一版修订,作者和认可人沿用上一版)、定时任务。清掉的是 provider / 连接 / 模型三项,提示词、歌词、
      素材这些用户写下的东西不动 —— 再打开时重新选一个模型就能接着用。**定时任务同时停用**:清掉模型的任务会落到
      默认模型上跑,那是在用户不知道的情况下换了一家花钱;
    - 生成历史、任务回执、产出记录和用量是**发生过的事**,原样保留。

    幂等:第二次跑时这三个模型已经没有行、也没有任何引用。
    """
    tables = set(inspect(engine).get_table_names())
    if "provider_profiles" not in tables:
        return
    models = ("music-3.0", "music-2.6", "music-cover")
    refs = ("profile:minimax-music", "profile:minimax-music-cover", *(f"model:minimax/{one}" for one in models))
    in_models = ", ".join(f":m{index}" for index in range(len(models)))
    in_refs = ", ".join(f":r{index}" for index in range(len(refs)))
    model_params = {f"m{index}": one for index, one in enumerate(models)}
    ref_params = {f"r{index}": one for index, one in enumerate(refs)}

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    with engine.begin() as conn:
        minimax = set(conn.execute(text("SELECT id FROM provider_profiles WHERE vendor = 'minimax'")).scalars().all())

        def points_at_music(ref: dict[str, Any]) -> bool:
            """一份存着的选择 `{provider?, provider_profile_id?, model}` 指的是不是被撤掉的那三个。"""
            if str(ref.get("model") or "").strip() not in models:
                return False
            return ref.get("provider") == "minimax" or str(ref.get("provider_profile_id") or "") in minimax

        def cleared(ref: dict[str, Any]) -> dict[str, Any]:
            return {key: value for key, value in ref.items() if key not in ("provider", "provider_profile_id", "model")}

        if "provider_models" in tables and minimax:
            profile_params = {f"p{index}": one for index, one in enumerate(sorted(minimax))}
            in_profiles = ", ".join(f":{key}" for key in profile_params)
            doomed = conn.execute(
                text(f"SELECT id FROM provider_models WHERE provider_profile_id IN ({in_profiles})"
                     f" AND model_id IN ({in_models})"),
                {**profile_params, **model_params},
            ).scalars().all()
            for row_id in doomed:
                if "generation_capability_declarations" in tables:
                    conn.execute(text("DELETE FROM generation_capability_declarations WHERE provider_model_id = :id"),
                                 {"id": row_id})
                if "provider_defaults" in tables:
                    conn.execute(text("UPDATE provider_defaults SET provider_model_id = NULL WHERE provider_model_id = :id"),
                                 {"id": row_id})
                conn.execute(text("DELETE FROM provider_models WHERE id = :id"), {"id": row_id})
            if "provider_pricing_rules" in tables:
                conn.execute(
                    text(f"DELETE FROM provider_pricing_rules WHERE model IN ({in_models})"
                         f" AND (provider = 'minimax' OR provider_profile_id IN ({in_profiles}))"),
                    {**profile_params, **model_params},
                )
        elif "provider_pricing_rules" in tables:
            conn.execute(text(f"DELETE FROM provider_pricing_rules WHERE provider = 'minimax' AND model IN ({in_models})"),
                         model_params)
        if "generation_capability_declarations" in tables:
            conn.execute(text(f"DELETE FROM generation_capability_declarations WHERE catalog_ref IN ({in_refs})"), ref_params)
        if "provider_models" in tables and "generation_capability_ref" in {
            column["name"] for column in inspect(conn).get_columns("provider_models")
        }:
            conn.execute(
                text(f"UPDATE provider_models SET generation_capability_ref = NULL WHERE generation_capability_ref IN ({in_refs})"),
                ref_params,
            )

        if "generation_sessions" in tables and minimax:
            for row in conn.execute(text(
                f"SELECT id, provider_profile_id, model FROM generation_sessions WHERE model IN ({in_models})"
            ), model_params).mappings().all():
                if points_at_music(dict(row)):
                    conn.execute(text("UPDATE generation_sessions SET model = NULL, provider_profile_id = NULL WHERE id = :id"),
                                 {"id": row["id"]})
        if "scheduled_tasks" in tables:
            for row in conn.execute(text("SELECT id, payload FROM scheduled_tasks")).mappings().all():
                payload = loads(row["payload"], None)
                if isinstance(payload, dict) and points_at_music(payload):
                    conn.execute(text("UPDATE scheduled_tasks SET payload = :p, enabled = 0 WHERE id = :id"),
                                 {"p": dumps(cleared(payload)), "id": row["id"]})
        if "boards" in tables:
            board_columns = {column["name"] for column in inspect(conn).get_columns("boards")}
            for row in conn.execute(text("SELECT id, canvas FROM boards")).mappings().all():
                canvas = loads(row["canvas"], None)
                if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                    continue
                touched = False
                for item in canvas["items"]:
                    form = item.get("form") if isinstance(item, dict) else None
                    if isinstance(form, dict) and points_at_music(form):
                        item["form"] = cleared(form)
                        touched = True
                if touched:
                    bump = ", revision = revision + 1" if "revision" in board_columns else ""
                    conn.execute(text(f"UPDATE boards SET canvas = :c{bump} WHERE id = :id"),
                                 {"c": dumps(canvas), "id": row["id"]})
        if "workflows" in tables:

            def rewrite_graph(graph: Any) -> Any:
                if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
                    return graph
                nodes = []
                for node in graph["nodes"]:
                    if not isinstance(node, dict) or not isinstance(node.get("config"), dict):
                        nodes.append(node)
                        continue
                    config = dict(node["config"])
                    if node.get("type") == "ai_generate" and points_at_music(config):
                        config = cleared(config)
                    for key, value in config.items():
                        if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                            config[key] = rewrite_graph(value)
                    nodes.append({**node, "config": config} if config != node["config"] else node)
                return {**graph, "nodes": nodes}

            def digest(graph: Any) -> str:
                canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            workflow_columns = {column["name"] for column in inspect(conn).get_columns("workflows")}
            has_revisions = "workflow_revisions" in tables and {"revision", "graph_hash"} <= workflow_columns
            for row in conn.execute(text("SELECT id, graph FROM workflows")).mappings().all():
                graph = loads(row["graph"], None)
                rewritten = rewrite_graph(graph)
                if not isinstance(graph, dict) or rewritten == graph:
                    continue
                if not has_revisions:
                    conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                                 {"g": dumps(rewritten), "id": row["id"]})
                    continue
                latest = conn.execute(
                    text("SELECT id, revision, created_by FROM workflow_revisions WHERE workflow_id = :id"
                         " ORDER BY revision DESC LIMIT 1"),
                    {"id": row["id"]},
                ).mappings().first()
                revision = int(latest["revision"]) + 1 if latest else 1
                revision_id = uuid.uuid4().hex
                conn.execute(
                    text(
                        "INSERT INTO workflow_revisions (id, workflow_id, revision, graph, graph_hash, source, note,"
                        " created_by, created_at) VALUES (:id, :workflow, :revision, :graph, :hash, 'migration',"
                        " 'MiniMax 音乐已撤掉:清掉指向它的模型选择', :author, :now)"
                    ),
                    {"id": revision_id, "workflow": row["id"], "revision": revision, "graph": dumps(rewritten),
                     "hash": digest(rewritten), "author": latest["created_by"] if latest else None, "now": stamp},
                )
                if latest and "workflow_revision_attestations" in tables:
                    for attester in conn.execute(
                        text("SELECT user_id FROM workflow_revision_attestations WHERE revision_id = :id"),
                        {"id": latest["id"]},
                    ).scalars().all():
                        conn.execute(
                            text("INSERT INTO workflow_revision_attestations (id, revision_id, user_id, created_at)"
                                 " VALUES (:id, :revision, :user, :now)"),
                            {"id": uuid.uuid4().hex, "revision": revision_id, "user": attester, "now": stamp},
                        )
                conn.execute(
                    text("UPDATE workflows SET graph = :g, revision = :r, graph_hash = :h WHERE id = :id"),
                    {"g": dumps(rewritten), "r": revision, "h": digest(rewritten), "id": row["id"]},
                )


def _merge_object_storage_plugins() -> None:
    """四个对象存储插件(阿里云 OSS / Amazon S3 / 腾讯云 COS / 火山引擎 TOS)合成一个随应用内置的「对象存储」
    插件(`dev.mosael.object-storage`),连哪一家成了连接的配置(`STORAGE_PROVIDER`)。

    **连接 id 不变**,于是「素材外链」的默认(plugin_capability_defaults)、直链缓存(plugin_public_links)、
    工作流和画板上选定的连接(`instance_id`)一个都不用动。在原地改的:

    - 连接:改挂新包;配置 `<家>_BUCKET / _REGION / _ENDPOINT` → `STORAGE_*`,并写上服务商。老 S3 插件填了
      非 amazonaws.com 接入点的(MinIO、R2)归到「S3 兼容服务」。地域空着的按老插件的默认值补上 —— 老代码
      就是这么补的,迁过来行为不变。名字还是老模板生成的那个时,按新模板重生成(新模板对四家生成的正是同一个
      名字;S3 兼容服务那一格除外),这样以后改配置时名字照旧跟着走;用户改过的名字不动;
    - 凭据:**只改键名,不解密**(`value` 是整格密文,和键名无关);
    - 授权:`network:oss|s3|cos|tos` → `network:object-storage`,授过的照旧是授过的;
    - 工具:`oss_upload` → `storage_upload`(presign / fetch / list 同理)。工具开关、调用记录、会话里
      「本会话始终允许」的名字(`plugin__<连接>__<工具>`)和确认卡上的工具名跟着改;新工具缺开关的补上
      (清单是 `expose: all`,全开);
    - 工作流(连同循环体 / 子图)与画板工具格上的节点类型 `plugin.<老包>.<老工具>` → 新写法。入参和出参的
      名字没变(asset_id / key / expires / url / public_url …),数据边与 `{{节点.url}}` 引用不用动。改过的
      工作流追加一版修订,作者和认可人沿用上一版 —— 机械改写不换担保人;
    - 老包的记录删掉,插件目录里老包的文件夹和持久目录删掉 —— 否则下一次扫描会把它们重新登记回来。

    新包由 `install-bundled-plugins`(每次启动的对账,排在前面)装好;有连接要搬而它不在就报错,不搬半截。
    幂等:第二次跑时已经没有老包的连接、记录和目录。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"plugin_packages", "plugin_instances"} <= tables:
        return
    new_package = "dev.mosael.object-storage"
    #: 老包 → (服务商, 配置键前缀, (ID 凭据键, 密钥凭据键), 老权限, 老工具前缀, 老地域默认, 老名字前缀 zh / en)
    legacy: dict[str, tuple[str, str, tuple[str, str], str, str, str, tuple[str, str]]] = {
        "dev.mosael.aliyun-oss": ("aliyun-oss", "OSS", ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"), "network:oss",
                                  "oss", "cn-hangzhou", ("阿里云 OSS", "Alibaba Cloud OSS")),
        "dev.mosael.aws-s3": ("aws-s3", "S3", ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"), "network:s3",
                              "s3", "us-east-1", ("Amazon S3", "Amazon S3")),
        "dev.mosael.tencent-cos": ("tencent-cos", "COS", ("COS_SECRET_ID", "COS_SECRET_KEY"), "network:cos",
                                   "cos", "ap-guangzhou", ("腾讯云 COS", "Tencent Cloud COS")),
        "dev.mosael.volcengine-tos": ("volcengine-tos", "TOS", ("TOS_ACCESS_KEY", "TOS_SECRET_KEY"), "network:tos",
                                      "tos", "cn-beijing", ("火山引擎 TOS", "Volcengine TOS")),
    }
    #: 新清单里服务商的显示名(zh, en)—— 和 name_template `{STORAGE_PROVIDER:label} · {STORAGE_BUCKET}` 同一份。
    labels = {"aliyun-oss": ("阿里云 OSS", "Alibaba Cloud OSS"), "aws-s3": ("Amazon S3", "Amazon S3"),
              "tencent-cos": ("腾讯云 COS", "Tencent Cloud COS"), "volcengine-tos": ("火山引擎 TOS", "Volcengine TOS"),
              "s3-compatible": ("S3 兼容服务", "S3-compatible service")}
    actions = ("upload", "presign", "fetch", "list")
    #: 节点类型 / 画板产出者的新旧写法。
    node_types = {
        f"plugin.{package}.{spec[4]}_{action}": f"plugin.{new_package}.storage_{action}"
        for package, spec in legacy.items() for action in actions
    }
    node_types.update({f"node:{old}": f"node:{new}" for old, new in list(node_types.items())})

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def safe(name: str) -> str:
        """智能体工具名里的一段(agent.tool_manifest.agent_tool_name 同一条折叠规则)。"""
        return re.sub(r"[^A-Za-z0-9_]+", "_", name)

    def renamed(value: Any) -> Any:
        """把一份 JSON 里**恰好等于**某个老节点类型的字符串换掉(键不动)。"""
        if isinstance(value, dict):
            return {key: renamed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return node_types.get(value, value) if isinstance(value, str) else value

    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    old_ids = tuple(legacy)
    marks = ", ".join(f":p{index}" for index in range(len(old_ids)))
    by_index = {f"p{index}": one for index, one in enumerate(old_ids)}
    with engine.begin() as conn:
        instances = conn.execute(
            text(f"SELECT id, package_id, name, config FROM plugin_instances WHERE package_id IN ({marks})"), by_index
        ).mappings().all()
        if instances and conn.execute(text("SELECT 1 FROM plugin_packages WHERE id = :id"),
                                      {"id": new_package}).first() is None:
            raise RuntimeError("the bundled object-storage plugin is not installed; storage connections cannot be merged yet")

        #: 这次改了名的智能体工具名:`plugin__<连接>__oss_upload` → `plugin__<连接>__storage_upload`。
        agent_tools: dict[str, str] = {}
        for row in instances:
            provider, prefix, (id_key, secret_key), permission, tool_prefix, region_default, (zh, en) = legacy[row["package_id"]]
            old = loads(row["config"], {}) or {}
            bucket = str(old.get(f"{prefix}_BUCKET") or "").strip()
            region = str(old.get(f"{prefix}_REGION") or "").strip() or region_default
            endpoint = str(old.get(f"{prefix}_ENDPOINT") or "").strip()
            if provider == "aws-s3" and endpoint and "amazonaws.com" not in endpoint.lower():
                provider = "s3-compatible"
            config = {"STORAGE_PROVIDER": provider, "STORAGE_BUCKET": bucket, "STORAGE_REGION": region,
                      "STORAGE_ENDPOINT": endpoint}
            name = row["name"] or ""
            if name == f"{zh} · {bucket}":
                name = f"{labels[provider][0]} · {bucket}"
            elif name == f"{en} · {bucket}":
                name = f"{labels[provider][1]} · {bucket}"
            conn.execute(
                text("UPDATE plugin_instances SET package_id = :package, config = :config, name = :name, updated_at = :now"
                     " WHERE id = :id"),
                {"package": new_package, "config": dumps(config), "name": name, "now": stamp, "id": row["id"]},
            )

            def move(table: str, column: str, old_value: str, new_value: str, instance_id: str = row["id"]) -> None:
                """把这个连接的一行从老键改到新键;新键已经有了就删掉老的(第二次跑、或者用户手动补过)。"""
                if table not in tables:
                    return
                taken = conn.execute(
                    text(f"SELECT 1 FROM {table} WHERE instance_id = :id AND {column} = :new"),
                    {"id": instance_id, "new": new_value},
                ).first()
                verb = f"DELETE FROM {table}" if taken else f"UPDATE {table} SET {column} = :new"
                conn.execute(text(f"{verb} WHERE instance_id = :id AND {column} = :old"),
                             {"id": instance_id, "old": old_value, "new": new_value})

            move("plugin_credentials", "key", id_key, "STORAGE_ACCESS_KEY_ID")
            move("plugin_credentials", "key", secret_key, "STORAGE_ACCESS_KEY_SECRET")
            move("plugin_permission_grants", "permission", permission, "network:object-storage")
            for action in actions:
                move("plugin_capabilities", "tool_name", f"{tool_prefix}_{action}", f"storage_{action}")
                if "plugin_invocations" in tables:
                    conn.execute(
                        text("UPDATE plugin_invocations SET tool_name = :new WHERE instance_id = :id AND tool_name = :old"),
                        {"id": row["id"], "old": f"{tool_prefix}_{action}", "new": f"storage_{action}"},
                    )
                agent_tools[f"plugin__{safe(row['id'])}__{tool_prefix}_{action}"] = f"plugin__{safe(row['id'])}__storage_{action}"
                if "plugin_capabilities" in tables and conn.execute(
                    text("SELECT 1 FROM plugin_capabilities WHERE instance_id = :id AND tool_name = :tool"),
                    {"id": row["id"], "tool": f"storage_{action}"},
                ).first() is None:
                    conn.execute(
                        text("INSERT INTO plugin_capabilities (instance_id, tool_name, exposed) VALUES (:id, :tool, 1)"),
                        {"id": row["id"], "tool": f"storage_{action}"},
                    )

        if agent_tools and "agent_sessions" in tables:
            for session in conn.execute(text("SELECT id, auto_allow_tools FROM agent_sessions")).mappings().all():
                allowed = loads(session["auto_allow_tools"], []) or []
                if isinstance(allowed, list) and any(name in agent_tools for name in allowed):
                    conn.execute(text("UPDATE agent_sessions SET auto_allow_tools = :v WHERE id = :id"),
                                 {"v": dumps([agent_tools.get(name, name) for name in allowed]), "id": session["id"]})
        if agent_tools and "tool_confirmations" in tables:
            for old_name, new_name in agent_tools.items():
                conn.execute(text("UPDATE tool_confirmations SET tool = :new WHERE tool = :old"),
                             {"old": old_name, "new": new_name})

        if "boards" in tables:
            board_columns = {column["name"] for column in inspect(conn).get_columns("boards")}
            for row in conn.execute(text("SELECT id, canvas FROM boards")).mappings().all():
                canvas = loads(row["canvas"], None)
                rewritten = renamed(canvas)
                if isinstance(canvas, dict) and rewritten != canvas:
                    bump = ", revision = revision + 1" if "revision" in board_columns else ""
                    conn.execute(text(f"UPDATE boards SET canvas = :c{bump} WHERE id = :id"),
                                 {"c": dumps(rewritten), "id": row["id"]})

        if "workflows" in tables:

            def digest(graph: Any) -> str:
                canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            workflow_columns = {column["name"] for column in inspect(conn).get_columns("workflows")}
            has_revisions = "workflow_revisions" in tables and {"revision", "graph_hash"} <= workflow_columns
            for row in conn.execute(text("SELECT id, graph FROM workflows")).mappings().all():
                graph = loads(row["graph"], None)
                rewritten = renamed(graph)
                if not isinstance(graph, dict) or rewritten == graph:
                    continue
                if not has_revisions:
                    conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                                 {"g": dumps(rewritten), "id": row["id"]})
                    continue
                latest = conn.execute(
                    text("SELECT id, revision, created_by FROM workflow_revisions WHERE workflow_id = :id"
                         " ORDER BY revision DESC LIMIT 1"),
                    {"id": row["id"]},
                ).mappings().first()
                revision = int(latest["revision"]) + 1 if latest else 1
                revision_id = uuid.uuid4().hex
                conn.execute(
                    text(
                        "INSERT INTO workflow_revisions (id, workflow_id, revision, graph, graph_hash, source, note,"
                        " created_by, created_at) VALUES (:id, :workflow, :revision, :graph, :hash, 'migration',"
                        " '对象存储四个插件合成一个:节点改用「对象存储」的工具', :author, :now)"
                    ),
                    {"id": revision_id, "workflow": row["id"], "revision": revision, "graph": dumps(rewritten),
                     "hash": digest(rewritten), "author": latest["created_by"] if latest else None, "now": stamp},
                )
                if latest and "workflow_revision_attestations" in tables:
                    for attester in conn.execute(
                        text("SELECT user_id FROM workflow_revision_attestations WHERE revision_id = :id"),
                        {"id": latest["id"]},
                    ).scalars().all():
                        conn.execute(
                            text("INSERT INTO workflow_revision_attestations (id, revision_id, user_id, created_at)"
                                 " VALUES (:id, :revision, :user, :now)"),
                            {"id": uuid.uuid4().hex, "revision": revision_id, "user": attester, "now": stamp},
                        )
                conn.execute(
                    text("UPDATE workflows SET graph = :g, revision = :r, graph_hash = :h WHERE id = :id"),
                    {"g": dumps(rewritten), "r": revision, "h": digest(rewritten), "id": row["id"]},
                )

        conn.execute(text(f"DELETE FROM plugin_packages WHERE id IN ({marks})"), by_index)

    # 文件夹最后删:库里的事务提交之后。删之前认两件事 —— 它是插件目录的**直接子目录**,里面那份清单的 id
    # 确实是老包之一(不按文件夹名猜:手动放进来的包可以叫任何名字)。
    plugins_dir = settings.plugins_dir
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            manifest = child / "mosael.plugin.json"
            if not child.is_dir() or not manifest.is_file():
                continue
            try:
                package_id = json.loads(manifest.read_text(encoding="utf-8")).get("id")
            except (OSError, ValueError, AttributeError):
                continue
            if package_id in legacy:
                shutil.rmtree(child)
    for package_id in legacy:
        shutil.rmtree(settings.data_dir / "plugin-data" / package_id, ignore_errors=True)
    if instances:
        logger.info("把 %d 个对象存储连接合进了「对象存储」插件", len(instances))


def _upgrade_stored_plugin_manifests() -> None:
    """包记录里存着的清单跟着清单迁移链(mosael_formats.plugin_manifest_upgrade)升到当前版本。

    **对账,不是迁移**:清单版本随哪一版应用都可能 +1。磁盘上的清单只在扫描时升,而扫描要人点「扫描插件」
    或装包才跑;在那之前读的一直是记录里存的那份。清单规则收紧时(Manim 0.2 的 `PIP_INDEX_URL` 配置项成了
    宿主占着的名字),那份就解析不过 —— 插件页、智能体会话、工作流一碰到插件就 500。

    只动记录:`_path` 是扫描写进去的运行时字段,迁移链会清掉它,这里放回去。磁盘那份下次扫描时由同一串步骤改。
    """
    from app.domain.plugins.manifest import PATH_KEY
    from app.domain.plugins.migrations import upgrade

    if "plugin_packages" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for package_id, stored in conn.execute(text("SELECT id, manifest FROM plugin_packages")).fetchall():
            try:
                raw = json.loads(stored) if isinstance(stored, str) else dict(stored or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            path = raw.get(PATH_KEY)
            if not upgrade(raw):
                continue
            if path:
                raw[PATH_KEY] = path
            conn.execute(
                text("UPDATE plugin_packages SET manifest = :m WHERE id = :i"),
                {"m": json.dumps(raw, ensure_ascii=False), "i": package_id},
            )


def _install_bundled_plugins() -> None:
    """随应用发的插件(`plugins/bundled/`)装进插件目录并登记包记录。

    **对账,不是迁移**:每个版本带的插件都可能变,判据是内容指纹(见 domain/plugins/bundled)。
    在这里而不是 lifespan:把老数据搬到插件上的迁移(ComfyUI 连接 → ComfyUI 插件实例)要先有
    这个包;而且不跑 lifespan 的入口(TestClient、脚本)拿到的也该是装好的系统。
    """
    from sqlalchemy.orm import Session

    from app.domain.plugins import bundled

    if "plugin_packages" not in set(inspect(engine).get_table_names()):
        return
    with Session(engine) as db:
        bundled.install(db, settings.plugins_dir)


def _forget_comfyui_run_workflow_tool() -> None:
    """ComfyUI 插件 1.4.0 删掉了通用的「按 id 跑工作流」(`run_workflow`):它连要跑哪张图都不知道,表单却要人填
    参数;它能跑的每一种图(保存的工作流、粘贴的 API 模板、内置文生图)都有了自己的工具。

    **存着的节点不在这里改。** 工作流里、画板工具格上的 `plugin.dev.mosael.comfyui.run_workflow` 要改成哪张图的
    工具、入参怎么改名,只有插件报出的工具清单说得出(`replaces`,图在 ComfyUI 里);那是每次启动和每次清单刷新都跑
    的对账 `rewrite-replaced-plugin-tools` 的事 —— 老工具不在了,对不上的格子由它丢掉并记进修订说明。定时任务
    只指着工作流,工作流改好就是改好了。选的那张图在 ComfyUI 里已经删了的节点无从改起,留着,运行前检查报「未知的
    节点类型」—— 和一个指向已删工作流的 `wf_…` 节点是同一种状态。

    这里清的是**只挂着工具名、没有别的去处**的几样,它们不用等清单:

    - `plugin_capabilities` 里这个工具的开关(工具不在了,开关没有意义;以后要是再有同名工具,不该继承它);
    - 会话里「本会话始终允许」的 `plugin__<连接>__run_workflow`(折叠规则同 agent.tool_manifest.agent_tool_name)。
      不转给每张图的工具:允许过「按 id 跑任意一张」不等于允许过哪一张。

    调用记录和确认卡是历史,不动。幂等:第二次跑时已经没有这些行。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"plugin_instances", "plugin_capabilities"} <= tables:
        return
    package_id = "dev.mosael.comfyui"

    def safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", value)

    with engine.begin() as conn:
        instance_ids = conn.execute(
            text("SELECT id FROM plugin_instances WHERE package_id = :p"), {"p": package_id}
        ).scalars().all()
        if not instance_ids:
            return
        for instance_id in instance_ids:
            conn.execute(
                text("DELETE FROM plugin_capabilities WHERE instance_id = :id AND tool_name = 'run_workflow'"),
                {"id": instance_id},
            )
        if "agent_sessions" not in tables:
            return
        retired = {f"plugin__{safe(instance_id)}__run_workflow" for instance_id in instance_ids}
        for session in conn.execute(text("SELECT id, auto_allow_tools FROM agent_sessions")).mappings().all():
            raw = session["auto_allow_tools"]
            try:
                allowed = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if isinstance(allowed, list) and retired & set(allowed):
                conn.execute(
                    text("UPDATE agent_sessions SET auto_allow_tools = :v WHERE id = :id"),
                    {"v": json.dumps([name for name in allowed if name not in retired], ensure_ascii=False),
                     "id": session["id"]},
                )


def _migrate_generation_capabilities_need_evidence() -> None:
    """生成能力要有正面证据(见 domain/providers/models.evidenced_capabilities):把**没写能力**的模型行按新规则
    认出来的能力**写进** `capability_ids`,让设置页的能力标签和选择器看的是同一份、看得见也改得了。

    此前行上没写能力时兜底的是整个供应商预设:OpenAI 兼容连接(147ai、Ollama)上的每个对话模型都是生图模型,
    Evolink 上一个认不出的模型同时是图像、视频和音乐模型 —— 画板的出图下拉里于是列着 `claude-opus-4-6`。

    - **写过能力的行一概不碰**:那是用户的话,哪怕和新规则不一致;
    - 没写的行,落成新规则的结果:目录认得的按目录,连接声明过 / 用户写过参数契约的按那几种,单能力供应商按
      那一种,其余只剩对话(多能力预设里有对话的话)。聚合连接上认不出的模型因此变成**只当对话模型**;
    - 但**用户用行动说过**它能做的那几种,照旧保留(只限旧规则当时确实给了的那几种):
        · 他把这一行设成了这种能力的**默认模型**;
        · 这一行在这种生成上**真的出过东西**(生成历史里有产出、或那一趟任务成功了);
        · 他在这一行上写过旧版的「参数按什么来」(`generation_capability_ref`),而它解析得到这种生成。
      于是一个在中转上跑通了的生图模型不会因为名字没登记就从下拉里消失;
    - 新规则什么都认不出、也没有用户证据的行(Evolink 上认不出的模型)留空 —— 空就是"按规则认",而规则
      认不出它,它不进任何下拉,设置里标上能力即可;
    - 存着的**模型选择**(画板格、工作流节点、定时任务、AI 工作台会话)不改:指着一个不再能做这件事的模型时,
      选择器显示「选择模型」,生成漏斗报「没有标上这项能力」(genErr_modelLacksKind_*),不会崩。

    规则本身取领域里那一份,不在这里抄:这一步的意思就是"把现在这条规则的答案写下来",抄一份只会让两边
    分岔。幂等:第二次跑时这些行都已经写了能力,第一条就跳过;留空的那些再算一遍还是空。
    """
    tables = set(inspect(engine).get_table_names())
    if "provider_models" not in tables or "provider_profiles" not in tables:
        return
    from app.domain.generation.catalog import GENERATION_KINDS, resolve_capability_ref
    from app.domain.providers.models import evidenced_capabilities, infer_capabilities
    from app.domain.providers.selection import ALL_CAPABILITY_IDS, capability_ids_for_vendor

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT m.id, m.model_id, m.capability_ids, m.declared_capabilities, m.generation_capability_ref,"
                " m.provider_profile_id, p.vendor FROM provider_models m"
                " JOIN provider_profiles p ON p.id = m.provider_profile_id"
            )
        ).mappings().all()

        declaration_kinds: dict[str, set[str]] = {}
        if "generation_capability_declarations" in tables:
            for model_row_id, kind in conn.execute(
                text("SELECT provider_model_id, kind FROM generation_capability_declarations")
            ).all():
                declaration_kinds.setdefault(str(model_row_id), set()).add(str(kind))

        #: 用户用行动说过的:模型行 id → 能力。
        acted: dict[str, set[str]] = {}
        if "provider_defaults" in tables:
            for capability, model_row_id in conn.execute(
                text("SELECT capability, provider_model_id FROM provider_defaults WHERE provider_model_id IS NOT NULL")
            ).all():
                acted.setdefault(str(model_row_id), set()).add(str(capability))
        produced: set[tuple[str, str, str]] = set()
        if "generation_jobs" in tables:
            succeeded = " OR g.job_id IN (SELECT id FROM jobs WHERE status = 'succeeded')" if "jobs" in tables else ""
            for profile_id, model_name, kind in conn.execute(
                text(
                    "SELECT DISTINCT g.provider_profile_id, g.model, g.kind FROM generation_jobs g"
                    f" WHERE g.provider_profile_id IS NOT NULL AND (g.result_asset_id IS NOT NULL{succeeded})"
                )
            ).all():
                produced.add((str(profile_id), str(model_name), str(kind)))
        custom_profiles: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        if "generation_capability_profiles" in tables:
            for template_id, profile_id, kind, capabilities in conn.execute(
                text("SELECT id, provider_profile_id, kind, capabilities FROM generation_capability_profiles")
            ).all():
                by_kind = custom_profiles.setdefault(str(profile_id), {}).setdefault(str(kind), {})
                by_kind[str(template_id)] = loads(capabilities, {}) or {}

        written = narrowed = 0
        for row in rows:
            own = [one for one in (loads(row["capability_ids"], []) or []) if one in ALL_CAPABILITY_IDS]
            if own:
                continue
            row_id = str(row["id"])
            vendor = str(row["vendor"] or "")
            model_name = str(row["model_id"] or "")
            profile_id = str(row["provider_profile_id"])
            declared = loads(row["declared_capabilities"], {}) or {}
            evidence = set(declaration_kinds.get(row_id, set()))
            if isinstance(declared, dict):
                evidence |= {str(kind) for kind in declared}
            capabilities = evidenced_capabilities(vendor, model_name, declared_kinds=evidence)

            before = infer_capabilities(vendor, model_name) or capability_ids_for_vendor(vendor)
            ref = str(row["generation_capability_ref"] or "").strip()
            for capability in before:
                if capability in capabilities:
                    continue
                if (
                    capability in acted.get(row_id, set())
                    or (profile_id, model_name, capability) in produced
                    or (
                        bool(ref)
                        and capability in GENERATION_KINDS
                        and resolve_capability_ref(
                            ref, capability, custom=custom_profiles.get(profile_id, {}).get(capability)
                        )
                        is not None
                    )
                ):
                    capabilities.append(capability)
            lost = [one for one in before if one not in capabilities and one in (*GENERATION_KINDS, "tts")]
            if lost:
                narrowed += 1
                logger.info(
                    "模型 %s(%s 连接)没有「能做 %s」的证据,不再出现在对应的生成入口里;要用它就在设置里标上",
                    model_name, vendor, "/".join(lost),
                )
            if not capabilities:
                continue
            conn.execute(
                text("UPDATE provider_models SET capability_ids = :caps WHERE id = :id"),
                {"caps": json.dumps(capabilities), "id": row_id},
            )
            written += 1
        if written or narrowed:
            logger.info("模型能力落成显式标签:%d 行写下了能力,其中 %d 行收窄了生成能力", written, narrowed)


def _rewrite_replaced_plugin_tools() -> None:
    """工作流里、画板上(内容格的能力、空格子上的生成器)存着的、已被插件运行时报出的新工具取代的老插件节点,改写成新工具(见
    domain/workflows/plugin_references 与 domain/boards/plugin_references)。ComfyUI 的 `run_workflow` + 某张工作流 → 那张工作流自己的工具。
    老工具已经从插件里删掉了的(ComfyUI 的 `run_workflow` 就是),新工具上没有位置的格子丢掉、记进修订说明 ——
    留着一个跑不起来的节点不是保住了用户的值。

    **对账,不是一次性迁移**:依据是插件上一次报出的工具清单(缓存在 `plugin_instances.discovered_tools`),
    清单会变(用户在 ComfyUI 里新存了工作流),新出现的对应关系下次启动也该迁;清单刷新时同一个函数也会跑。
    没有可迁的就什么都不做。

    画板上还多一件:工具声明了 `mirrors`(和一个生成模型是同一件事)、连接的主人用得上那个模型时,空格子上存着的
    这个生成器改挂生成、选那个模型(见 domain/boards/plugin_references 的「被生成取代的生成器」)。同一个道理是对账:
    `mirrors` 只在插件报出清单之后才有。
    """
    from sqlalchemy.orm import Session

    from app.domain.boards import plugin_references as board_references
    from app.domain.workflows import plugin_references

    if not {"plugin_instances", "workflows", "workflow_revisions", "boards"} <= set(inspect(engine).get_table_names()):
        return
    with Session(engine) as db:
        plugin_references.rewrite_replaced_tools(db)
        board_references.reconcile_plugin_tool_cells(db)


def _migrate_plugin_generation_columns() -> None:
    """插件可以是生成供应商(ADR 0020)要的三列。

    - `provider_profiles.plugin_instance_id`:这条连接**是**哪个插件实例(外键,实例删掉连接跟着删);
    - `provider_models.declared_capabilities`:连接自己声明的生成参数描述符(插件目录刷新时写);
    - `plugin_instances.capability_status`:这个实例替宿主做的事上一次做得怎么样(几个模型、失败原因)。

    `create_all` 不给已有的表加列,所以在它之前。表不在(还没建过)的跳过 —— 那种库由
    `create-current-schema` 直接建成带这几列的样子。
    """
    with engine.begin() as conn:
        def columns(table: str) -> set[str]:
            return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}

        profile_columns = columns("provider_profiles")
        if profile_columns and "plugin_instance_id" not in profile_columns:
            conn.execute(text(
                "ALTER TABLE provider_profiles ADD COLUMN plugin_instance_id VARCHAR(64) "
                "REFERENCES plugin_instances (id) ON DELETE CASCADE"
            ))
        if profile_columns:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_provider_profiles_plugin_instance_id "
                "ON provider_profiles (plugin_instance_id)"
            ))
        model_columns = columns("provider_models")
        if model_columns and "declared_capabilities" not in model_columns:
            conn.execute(text("ALTER TABLE provider_models ADD COLUMN declared_capabilities JSON"))
        instance_columns = columns("plugin_instances")
        if instance_columns and "capability_status" not in instance_columns:
            conn.execute(text(
                "ALTER TABLE plugin_instances ADD COLUMN capability_status JSON NOT NULL DEFAULT '{}'"
            ))


def _migrate_plugin_authorization_rejected() -> None:
    """`plugin_instances.authorization_rejected_at`:插件上一次说「对方不再接受已存的令牌」是什么时候。

    `create_all` 不给已有的表加列,所以在它之前。表不在的跳过 —— 那种库由 `create-current-schema`
    直接建成带这一列的样子。可空、没有缺省:老连接一律「没被拒过」,和它们的真实状态一致。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plugin_instances)"))}
        if columns and "authorization_rejected_at" not in columns:
            conn.execute(text("ALTER TABLE plugin_instances ADD COLUMN authorization_rejected_at DATETIME"))


def _migrate_provider_credentials_remember_rejected_refresh() -> None:
    """`provider_credentials.oauth_rejected_at`:对方上一次明确拒绝刷新这份订阅凭据是什么时候(要重新授权)。

    `create_all` 不给已有的表加列,所以在它之前。表不在的跳过 —— 那种库由 `create-current-schema` 直接建成带这一列的
    样子。可空、没有缺省:老凭据一律「没被拒过」;真被拒的,下一次刷新撞上时当场记下。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_credentials)"))}
        if columns and "oauth_rejected_at" not in columns:
            conn.execute(text("ALTER TABLE provider_credentials ADD COLUMN oauth_rejected_at DATETIME"))


def _migrate_plugin_connections_choose_package_sources() -> None:
    """包镜像由宿主给:`tts_config.npm_registry`(管理 → 下载源的 npm 那一行)、`plugin_instances.package_sources`
    (连接自己的覆盖,见 domain/plugins/package_sources)。

    此前 Manim、Remotion 各在自己的清单里带一个镜像配置项(`PIP_INDEX_URL`、`NPM_REGISTRY`),是自由文本框,
    和管理页的 pip 下载源互不知道。新版清单删了这两项、改声明 `package_sources`;存着它们的连接在这里搬成
    连接自己的覆盖 —— 填的地址正好是某个预设的,记成那个预设的 key。搬完从 config 里删掉,不删就还会被注入。

    `create_all` 不给已有的表加列,所以在它之前。**写死包 id、配置键和预设地址**:迁移是历史的快照。幂等。
    """
    presets = {
        "pypi": {"https://pypi.tuna.tsinghua.edu.cn/simple": "tsinghua", "https://mirrors.aliyun.com/pypi/simple/": "aliyun",
                 "https://mirrors.cloud.tencent.com/pypi/simple": "tencent"},
        "npm": {"https://registry.npmmirror.com": "npmmirror", "https://mirrors.cloud.tencent.com/npm/": "tencent",
                "https://repo.huaweicloud.com/repository/npm/": "huawei"},
    }
    moves = {"dev.mosael.manim": ("PIP_INDEX_URL", "pypi"), "dev.mosael.remotion": ("NPM_REGISTRY", "npm")}
    with engine.begin() as conn:
        tts_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(tts_config)"))}
        if tts_columns and "npm_registry" not in tts_columns:
            conn.execute(text("ALTER TABLE tts_config ADD COLUMN npm_registry VARCHAR(200) NOT NULL DEFAULT ''"))
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plugin_instances)"))}
        if not columns:
            return
        if "package_sources" not in columns:
            conn.execute(text("ALTER TABLE plugin_instances ADD COLUMN package_sources JSON NOT NULL DEFAULT '{}'"))
        for package_id, (key, source) in moves.items():
            rows = conn.execute(
                text("SELECT id, config, package_sources FROM plugin_instances WHERE package_id = :p"), {"p": package_id}
            ).fetchall()
            for instance_id, raw_config, raw_sources in rows:
                try:
                    config = json.loads(raw_config) if isinstance(raw_config, str) else dict(raw_config or {})
                    sources = json.loads(raw_sources) if isinstance(raw_sources, str) else dict(raw_sources or {})
                except (TypeError, ValueError):
                    continue
                if not isinstance(config, dict) or key not in config:
                    continue
                url = str(config.pop(key) or "").strip()
                if url and isinstance(sources, dict) and not sources.get(source):
                    sources[source] = presets[source].get(url) or presets[source].get(url.rstrip("/")) or url
                conn.execute(
                    text("UPDATE plugin_instances SET config = :c, package_sources = :s WHERE id = :i"),
                    {"c": json.dumps(config, ensure_ascii=False), "s": json.dumps(sources, ensure_ascii=False),
                     "i": instance_id},
                )


def _migrate_plugin_connections_choose_their_network() -> None:
    """插件连接有了宿主给的「网络」:`plugin_instances.network_mode` / `proxy_url`(见 domain/plugins/egress)。

    此前全局出站代理到不了插件子进程,MinerU 就在自己的清单里发明了一对配置 `MINERU_NETWORK`
    (system / direct / proxy)和 `MINERU_PROXY`。清单里这两项删了,存着它们的连接在这里搬到新的两列上:
    system → follow(没配全局代理时两者是同一个行为;配了,默认就该跟着它走)、direct → direct、
    proxy → proxy。选了走代理却没填地址的,当时每次调用都报错,搬成 follow。搬完从 config 里删掉 ——
    不删的话它们照旧被注入插件进程,是两个没人读、也没人能改的变量。

    `create_all` 不给已有的表加列,所以在它之前。老连接一律 follow:此前它们拿到的环境里根本没有代理变量,
    follow 在没配全局代理时给的也正是这样的环境。**写死包 id 与取值**:迁移是历史的快照。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plugin_instances)"))}
        if not columns:
            return
        if "network_mode" not in columns:
            conn.execute(text(
                "ALTER TABLE plugin_instances ADD COLUMN network_mode VARCHAR(16) NOT NULL DEFAULT 'follow'"
            ))
        if "proxy_url" not in columns:
            conn.execute(text("ALTER TABLE plugin_instances ADD COLUMN proxy_url VARCHAR(300) NOT NULL DEFAULT ''"))
        rows = conn.execute(
            text("SELECT id, config FROM plugin_instances WHERE package_id = 'dev.mosael.mineru'")
        ).fetchall()
        for instance_id, raw in rows:
            try:
                config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(config, dict) or not {"MINERU_NETWORK", "MINERU_PROXY"} & set(config):
                continue
            chosen = str(config.pop("MINERU_NETWORK", "") or "").strip().lower()
            url = str(config.pop("MINERU_PROXY", "") or "").strip()
            mode = {"direct": "direct", "proxy": "proxy"}.get(chosen, "follow")
            if mode == "proxy" and not url:
                mode = "follow"
            conn.execute(
                text("UPDATE plugin_instances SET config = :c, network_mode = :m, proxy_url = :u WHERE id = :i"),
                {
                    "c": json.dumps(config, ensure_ascii=False),
                    "m": mode,
                    "u": url if mode == "proxy" else "",
                    "i": instance_id,
                },
            )


def _migrate_plugin_instances() -> None:
    """插件从「一行 = 一个包 = 一次接入」拆成「包 → 实例 → 能力」三层。

    旧表 plugins 里的每一行都是"装了并且配好了的一次接入",所以逐行搬成:一个 package +
    一个 instance,凭据 / 授权 / 调用记录改挂 instance。

    **已发现的工具全部勾上**,不套新的"默认不暴露"。升级不该改变用户已经在界面上看到的
    东西 —— 那条规矩只对之后新建的实例生效。

    必须在 create_all **之前**跑重命名(否则 create_all 会建一张空的 plugin_packages,
    旧数据留在 plugins 里无人认领),但实例表要等 create_all 建好才能填 —— 所以这个函数
    只做重命名和列的准备,填充留给 _backfill_plugin_instances。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "plugins" not in tables or "plugin_packages" in tables:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE plugins RENAME TO plugin_packages"))
        # 旧的子表按 plugin_id 挂着,重命名到一边等回填改挂 instance_id。
        for table in ("plugin_permission_grants", "plugin_credentials", "plugin_invocations"):
            if table in tables:
                conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}_legacy"))


def _backfill_plugin_instances() -> None:
    """给每个包建一个默认实例,把旧的凭据 / 授权 / 调用记录搬过去。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "plugin_packages_legacy_done" in tables or "plugin_permission_grants_legacy" not in tables:
        return
    with engine.begin() as conn:
        packages = conn.execute(text("SELECT id, name FROM plugin_packages")).fetchall()
        enabled_col = "enabled" in {c["name"] for c in inspector.get_columns("plugin_packages")}
        for package_id, name in packages:
            enabled = 0
            if enabled_col:
                row = conn.execute(
                    text("SELECT enabled FROM plugin_packages WHERE id = :id"), {"id": package_id}
                ).fetchone()
                enabled = int(bool(row[0])) if row else 0
            instance_id = uuid.uuid4().hex
            tools = conn.execute(
                text("SELECT json_extract(manifest, '$._discovered_tools') FROM plugin_packages WHERE id = :id"),
                {"id": package_id},
            ).scalar()
            conn.execute(
                text(
                    "INSERT INTO plugin_instances (id, package_id, name, enabled, config, discovered_tools,"
                    " created_at, updated_at) VALUES (:i, :p, :n, :e, '{}', :t, :now, :now)"
                ),
                {"i": instance_id, "p": package_id, "n": name, "e": enabled, "t": tools or "[]", "now": now()},
            )
            # 已发现的工具全部勾上:升级不改变用户已经看到的东西。
            for tool in json.loads(tools or "[]"):
                if isinstance(tool, dict) and tool.get("name"):
                    conn.execute(
                        text("INSERT INTO plugin_capabilities (instance_id, tool_name, exposed) VALUES (:i, :t, 1)"),
                        {"i": instance_id, "t": tool["name"]},
                    )
            conn.execute(
                text(
                    "INSERT INTO plugin_permission_grants (instance_id, permission, granted, created_at, updated_at)"
                    " SELECT :i, permission, granted, created_at, updated_at"
                    " FROM plugin_permission_grants_legacy WHERE plugin_id = :p"
                ),
                {"i": instance_id, "p": package_id},
            )
            conn.execute(
                text(
                    "INSERT INTO plugin_credentials (instance_id, key, value, created_at, updated_at)"
                    " SELECT :i, key, value, created_at, updated_at"
                    " FROM plugin_credentials_legacy WHERE plugin_id = :p"
                ),
                {"i": instance_id, "p": package_id},
            )
            conn.execute(
                text(
                    "INSERT INTO plugin_invocations (id, instance_id, tool_name, status, input, output, error,"
                    " created_at) SELECT id, :i, tool_name, status, input, output, error, created_at"
                    " FROM plugin_invocations_legacy WHERE plugin_id = :p"
                ),
                {"i": instance_id, "p": package_id},
            )
        for table in ("plugin_permission_grants", "plugin_credentials", "plugin_invocations"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table}_legacy"))
        if enabled_col:
            conn.execute(text("ALTER TABLE plugin_packages DROP COLUMN enabled"))


def _migrate_line_fields_are_lists() -> None:
    """声明为「行列表」的字段(`"lines": True`,目前是生成节点的输入素材)从多行文本改成列表。

    规范形状变了(见 workflows/normalization.canonicalize_line_fields):某一行可以是一整串引用
    (`{{角色三视图.results}}`),插值后是一组,多行文本装不下它。保存和导入已经只写列表;库里已存的
    在这里一次转好,编辑器只认列表,不为旧的多行文本留分支。

    只改表示、不改语义(按行拆开,空行丢掉)。排在修订迁移之前:它会发现图变了,追加一份修订并
    校正摘要,不覆盖旧快照。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.normalization import canonicalize_line_fields

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            normalized = canonicalize_line_fields(graph, node_types=NODE_TYPES)
            if normalized != graph:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(normalized, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_audio_engines_are_providers() -> None:
    """降噪、分离节点的 `engine` 从引擎名改成能力表的提供方 id(ADR 0032 第二步)。

    `auto` / 空 → 清掉(= 按运行者的默认);`ffmpeg` / `deepfilternet` / `rnnoise` / `demucs` → `builtin:<引擎>`。
    工作流(含循环体、子图里的)和画板上的能力设置(`form.abilities`)、生成器表单(`form.producer`)一并改。
    必须在 _migrate_workflow_revisions 之前:图变了,那一步会记一条新修订。规则抄在这里,迁移不跟着领域代码变。
    """
    targets = {"denoise_audio": {"ffmpeg", "deepfilternet", "rnnoise"}, "separate_audio": {"demucs"}}

    def fixed(node_type: str, config: Any) -> Any:
        if not isinstance(config, dict) or "engine" not in config:
            return config
        value = str(config.get("engine") or "").strip()
        rest = {key: one for key, one in config.items() if key != "engine"}
        if value in ("", "auto"):
            return rest
        if value in targets[node_type]:
            return {**rest, "engine": f"builtin:{value}"}
        return config

    def rewrite_graph(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            if node.get("type") in targets:
                config = fixed(str(node["type"]), config)
            for key, value in list(config.items()):
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite_graph(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes}

    def rewrite_canvas(canvas: Any) -> Any:
        if not isinstance(canvas, dict):
            return canvas
        items = []
        for item in canvas.get("items") or []:
            form = item.get("form") if isinstance(item, dict) else None
            if not isinstance(form, dict):
                items.append(item)
                continue
            form = dict(form)
            producer = str(form.get("producer") or "").removeprefix("node:")
            if producer in targets:
                form["config"] = fixed(producer, form.get("config"))
            abilities = form.get("abilities")
            if isinstance(abilities, dict):
                form["abilities"] = {
                    key: ({**ability, "config": fixed(key.removeprefix("node:"), ability.get("config"))}
                          if key.removeprefix("node:") in targets and isinstance(ability, dict) else ability)
                    for key, ability in abilities.items()
                }
            items.append({**item, "form": form})
        return {**canvas, "items": items}

    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, column, rewrite in (("workflows", "graph", rewrite_graph), ("boards", "canvas", rewrite_canvas)):
            if table not in tables:
                continue
            for row in conn.execute(text(f"SELECT id, {column} FROM {table}")).mappings().all():
                raw = row[column]
                try:
                    value = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                rewritten = rewrite(value)
                if rewritten != value:
                    conn.execute(text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                 {"value": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]})


def _migrate_transcription_engines_are_providers() -> None:
    """转写节点的 `engine` 从引擎名改成能力表的提供方 id(ADR 0032 第三步)。

    `auto` / 空 → 清掉(= 按运行者的默认);`funasr` / `whisperx` → `builtin:<引擎>`。工作流(含循环体、子图里的)
    和画板上的能力设置(`form.abilities`)、生成器表单(`form.producer`)一并改。必须在 _migrate_workflow_revisions
    之前:图变了,那一步会记一条新修订。规则抄在这里,迁移不跟着领域代码变。
    """
    node_type = "transcribe_asset"
    engines = {"funasr", "whisperx"}

    def fixed(config: Any) -> Any:
        if not isinstance(config, dict) or "engine" not in config:
            return config
        value = str(config.get("engine") or "").strip().lower()
        rest = {key: one for key, one in config.items() if key != "engine"}
        if value in ("", "auto"):
            return rest
        if value in engines:
            return {**rest, "engine": f"builtin:{value}"}
        return config

    def rewrite_graph(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            if node.get("type") == node_type:
                config = fixed(config)
            for key, value in list(config.items()):
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite_graph(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes}

    def rewrite_canvas(canvas: Any) -> Any:
        if not isinstance(canvas, dict):
            return canvas
        items = []
        for item in canvas.get("items") or []:
            form = item.get("form") if isinstance(item, dict) else None
            if not isinstance(form, dict):
                items.append(item)
                continue
            form = dict(form)
            if str(form.get("producer") or "").removeprefix("node:") == node_type:
                form["config"] = fixed(form.get("config"))
            abilities = form.get("abilities")
            if isinstance(abilities, dict):
                form["abilities"] = {
                    key: ({**ability, "config": fixed(ability.get("config"))}
                          if key.removeprefix("node:") == node_type and isinstance(ability, dict) else ability)
                    for key, ability in abilities.items()
                }
            items.append({**item, "form": form})
        return {**canvas, "items": items}

    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, column, rewrite in (("workflows", "graph", rewrite_graph), ("boards", "canvas", rewrite_canvas)):
            if table not in tables:
                continue
            for row in conn.execute(text(f"SELECT id, {column} FROM {table}")).mappings().all():
                raw = row[column]
                try:
                    value = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                rewritten = rewrite(value)
                if rewritten != value:
                    conn.execute(text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                 {"value": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]})


def _migrate_translation_engines_are_providers() -> None:
    """翻译节点(`translate`、`translate_lines`)的 `engine` 从 `google | ai` 改成能力表的提供方 id(ADR 0032 第三步)。

    `google` → `builtin:google`,`ai` → `builtin:chat`;**照原样留着点名**,不清成「按默认」—— 以前节点的缺省值就是
    写进去的 `google`,清掉的话以后他把默认定成一家收费插件,这些节点会悄悄跟着换过去。空的本来就没点名,不动。
    工作流(含循环体、子图里的)和画板上的能力设置、生成器表单一并改。必须在 _migrate_workflow_revisions 之前。
    规则抄在这里,迁移不跟着领域代码变。
    """
    node_types = {"translate", "translate_lines"}
    renamed = {"google": "builtin:google", "ai": "builtin:chat"}

    def fixed(config: Any) -> Any:
        if not isinstance(config, dict):
            return config
        value = str(config.get("engine") or "").strip().lower()
        return {**config, "engine": renamed[value]} if value in renamed else config

    def rewrite_graph(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            if node.get("type") in node_types:
                config = fixed(config)
            for key, value in list(config.items()):
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite_graph(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes}

    def rewrite_canvas(canvas: Any) -> Any:
        if not isinstance(canvas, dict):
            return canvas
        items = []
        for item in canvas.get("items") or []:
            form = item.get("form") if isinstance(item, dict) else None
            if not isinstance(form, dict):
                items.append(item)
                continue
            form = dict(form)
            if str(form.get("producer") or "").removeprefix("node:") in node_types:
                form["config"] = fixed(form.get("config"))
            abilities = form.get("abilities")
            if isinstance(abilities, dict):
                form["abilities"] = {
                    key: ({**ability, "config": fixed(ability.get("config"))}
                          if key.removeprefix("node:") in node_types and isinstance(ability, dict) else ability)
                    for key, ability in abilities.items()
                }
            items.append({**item, "form": form})
        return {**canvas, "items": items}

    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, column, rewrite in (("workflows", "graph", rewrite_graph), ("boards", "canvas", rewrite_canvas)):
            if table not in tables:
                continue
            for row in conn.execute(text(f"SELECT id, {column} FROM {table}")).mappings().all():
                raw = row[column]
                try:
                    value = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                rewritten = rewrite(value)
                if rewritten != value:
                    conn.execute(text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                 {"value": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]})


def _migrate_speech_engines_are_providers() -> None:
    """配音引擎从裸名改成能力表的提供方 id(ADR 0032 第四步):`clone` → `builtin:clone`,`edge` / `openai` /
    `volcano` / `alibaba` / `alibaba-cosyvoice` 同理;空的不动(画板的配音表单里空 = 克隆音色),认不出的
    (插件连接 id)原样留着。

    改四处:工作流里念字的五种节点(含循环体、子图)、画板(配音表单顶层的 `engine`、生成器表单与能力设置里
    这五种节点的 `config.engine`)、实体的 `voice_engine`、智能体语音偏好 `agent_voice_prefs.engine`。
    必须在 _migrate_workflow_revisions 之前。规则抄在这里,迁移不跟着领域代码变。
    """
    node_types = {"synthesize_speech", "dub_subtitles", "image_speak", "video_lipsync", "talking_segments"}
    engines = {"clone", "edge", "openai", "volcano", "alibaba", "alibaba-cosyvoice"}

    def renamed(value: Any) -> Any:
        return f"builtin:{value}" if isinstance(value, str) and value.strip() in engines else value

    def fixed(config: Any) -> Any:
        if not isinstance(config, dict) or "engine" not in config:
            return config
        return {**config, "engine": renamed(config["engine"])}

    def rewrite_graph(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            if node.get("type") in node_types:
                config = fixed(config)
            for key, value in list(config.items()):
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite_graph(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes}

    def rewrite_canvas(canvas: Any) -> Any:
        if not isinstance(canvas, dict):
            return canvas
        items = []
        for item in canvas.get("items") or []:
            form = item.get("form") if isinstance(item, dict) else None
            if not isinstance(form, dict):
                items.append(item)
                continue
            form = dict(form)
            producer = str(form.get("producer") or "")
            if producer == "speak" and "engine" in form:
                form["engine"] = renamed(form["engine"])
            if producer.removeprefix("node:") in node_types:
                form["config"] = fixed(form.get("config"))
            abilities = form.get("abilities")
            if isinstance(abilities, dict):
                form["abilities"] = {
                    key: ({**ability, "config": fixed(ability.get("config"))}
                          if key.removeprefix("node:") in node_types and isinstance(ability, dict) else ability)
                    for key, ability in abilities.items()
                }
            items.append({**item, "form": form})
        return {**canvas, "items": items}

    def rewrite_attributes(attributes: Any) -> Any:
        if not isinstance(attributes, dict) or "voice_engine" not in attributes:
            return attributes
        return {**attributes, "voice_engine": renamed(attributes["voice_engine"])}

    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, column, rewrite in (("workflows", "graph", rewrite_graph), ("boards", "canvas", rewrite_canvas),
                                       ("entities", "attributes", rewrite_attributes)):
            if table not in tables:
                continue
            for row in conn.execute(text(f"SELECT id, {column} FROM {table}")).mappings().all():
                raw = row[column]
                try:
                    value = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                rewritten = rewrite(value)
                if rewritten != value:
                    conn.execute(text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                 {"value": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]})
        if "agent_voice_prefs" in tables:
            for old in engines:
                conn.execute(text("UPDATE agent_voice_prefs SET engine = :new WHERE engine = :old"),
                             {"new": f"builtin:{old}", "old": old})


def _migrate_condition_literals_are_json() -> None:
    """条件节点两边手写的 `True` / `False` 改写成 `true` / `false`。

    值当文字用时此前是 `str()`:上游交来的布尔在条件里读作 `True`,用户照着看到的写了 `True`
    才对得上。现在统一写成 JSON(见 workflows.as_text),布尔读作 `true` —— 库里那些照旧写法
    写好的条件会从此永远不等。这里一次改好,条件节点不为旧写法留分支。

    只改**整格**就是这个字面量的(带引用、带别的字的不动),循环体 / 子图体里的一并改。排在修订
    迁移之前:它会发现图变了,追加一份修订。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    literals = {"True": "true", "False": "false"}

    def rewrite(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            if node.get("type") == "condition":
                for side in ("left", "right"):
                    value = config.get(side)
                    if isinstance(value, str) and value.strip() in literals:
                        config[side] = literals[value.strip()]
            for key, value in config.items():
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes}

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            rewritten = rewrite(graph)
            if rewritten != graph:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_condition_edges_use_source_handle() -> None:
    """边上的 `branch` 键改写成 `source_handle`。

    全片生成模板里五条条件边写的是 `"branch": "true"`,而没有任何代码读 `branch`:它们能按
    「真」那一支跑,只是因为没写 handle 的条件边缺省就是真;画布上也就没有真 / 假的标记。
    模板已经改成 `source_handle`;从它装出来的那些工作流在这里一次改好,编辑器和引擎只认
    `source_handle` 一种写法。

    从会分支的节点出发、还没写 handle 的,`branch` 的值搬进 `source_handle`;其余的只是把这个
    没人读的键删掉。循环体 / 子图体里的一并改。

    **改完自己把修订对上。** 排在修订迁移之前只在「两步同一次启动里都没跑过」时有用;修订迁移
    早已记过账的机器上它不会再跑,而当前图和最新快照的摘要对不上的工作流是**跑不起来的**
    (wfErr_revisionDigestMismatch)。修订迁移本身是可重入的(图变了就追加一份修订),改完就调它。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import BRANCHING_NODE_TYPES

    def rewrite(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        types = {
            str(node.get("id")): str(node.get("type"))
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
        }
        edges = []
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict) or "branch" not in edge:
                edges.append(edge)
                continue
            moved = {key: value for key, value in edge.items() if key != "branch"}
            if types.get(str(edge.get("source"))) in BRANCHING_NODE_TYPES and not edge.get("source_handle"):
                moved["source_handle"] = str(edge["branch"])
            edges.append(moved)
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            for key, value in config.items():
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes, "edges": edges}

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            rewritten = rewrite(graph)
            if rewritten != graph:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]},
                )
    _migrate_workflow_revisions()


def _migrate_loop_scopes_are_not_outer_data_edges() -> None:
    """把规范化错接成外层数据边的循环 / 子图 `output`、条件循环 `condition` 改回体内引用。

    规范化此前只跳过 object / graph 类型的字段,没排除内嵌子图节点的 output / condition —— 那两格
    属于**体内**作用域。节点 id 只在当前这一层唯一,外层和体内同名(`llm-1`)是常态,于是体内引用
    `{{llm-1.text}}` 被升级成一条**来自外层 llm-1** 的数据边、output 清空:遍历循环交出的是外层那
    一个值,条件循环的条件绑到了外层的布尔值上。

    被改写过的签名:目标是循环 / 子图、`target_input` 是它那一格体内字段的数据边。这种边不会是
    用户有意接的(外层一个值当每一轮的输出模板没有意义),一律删掉;那一格还是空的就恢复成
    `{{来源.输出}}`(规范化清空之前的原文),已经重填过的不动。节点的 `inputs` 端口列表里那一项一并摘掉。
    规范化折边时会把同一对节点间无 handle 的控制边当多余的折掉:删边后这一对之间什么边都不剩时,
    补回一条控制边 —— 保住它眼下的先后,和被折掉的那条正是同一条。循环体 / 子图体里的一并改。

    经 `_rewrite_workflow_graphs` 落成新的一版修订:作者沿用上一版、认可过上一版的人照样担保。此前是只改
    `workflows.graph` 再调修订迁移补一版 —— 那一版没有作者,带发布账号 / 浏览器档案 / 本机文件节点的工作流
    升级后跑到那一步就报「这一版没人担保」。改写规则在领域层的图升级里(graph_upgrade),导入旧文件、
    恢复旧修订用的是同一份。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows.graph_upgrade import inner_scope_fields_come_back

    _rewrite_workflow_graphs(inner_scope_fields_come_back, "循环 / 子图的体内 output、condition 被错接成了外层数据边:改回体内引用")


def _disable_tasks_bound_to_deleted_workflows() -> None:
    """绑着一张**已经删掉**的工作流、却还是「启用」的定时任务,停用。

    删工作流此前不管定时任务:任务仍是启用的,排程的到点照样触发、手动的照样能点「立即运行」,
    每一次都落一条「工作流不存在」的失败。删除路径现在会当场把它们停掉(scheduler.stop_tasks_bound_to_workflow),
    启用、触发也都先问一句跑不跑得起来 —— 库里已经留下的那些在这里一次停掉。

    只动开关和下次触发时刻,任务和它的运行记录都留着:删不删由人决定。别的工作区的同 id
    工作流不算「在」—— 执行体也不会去跑它。
    """
    present = set(inspect(engine).get_table_names())
    if not {"scheduled_tasks", "workflows"} <= present:
        return
    with engine.begin() as conn:
        existing = {(row[0], row[1]) for row in conn.execute(text("SELECT id, workspace_id FROM workflows"))}
        rows = conn.execute(
            text("SELECT id, workspace_id, payload FROM scheduled_tasks WHERE kind = 'workflow' AND enabled = 1")
        ).mappings().all()
        for row in rows:
            raw = row["payload"]
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                payload = None
            workflow_id = str(payload.get("workflow_id") or "") if isinstance(payload, dict) else ""
            if (workflow_id, row["workspace_id"]) in existing:
                continue
            conn.execute(
                text("UPDATE scheduled_tasks SET enabled = 0, next_run_at = NULL WHERE id = :id"),
                {"id": row["id"]},
            )
            logger.info("定时任务 %s 绑的工作流已不在,停用", row["id"])


def _migrate_job_keys_are_keys() -> None:
    """jobs 的 message_key / error_key 里只能是**文案 key**(或空)。

    改正之前(见 core/i18n.is_message_key),`WorkflowDomainError(str(exc))` 把第三方报错原文当 key,
    `blame()` 截成 80 字写进 error_key;读的时候拿它当模板 format,花括号一炸,整个执行历史接口 500。
    写入端已经不会再这么写了 —— 库里已有的那些在这里一次改掉,读取端只认新形状,不为旧行留分支。

    顺手救回失败原因:当年写 `error` 时,原文里花括号之后的部分被当成"填不上的占位符"抹掉了
    (只剩「调用 LLM失败:Error: 403」),而那半截"key"里还留着原文的前 80 个字 —— 比 `error`
    完整,就挪回 `error`。

    每次启动都跑、幂等:不变式是 key ∈ 文案表 ∪ {""},将来删掉某条文案时,引用它的旧行也会在
    这里被清掉(显示退回到落库时渲好的那句 message/error)。
    """
    from app.core.i18n import MESSAGES

    if "jobs" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, message_key, error_key, error FROM jobs WHERE message_key != '' OR error_key != ''")
        ).fetchall()
        for job_id, message_key, error_key, error in rows:
            if message_key and message_key not in MESSAGES:
                conn.execute(
                    text("UPDATE jobs SET message_key = '', message_params = '{}' WHERE id = :id"), {"id": job_id}
                )
            if error_key and error_key not in MESSAGES:
                recovered = error_key if len(error_key) > len(error or "") and error_key.startswith(error or "") else error
                conn.execute(
                    text("UPDATE jobs SET error_key = '', error_params = '{}', error = :error WHERE id = :id"),
                    {"error": recovered, "id": job_id},
                )


def _migrate_cancelled_jobs_get_their_own_status() -> None:
    """被停下的任务有了自己的终态 `cancelled`(ADR 0049)。此前记成 `failed` + `error_key = jobErr_cancelled`。

    - jobs:那样记的改成 `cancelled`,`error` / `error_key` / `error_params` 清空(取消没有原因可说),消息换成「已取消」
      (jobMsg_cancelled,按缺省语言渲染,读的时候按读的人的语言翻)。
    - scheduled_task_runs:任务已经是 `cancelled` 的跟着改成 `cancelled`,`error` 清空(运行记录此前抄的是任务的 failed)。
    - 生成记录(generation_jobs)不动:它显示「已停止」靠自己抄下的 error_key,那一套照旧。
    """
    from app.core.i18n import DEFAULT_LOCALE, render_message

    tables = set(inspect(engine).get_table_names())
    if "jobs" not in tables:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status = 'cancelled', error = NULL, error_key = '', error_params = '{}', "
                "message_key = 'jobMsg_cancelled', message_params = '{}', message = :message "
                "WHERE status = 'failed' AND error_key = 'jobErr_cancelled'"
            ),
            {"message": render_message("jobMsg_cancelled", DEFAULT_LOCALE, {})},
        )
        if "scheduled_task_runs" in tables:
            conn.execute(text(
                "UPDATE scheduled_task_runs SET status = 'cancelled', error = NULL "
                "WHERE status = 'failed' AND job_id IN (SELECT id FROM jobs WHERE status = 'cancelled')"
            ))


def _migrate_job_worker_leases() -> None:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if not columns:
            return
        for name, ddl in (
            ("lease_token", "ALTER TABLE jobs ADD COLUMN lease_token VARCHAR(64)"),
            ("lease_worker", "ALTER TABLE jobs ADD COLUMN lease_worker VARCHAR(64)"),
            ("lease_expires_at", "ALTER TABLE jobs ADD COLUMN lease_expires_at DATETIME"),
        ):
            if name not in columns:
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_status_lease_expires ON jobs(status, lease_expires_at)"))
        # **把最后半步走完。** 只加列不回填的话,那些"租约列还不存在时就已经 running"的行
        # 永远没有租约,于是读路径要长一条 `lease_expires_at IS NULL` 的兼容分支 ——
        # 而本仓库的规矩是不写兼容、旧数据用迁移(ADR-0006)。迁移停在最后一环之前,
        # 剩下的半步就变成了读路径上一条永久的税。
        #
        # 结局和 `expire_worker_leases` 对它们的处置一致:它们的执行器早就不在了
        # (这次升级重启过后端),判失败并说清原因。**不是重跑** —— 可能带副作用的活儿
        # 不自动重复,那是 jobs 模块从头就定的规矩。
        from app.domain.jobs import external_kinds

        #: `publish` 不在内:它有自己的一套认领(见 publish/worker),不走 job 的租约。
        kinds = [kind for kind in external_kinds() if kind != "publish"]
        if kinds and "error_key" in columns:
            placeholders = ", ".join(f":k{i}" for i in range(len(kinds)))
            conn.execute(
                text(
                    f"UPDATE jobs SET status = 'failed', error_key = 'jobErr_leaseExpired' "
                    f"WHERE status IN ('queued', 'running') AND lease_expires_at IS NULL "
                    f"AND kind IN ({placeholders})"
                ),
                {f"k{i}": kind for i, kind in enumerate(kinds)},
            )


def _migrate_model_structured_output() -> None:
    """模型行记得下「这个端点支不支持 json_schema」。

    此前没有任何地方写得下这件事,于是不支持的端点上 Schema 只是个事后本地校验,而用户看不出来 ——
    他在节点里写着 strict,实际跑的却是纯文本(见 domain/providers/structured_output)。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_models)"))}
        if columns and "structured_output" not in columns:
            conn.execute(text("ALTER TABLE provider_models ADD COLUMN structured_output BOOLEAN"))


def _migrate_clip_offline_asset() -> None:
    """片段记住"素材曾经是什么"。

    在此之前,被时间线引用的素材**删不掉**(接口直接 422,让用户先去每条序列里找出来删掉)。
    现在删得掉了,引用它的片段转成脱机占位 —— 而占位要显示成什么,全靠这一列里的那份快照。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}
        if columns and "offline_asset" not in columns:
            conn.execute(text("ALTER TABLE clips ADD COLUMN offline_asset JSON"))


def _migrate_clips_get_a_link_group() -> None:
    """片段多一列 `link_group`(链接组):同组的片段一起移动、修剪、切分、删除(见 sequences/links.py)。

    已有的片段都不在任何组里(NULL)。此前分离出去、还和画面对得严丝合缝的音频,由
    migrate-detached-audio-joins-its-video 补进同一组。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}
        if columns and "link_group" not in columns:
            conn.execute(text("ALTER TABLE clips ADD COLUMN link_group VARCHAR(64)"))


def _migrate_browser_profile_start_url() -> None:
    """通用档案记下下次从哪一页开(见 BrowserProfile.start_url)。老档案留空 —— 它们从没记过。"""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(browser_profiles)"))}
        if columns and "start_url" not in columns:
            conn.execute(text("ALTER TABLE browser_profiles ADD COLUMN start_url VARCHAR(2000)"))


def _migrate_usage_unpriced_reason() -> None:
    """用量事件记下「为什么没能定价」(见 ProviderUsageEvent.unpriced_reason)。

    老事件留空 —— 它们当时没问过这个问题,也补不出来。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_usage_events)"))}
        if columns and "unpriced_reason" not in columns:
            conn.execute(text("ALTER TABLE provider_usage_events ADD COLUMN unpriced_reason VARCHAR(40)"))


def _migrate_pricing_time_prices() -> None:
    """计价规则带上分时段价格(见 domain/billing/price_schedule)。

    老规则一律是「全天一个价」:时段为空列表、时区为空 —— 这正是它们一直以来的含义,不必猜。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_pricing_rules)"))}
        if not columns:
            return
        if "time_prices" not in columns:
            conn.execute(text("ALTER TABLE provider_pricing_rules ADD COLUMN time_prices JSON NOT NULL DEFAULT '[]'"))
        if "time_zone" not in columns:
            conn.execute(text("ALTER TABLE provider_pricing_rules ADD COLUMN time_zone VARCHAR(64) NOT NULL DEFAULT ''"))


def _migrate_pricing_rules_by_resolution() -> None:
    """计价规则多一格输出分辨率(见 ProviderPricingRule.resolution)。

    老规则一律是「不限分辨率」—— 这正是它们一直以来的含义:此前规则只能记一档,其余档写在备注里。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_pricing_rules)"))}
        if columns and "resolution" not in columns:
            conn.execute(text("ALTER TABLE provider_pricing_rules ADD COLUMN resolution VARCHAR(16) NOT NULL DEFAULT ''"))


def _drop_plugin_packages_that_break_the_manifest_rules() -> None:
    """插件清单的形状收紧了(id / 声明的工具名 / 配置与凭据的键,见 domain/plugins/manifest):库里存着的包记录
    若违反新规矩,`manifest_of` 读它就抛 —— 插件页、智能体工具表、工作流节点面板对**所有人**报错。

    这样的包本来也跑不了:id 是插件目录名(`../x` 会装到插件目录外面)、带点的工具名进不了节点类型、
    叫 `path` 的配置项会顶掉插件进程的 PATH。删掉包记录(它的连接、凭据、授权、调用记录随外键级联),
    每删一个记一条警告说是哪个、为什么。**磁盘上的目录不动**:作者改好清单之后重新扫描,它就回来。

    规矩在这里原样写一份(迁移体是那一刻的快照,不随以后的清单规矩变)。幂等:删过的不会再出现。
    """
    if "plugin_packages" not in set(inspect(engine).get_table_names()):
        return
    import re

    plugin_id = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    tool_name = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    field_key = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    reserved = {
        "PATH", "HOME", "LANG", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    }

    def why_broken(package_id: str, raw: Any) -> str:
        if not isinstance(raw, dict):
            return "manifest is not an object"
        declared_id = raw.get("id")
        for one in (package_id, declared_id.strip() if isinstance(declared_id, str) else ""):
            if not plugin_id.match(one):
                return f"invalid id {one!r}"
        tools = raw.get("tools")
        seen_tools: set[str] = set()
        for tool in (tools.get("declare") or []) if isinstance(tools, dict) else []:
            name = tool.get("name") if isinstance(tool, dict) else None
            if not isinstance(name, str):
                continue
            if not tool_name.match(name):
                return f"invalid tool name {name!r}"
            if name in seen_tools:
                return f"duplicate tool {name!r}"
            seen_tools.add(name)
        instance = raw.get("instance")
        seen_keys: set[str] = set()
        for group in ("config", "credentials"):
            fields = instance.get(group) if isinstance(instance, dict) else None
            for field in fields if isinstance(fields, list) else []:
                key = str(field.get("key") or "").strip() if isinstance(field, dict) else ""
                if not field_key.match(key):
                    continue  # 解析时本来就丢掉的键
                upper = key.upper()
                if upper in reserved or upper.startswith("MOSAEL_"):
                    return f"key {key!r} overrides a host environment variable"
                if upper in seen_keys:
                    return f"keys collide as {upper!r}"
                seen_keys.add(upper)
        return ""

    with engine.begin() as conn:
        for package_id, stored in conn.execute(text("SELECT id, manifest FROM plugin_packages")).all():
            try:
                raw = json.loads(stored) if isinstance(stored, str) else stored
            except ValueError:
                raw = None
            reason = why_broken(str(package_id), raw)
            if reason:
                logger.warning("插件包 %s 的清单不合新规矩(%s),删掉它的记录;改好清单后重新扫描即可", package_id, reason)
                conn.execute(text("DELETE FROM plugin_packages WHERE id = :id"), {"id": package_id})


def _migrate_named_browser_partitions_are_per_workspace() -> None:
    """具名浏览器会话的登录分区从 `persist:rpa-<清洗后的名字>` 改成 `persist:rpa-<工作区>-<原名哈希>`:
    写下每个旧分区该搬到哪(`browser_partition_moves`),由 Electron 执行器在磁盘上搬。

    旧名字跨工作区共用、非 ASCII 名字清洗后撞成一个(「xhs-主号」「xhs-副号」都是 `xhs`)。登录数据在
    Electron 的 `userData/Partitions/` 里,后端不知道那个目录在哪 —— 所以这里只算「谁搬到哪」,搬由执行器
    启动时做(electron/publish/partitionMoves.ts),搬完回报。

    一个旧分区只能归一处:
    - **用过它的工作区里最早的那个**(按那个工作区第一次开这个会话的时间)。别的工作区记一条 abandoned,写明原因 ——
      它们此前用的其实是同一份登录,那份登录归不了两家;
    - 名字:清洗把原名弄丢了(库里存的是清洗后的),从那个工作区的工作流里找「打开浏览器」节点写的原名
      (清洗后对得上的那些,按工作流创建先后);找不到(智能体开的、名字是引用)就用库里那个名字 —— 纯 ASCII
      的名字清洗前后本来就一样。对得上好几个原名(它们此前共用这一份登录)时归最早的那个,其余记 abandoned。

    清洗和新分区的算法都写死在这里:迁移是历史的快照,不跟着以后还会变的领域实现走。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"browser_sessions", "browser_partition_moves", "workflows"} <= tables:
        return

    def old_clean(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "-", (name or "").strip())[:64].strip("-")

    def new_partition(workspace_id: str, name: str) -> str:
        return f"persist:rpa-{workspace_id}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}"

    def named_openers(graph: Any) -> list[str]:
        """图里(连同循环体 / 子图)「打开浏览器」节点写的具名会话名,只要字面量。"""
        found: list[str] = []
        if not isinstance(graph, dict):
            return found
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            name = config.get("session_name")
            if (node.get("type") == "browser_open" and config.get("session_mode") == "named"
                    and isinstance(name, str) and name.strip() and "{{" not in name):
                found.append(name.strip())
            for value in config.values():
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    found.extend(named_openers(value))
        return found

    stamp = datetime.now(UTC).replace(tzinfo=None)
    with engine.begin() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM browser_partition_moves")).scalar_one():
            return
        rows = conn.execute(
            text(
                "SELECT workspace_id, name, partition, created_at FROM browser_sessions "
                "WHERE kind = 'named' ORDER BY created_at"
            )
        ).mappings().all()
        #: 旧分区(按 Electron 落盘的样子:转小写)→ 工作区 → (第一次用的时间, 库里存的名字)
        groups: dict[str, dict[str, tuple[Any, str]]] = {}
        for row in rows:
            stored = str(row["name"] or "")
            partition = str(row["partition"] or "")
            if not stored or partition != f"persist:rpa-{stored}":
                continue  # 已经是新形状的,或者不是这条规则造出来的
            per_workspace = groups.setdefault(partition.lower(), {})
            if row["workspace_id"] not in per_workspace:
                per_workspace[row["workspace_id"]] = (row["created_at"], stored)
        if not groups:
            return
        graphs: dict[str, list[str]] = {}
        for row in conn.execute(text("SELECT workspace_id, graph FROM workflows ORDER BY created_at")).mappings():
            try:
                graph = json.loads(row["graph"]) if isinstance(row["graph"], str) else row["graph"]
            except (TypeError, ValueError):
                continue
            graphs.setdefault(row["workspace_id"], []).extend(named_openers(graph))

        def record(old: str, new: str, workspace_id: str, name: str, status: str, reason: str) -> None:
            conn.execute(
                text(
                    "INSERT INTO browser_partition_moves "
                    "(id, old_partition, new_partition, workspace_id, session_name, status, reason, created_at, updated_at) "
                    "VALUES (:id, :old, :new, :ws, :name, :status, :reason, :now, :now)"
                ),
                {"id": uuid.uuid4().hex, "old": old, "new": new, "ws": workspace_id, "name": name[:80],
                 "status": status, "reason": reason, "now": stamp},
            )

        for old, per_workspace in groups.items():
            ordered = sorted(per_workspace.items(), key=lambda item: str(item[1][0]))
            winner, (_, stored) = ordered[0]
            key = old[len("persist:rpa-"):]
            names = list(dict.fromkeys(name for name in graphs.get(winner, []) if old_clean(name).lower() == key))
            chosen = names[0] if names else stored
            record(old, new_partition(winner, chosen), winner, chosen, "pending", "")
            for other in names[1:]:
                record(old, new_partition(winner, other), winner, other, "abandoned",
                       f"旧分区 {old} 同时被「{chosen}」和「{other}」用着(清洗后撞名),登录数据归了先出现的「{chosen}」")
            for workspace_id, (_, name) in ordered[1:]:
                record(old, "", workspace_id, name, "abandoned",
                       f"旧分区 {old} 也被工作区 {winner} 用过、而且更早,登录数据归了它;这个工作区的「{name}」要重新登录")
                logger.info("具名浏览器分区 %s 归工作区 %s,放弃工作区 %s 那份", old, winner, workspace_id)


def _migrate_browser_sessions_one_open_per_login() -> None:
    """一份登录(分区)上最多一个开着的具名 / 池档案会话:建局部唯一索引 `uq_browser_sessions_open_login`。

    租约此前只靠「先查后建」,同一拍的两次打开各建一个,同一份登录上开着两个会话(两次运行互相点、互相导航)。
    建索引之前先把已经撞上的收掉:每个分区留最早开的那个,其余落 closed、没跑完的动作落 failed ——
    不先收,建索引本身就会因为重复而失败。全新安装由 create_all 按模型建好,这里 IF NOT EXISTS 什么也不做。
    """
    if "browser_sessions" not in set(inspect(engine).get_table_names()):
        return
    login = "status = 'open' AND kind IN ('named', 'profile')"
    with engine.begin() as conn:
        rows = conn.execute(
            text(f"SELECT id, partition FROM browser_sessions WHERE {login} ORDER BY created_at, id")
        ).all()
        kept: set[str] = set()
        extras: list[str] = []
        for session_id, partition in rows:
            if partition in kept:
                extras.append(session_id)
            else:
                kept.add(partition)
        for session_id in extras:
            conn.execute(text("UPDATE browser_sessions SET status = 'closed' WHERE id = :id"), {"id": session_id})
            conn.execute(
                text(
                    "UPDATE browser_actions SET status = 'failed', error = 'browserErr_sessionClosed' "
                    "WHERE session_id = :id AND status IN ('queued', 'running')"
                ),
                {"id": session_id},
            )
        if extras:
            logger.info("同一份登录上开着多个浏览器会话,收掉后开的 %d 个", len(extras))
        conn.execute(
            text(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_browser_sessions_open_login ON browser_sessions (partition) WHERE {login}")
        )


def _migrate_partition_moves_are_settled_per_executor() -> None:
    """登录分区搬家单的「搬没搬」改成每台电脑各记各的(`browser_partition_move_receipts`):已经落了 done / skipped
    的单回到 pending。

    此前一条单只有一个全局状态,第一个连上来的执行器领走就落终态 —— 旧目录不在它那台电脑上就记 skipped,
    真正有那份登录的电脑再也领不到。回到 pending 是安全的:搬过的那台再看一眼,旧目录已经不在,什么也不做;
    别的电脑上旧目录还在的,这回轮得到它们搬。abandoned 是迁移时的决定,不动。
    """
    if "browser_partition_moves" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE browser_partition_moves SET status = 'pending', reason = '' WHERE status IN ('done', 'skipped')")
        )


def _rewrite_workflow_graphs(rewrite: Any, note: Any, *, only: Any = None) -> int:
    """把每个工作流的当前图过一遍 `rewrite`(连同循环体 / 子图,由 `rewrite` 自己走);变了的追加一版修订。

    修订表建好之后的图迁移都得这么落(`workflows.graph` 是最新修订的投影,只改投影会让两边对不上):
    作者沿用上一版,认可过上一版的人照样为这一版担保 —— 机械改写不换担保人,也不该让跑得好好的流程停下来等人认可
    (同 domain/workflows/plugin_references)。`only(workflow)` 给了的话,只看它说是的那些。`note` 可以是一个函数
    (改写前的图 → 说明),说明里要点名这一张图里的哪几个节点时用。
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Workflow, WorkflowRevisionAttestation
    from app.domain.workflows.revisions import commit_graph_revision, current_workflow_revision, revision_vouchers

    changed = 0
    with Session(engine) as db:
        for workflow in db.scalars(select(Workflow)).all():
            if only is not None and not only(workflow):
                continue
            if rewrite(json.loads(json.dumps(workflow.graph))) == workflow.graph:
                continue
            previous = current_workflow_revision(db, workflow)
            vouchers = revision_vouchers(db, previous)
            revision = commit_graph_revision(
                db, workflow, rewrite, source="migration", created_by=previous.created_by,
                note=note(workflow.graph) if callable(note) else note,
            )
            if revision is not None:
                for user in vouchers - {revision.created_by}:
                    db.add(WorkflowRevisionAttestation(revision_id=revision.id, user_id=user))
                changed += 1
        db.commit()
    return changed


def _migrate_migration_revisions_keep_their_vouchers() -> None:
    """迁移落下的、没有作者的修订,补上上一版的作者,认可过上一版的人照样为它担保。

    1.8.1 的循环作用域迁移(和更早的条件边迁移)只改 `workflows.graph`,再由修订迁移把改动记成新的一版 ——
    那一版 `created_by` 为空、也不带认可。一次运行要用私有发布账号 / 浏览器档案 / 本机文件时,被执行那一版
    得有人担保(见 domain/authority),于是这些工作流升级之后一跑到那一步就失败,而用户什么都没改过。

    机械改写不换担保人(和 `_rewrite_workflow_graphs` 同一条):作者取紧挨着的上一版的作者,认可照抄。
    按版本号从小到大补,连着几版都是迁移落的,也一版一版接上。没有上一版的(老数据的第一版)不动 ——
    那些由 `_backfill_workflow_revision_authors` 管。重跑时没有可补的,什么都不做。
    """
    if not {"workflow_revisions", "workflow_revision_attestations"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import WorkflowRevision, WorkflowRevisionAttestation
    from app.domain.workflows.revisions import revision_vouchers

    with Session(engine) as db:
        orphans = db.scalars(
            select(WorkflowRevision)
            .where(WorkflowRevision.source == "migration", WorkflowRevision.created_by.is_(None))
            .order_by(WorkflowRevision.workflow_id, WorkflowRevision.revision)
        ).all()
        for revision in orphans:
            previous = db.scalar(
                select(WorkflowRevision)
                .where(WorkflowRevision.workflow_id == revision.workflow_id, WorkflowRevision.revision < revision.revision)
                .order_by(WorkflowRevision.revision.desc())
                .limit(1)
            )
            if previous is None:
                continue
            vouchers = revision_vouchers(db, previous)
            revision.created_by = previous.created_by
            for user in vouchers - revision_vouchers(db, revision) - {previous.created_by}:
                db.add(WorkflowRevisionAttestation(revision_id=revision.id, user_id=user))
            # 下一版若也是迁移落的,它的「上一版」就是这一版:先落下,查得到。
            db.flush()
        db.commit()


def _migrate_start_required_params_are_a_list() -> None:
    """开始节点的必填参数(`required_params`)从一串逗号分隔的名字改成参数名的列表。

    面板上必填改成了每一行参数自己的开关,改名、删行时跟着那一行走;一串字表示不了「这一行」。点名了却没有那一行的
    参数补成一行(默认空着):它照旧是必填,运行前照旧拦,只是现在面板上看得见。改写规则在领域层的图升级里
    (graph_upgrade.start_required_params_become_a_list),导入旧文件、恢复旧修订用的是同一份。经
    `_rewrite_workflow_graphs` 落成新的一版修订:作者沿用上一版、认可过上一版的人照样担保。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows.graph_upgrade import start_required_params_become_a_list

    _rewrite_workflow_graphs(
        start_required_params_become_a_list,
        "开始节点的必填参数改成每一行参数自己的开关:逗号分隔的名字改成参数名的列表(点名了却没有那一行的补一行)",
    )


def _migrate_plugin_node_names_follow_the_plugin() -> None:
    """插件节点上写死的、就是那个工具名字的节点名清掉:名字空着,画布、检查器、引用、执行历史跟着插件**此刻**报的名字走。

    「添加节点」此前把插件工具当时的名字写进了节点(`name`)。插件报的名字会变 —— ComfyUI 工作流起了精简表单标题,
    「工作流 · krea2-text-2-image」就成了「工作流 · 快速用krea2生图」(模型下拉里早就叫这个),画布上的节点却还是文件名。
    现在加节点不写死(前端 useWorkflowCanvasEdits.newNode);存着的节点在这里跟上:名字等于这个工具在**升级前缓存的**
    清单里的名字(按语言分的每一种都算 —— 加节点时按界面语言取的)就清掉;用户自己改过的名字留着,认不出工具的节点不动。
    启动时先跑迁移、再刷新清单,所以比对的是加节点那时插件报的名字。经 `_rewrite_workflow_graphs` 落一版修订。
    """
    if not {"workflows", "workflow_revisions", "plugin_instances"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import PluginInstance
    from app.domain.plugins.tools import all_tools

    def variants(value: Any) -> set[str]:
        if isinstance(value, dict):
            return {one.strip() for one in value.values() if isinstance(one, str) and one.strip()}
        return {value.strip()} if isinstance(value, str) and value.strip() else set()

    defaults: dict[str, set[str]] = {}
    with Session(engine) as db:
        for instance in db.scalars(select(PluginInstance)).all():
            try:
                tools = all_tools(db, instance)
            except ValueError:  # 包记录没了、清单坏了(PluginDomainError / ManifestError 都是 ValueError)
                continue
            #: 运行时报出的工具原样存着(名字按语言分),all_tools 只给此刻这一种语言
            raw = {str(tool.get("name")): tool for tool in instance.discovered_tools or [] if isinstance(tool, dict)}
            for tool in tools:
                names = variants(tool.get("label")) | variants((raw.get(tool["name"]) or {}).get("label"))
                defaults.setdefault(f"plugin.{instance.package_id}.{tool['name']}", set()).update(names)
    if not defaults:
        return

    def visit(node: dict[str, Any]) -> dict[str, Any]:
        name = node.get("name")
        if not isinstance(name, str) or name.strip() not in defaults.get(str(node.get("type")), ()):
            return node
        return {key: value for key, value in node.items() if key != "name"}

    changed = _rewrite_workflow_graphs(
        lambda graph: _walk_graph_nodes(graph, visit),
        "插件节点的名字不再写死:就是插件给这个工具起的名字的,清掉,跟着插件此刻报的名字走(用户改过的名字留着)",
    )
    if changed:
        logger.info("%d 个工作流里写死的插件节点名清掉了,跟着插件报的名字走", changed)


def _walk_graph_nodes(graph: Any, visit: Any) -> Any:
    """一张图(连同循环体 / 子图体)里的每个节点交给 `visit(node) -> node`,返回新图。不改原图。"""
    if not isinstance(graph, dict):
        return graph
    nodes = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            nodes.append(node)
            continue
        config = dict(node.get("config") or {})
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                config[key] = _walk_graph_nodes(value, visit)
        nodes.append(visit({**node, "config": config}))
    return {**graph, "nodes": nodes}


#: 一段引用。和 workflows.VARIABLE_RE 同一个写法,写死在这里:迁移是历史的快照。
_CODE_REFERENCE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def _migrate_browser_nodes_fill_one_target_keeping_reference_fallbacks() -> None:
    """「点击」的选择器 / 文字、「等待」的元素 / 网址 / 文字改成只能填一样(`one_of`):两样都填了的老节点,
    只留执行器此前实际用的那一样 —— **除非前面那一样是纯引用**(只有 `{{…}}`、没有字面文字)。

    执行器一直是按先后取的:点击先认选择器,等待按「元素 → 网址 → 文字」,取的是**插值之后**第一个非空的。
    前面那格是字面量时,后面那几格从来没起过作用,清掉它们行为不变。前面那格是纯引用时就不是了:引用在运行时
    取到空,执行器落到后面那一格 —— 那是一个真在起作用的兜底。

    此前的那一步(migrate-browser-nodes-fill-one-target)按字面量判「填了」,把这种兜底也删了:引用取空的那次
    运行,行为悄悄变了。这一步取代它:还没升级过的库只删真正不起作用的那几格;纯引用 + 兜底的节点原样留着,
    运行前检查会说「只能填一个」,由人决定,而不是替人删掉。已经被那一步删掉的兜底不在这里恢复(见提交说明)。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    precedence = {"browser_click": ("selector", "text"), "browser_wait": ("selector", "url_contains", "text")}

    def reference_only(value: Any) -> bool:
        return isinstance(value, str) and bool(_CODE_REFERENCE.search(value)) and not _CODE_REFERENCE.sub("", value).strip()

    def visit(node: dict[str, Any]) -> dict[str, Any]:
        order = precedence.get(str(node.get("type")))
        config = node["config"]
        if not order:
            return node
        filled = [key for key in order if config.get(key) not in (None, "")]
        #: 执行器用得到的:从头数到第一个字面量为止(含);它后面的那几格永远轮不到
        used = next((i for i, key in enumerate(filled) if not reference_only(config[key])), len(filled) - 1)
        unused = filled[used + 1:]
        if not unused:
            return node
        return {**node, "config": {key: value for key, value in config.items() if key not in unused}}

    _rewrite_workflow_graphs(
        lambda graph: _walk_graph_nodes(graph, visit),
        "浏览器节点的点击目标 / 等待条件改成只填一样:清掉执行器此前就没用到的那几格(纯引用后面的兜底留着)",
    )


#: 1.8.1 那条浏览器「只填一样」迁移(migrate-browser-nodes-fill-one-target,已被上面那条取代)落的修订说明 ——
#: 它把纯引用后面的兜底也删了;恢复兜底的迁移据此找到它删掉了什么。
_BROWSER_ONE_TARGET_NOTE = "浏览器节点的点击目标 / 等待条件改成只填一样:清掉执行器此前就没用到的那几格"


def _nodes_by_path(graph: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], dict[str, Any]]:
    """一张图(连同循环体 / 子图体)里的节点,按「容器 id … 节点 id」的路径索引 —— 节点 id 只在一层里唯一。"""
    found: dict[tuple[str, ...], dict[str, Any]] = {}
    if not isinstance(graph, dict):
        return found
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        path = (*prefix, str(node.get("id")))
        found[path] = node
        for value in (node.get("config") or {}).values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                found.update(_nodes_by_path(value, path))
    return found


def _bound_by_path(graph: Any, prefix: tuple[str, ...] = ()) -> set[tuple[tuple[str, ...], str]]:
    """哪些 (节点路径, 字段) 接了数据边 —— 和 `_nodes_by_path` 同一种路径。"""
    bound: set[tuple[tuple[str, ...], str]] = set()
    if not isinstance(graph, dict):
        return bound
    for edge in graph.get("edges") or []:
        if isinstance(edge, dict) and edge.get("kind") == "data" and edge.get("target_input"):
            bound.add(((*prefix, str(edge.get("target"))), str(edge["target_input"])))
    for node in graph.get("nodes") or []:
        if isinstance(node, dict):
            for value in (node.get("config") or {}).values():
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    bound |= _bound_by_path(value, (*prefix, str(node.get("id"))))
    return bound


def _migrate_browser_fallback_targets_come_back() -> None:
    """浏览器「只填一样」那条迁移删掉的**兜底**,从修订历史里找回来。

    那条迁移把点击 / 等待里多填的格子一律清掉,只留执行器先认的那一格 —— 可「选择器写 `{{上游.选择器}}`、
    文字填一个兜底」是有意的:上游给空时执行器按顺序落到文字那格。one_of 现在认这种写法(见
    graph_rules.one_of_errors),被删的兜底在这里补回去。

    原值在那条迁移那一版的**前一版**修订里。只补「当前图里那个节点还在(按容器 … 节点的路径认)、那一格现在
    空着、前一版里有值」的,而且补上之后那一组得是合法的「引用在前、兜底在后」—— 两格都是字面量的,执行器
    本来就只认第一格,补回去只会让运行前校验报「只能填一个」。补过的不再空着,重跑不动。作者和担保人沿用上一版。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import WorkflowRevision
    from app.domain.workflows import NODE_TYPES, one_of_errors
    from app.domain.workflows.graph_rules import blank

    fields = {"browser_click": ("selector", "text"), "browser_wait": ("selector", "url_contains", "text")}
    lost: dict[str, dict[tuple[str, ...], dict[str, Any]]] = {}
    with Session(engine) as db:
        stripped = db.scalars(
            select(WorkflowRevision).where(
                WorkflowRevision.source == "migration", WorkflowRevision.note == _BROWSER_ONE_TARGET_NOTE
            )
        ).all()
        for revision in stripped:
            previous = db.scalar(
                select(WorkflowRevision)
                .where(WorkflowRevision.workflow_id == revision.workflow_id, WorkflowRevision.revision < revision.revision)
                .order_by(WorkflowRevision.revision.desc())
                .limit(1)
            )
            if previous is None:
                continue
            before, after = _nodes_by_path(previous.graph), _nodes_by_path(revision.graph)
            for path, node in after.items():
                keys = fields.get(str(node.get("type")))
                old = before.get(path)
                if not keys or old is None or old.get("type") != node.get("type"):
                    continue
                removed = {
                    key: (old.get("config") or {})[key] for key in keys
                    if not blank((old.get("config") or {}).get(key)) and blank((node.get("config") or {}).get(key))
                }
                if removed:
                    lost.setdefault(revision.workflow_id, {}).setdefault(path, {}).update(removed)

    def restore(found: dict[tuple[str, ...], dict[str, Any]]) -> Any:
        def rewrite(graph: Any) -> Any:
            graph = json.loads(json.dumps(graph))
            nodes, bound = _nodes_by_path(graph), _bound_by_path(graph)
            for path, values in found.items():
                node = nodes.get(path)
                if node is None or not isinstance(node.get("config"), dict):
                    continue
                config = node["config"]
                wired = {(path[-1], key) for (where, key) in bound if where == path}
                candidate = {
                    **config,
                    **{key: value for key, value in values.items()
                       if blank(config.get(key)) and (path[-1], key) not in wired},
                }
                specs = NODE_TYPES[str(node.get("type"))]["config"]
                if candidate != config and not one_of_errors(path[-1], candidate, specs, wired):
                    node["config"] = candidate
            return graph

        return rewrite

    for workflow_id, found in lost.items():
        _rewrite_workflow_graphs(
            restore(found),
            "浏览器节点「引用在前、兜底在后」的兜底找回来(只填一样那次迁移删掉的)",
            only=lambda workflow, wanted=workflow_id: workflow.id == wanted,
        )


def _migrate_code_fields_read_references_from_input() -> None:
    """代码字段(「执行脚本」的 expression、「代码」节点的 code)不再插值 `{{…}}`:里面已有的引用挪进节点的入参
    (`input`),代码改成读入参。

    插值此前是按文字拼进代码的 —— 上游交来一段带引号的文字就能改写整段脚本,而「执行脚本」跑在用户已登录的
    网页里。现在代码原样执行,上游的值作为数据交进去(见 workflows.binding、electron 的 scriptWithInput)。
    入参里的键由引用路径起名(`llm-1.text` → `llm_1_text`),和已有的键撞了就加序号;同一个引用只占一个键。
    改写规则在领域层的图升级里(graph_upgrade.code_references_read_input;字符串里的引用读成和插值同义的
    文字,只改根指得到东西的引用),导入旧文件、恢复旧修订用的是同一份。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows.graph_upgrade import code_references_read_input

    def note(graph: Any) -> str:
        skipped: list[str] = []
        code_references_read_input(graph, skipped=skipped)
        if not skipped:
            return _CODE_FIELDS_NOTE
        return f"{_CODE_FIELDS_NOTE}。{_SCRIPT_DECLARES_INPUT_NOTE}" + "、".join(skipped)

    _rewrite_workflow_graphs(code_references_read_input, note)


#: 代码字段迁移落的那一版修订的说明(开头)—— 修正迁移据此认出哪些工作流被它改写过。
_CODE_FIELDS_NOTE = "代码字段不再替换 {{…}}:代码里的引用挪进入参(input),代码改成读入参"
#: 自己声明了 input 的「执行脚本」没改(改了读到的是脚本自己的变量),说明里点名它们。
_SCRIPT_DECLARES_INPUT_NOTE = (
    "这些「执行脚本」自己声明了 input,改成读入参会读到脚本自己的变量,所以没改 —— 里面的 {{…}} 不会被替换,"
    "请把脚本里的 input 改个名字、再从 input 读上游的值:"
)


def _migrate_scripts_declaring_input_go_back() -> None:
    """1.8.1 的代码字段迁移把**自己声明了 input** 的「执行脚本」也改成了读 `input.k`:改回迁移之前的样子,并说出来。

    「执行脚本」包在 `with ({input: …}) { 脚本 }` 里跑,脚本自己的 `const input = …`(或叫 input 的参数)盖住
    交进来的那个,`input.k` 读到的是脚本自己的变量 —— 静默取空,而且看不出来。那次改写之后的代码在这种脚本里
    没有一处是对的;改回迁移前的原文(连同入参),修订说明里点名这几个节点,让人去改名。

    只改「迁移之后没人动过」的:当前图里那个节点(按容器 … 节点的路径认)的脚本和入参还是迁移那一版的样子。
    改回去之后不再是那一版的样子,重跑不动。作者和担保人沿用上一版。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import WorkflowRevision
    from app.domain.workflows.code_references import declares_input

    originals: dict[str, dict[tuple[str, ...], tuple[dict[str, Any], dict[str, Any]]]] = {}
    with Session(engine) as db:
        migrated = db.scalars(
            select(WorkflowRevision).where(
                WorkflowRevision.source == "migration", WorkflowRevision.note.startswith(_CODE_FIELDS_NOTE)
            )
        ).all()
        for revision in migrated:
            previous = db.scalar(
                select(WorkflowRevision)
                .where(WorkflowRevision.workflow_id == revision.workflow_id, WorkflowRevision.revision < revision.revision)
                .order_by(WorkflowRevision.revision.desc())
                .limit(1)
            )
            if previous is None:
                continue
            before = _nodes_by_path(previous.graph)
            for path, node in _nodes_by_path(revision.graph).items():
                old = before.get(path)
                if node.get("type") != "browser_evaluate" or old is None or old.get("type") != "browser_evaluate":
                    continue
                old_config, new_config = old.get("config") or {}, node.get("config") or {}
                script = old_config.get("expression")
                if isinstance(script, str) and declares_input(script) and new_config != old_config:
                    originals.setdefault(revision.workflow_id, {})[path] = (old_config, new_config)

    def go_back(found: dict[tuple[str, ...], tuple[dict[str, Any], dict[str, Any]]]) -> Any:
        def rewrite(graph: Any) -> Any:
            graph = json.loads(json.dumps(graph))
            nodes = _nodes_by_path(graph)
            for path, (before, after) in found.items():
                node = nodes.get(path)
                config = node.get("config") if node is not None else None
                if not isinstance(config, dict) or any(config.get(key) != after.get(key) for key in ("expression", "input")):
                    continue
                restored = {key: value for key, value in config.items() if key not in ("expression", "input")}
                restored.update({key: before[key] for key in ("expression", "input") if key in before})
                node["config"] = restored
            return graph

        return rewrite

    for workflow_id, found in originals.items():
        _rewrite_workflow_graphs(
            go_back(found),
            _SCRIPT_DECLARES_INPUT_NOTE + "、".join(path[-1] for path in found),
            only=lambda workflow, wanted=workflow_id: workflow.id == wanted,
        )


def _migrate_code_string_reads_keep_their_text() -> None:
    """1.8.1 的代码字段迁移把字符串里的引用改成了 `str(inputs["k"])` / `String(input.k)`,意思变了:改回同义的写法。

    插值把值写成文字走的是 workflows.as_text(对象 / 列表 / 布尔写成 JSON、None 写成空串),`str()` / `String()`
    不是 —— 迁过的老代码里 `json.loads('{{llm.obj}}')` 拿到 Python 的 repr 当场崩、`'{{c.result}}' == 'true'`
    永远是假;JS 模板字符串里的 `${ {{a.n}} * 2 }` 被改成了 `${ ${input.a_n} * 2 }`,语法错误。

    只动**那次迁移改写过的工作流**(有一版修订的说明是它的那句)里、**它起的入参**(值是一整个 `{{…}}`)、
    **它产出的精确形态**(见 code_references.string_reads_keep_their_text);改过的不再是那几种形态,重跑不动。
    作者和担保人沿用上一版(_rewrite_workflow_graphs)。
    """
    if not {"workflows", "workflow_revisions"} <= set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows.code_references import REFERENCE, declares_input, string_reads_keep_their_text

    with engine.begin() as conn:
        touched = {
            row[0] for row in conn.execute(
                text("SELECT DISTINCT workflow_id FROM workflow_revisions WHERE source = 'migration' AND note LIKE :note"),
                {"note": _CODE_FIELDS_NOTE + "%"},
            )
        }
    if not touched:
        return
    fields = {"browser_evaluate": ("expression", "js"), "code": ("code", "python")}

    def visit(node: dict[str, Any]) -> dict[str, Any]:
        spec = fields.get(str(node.get("type")))
        config = node["config"]
        given = config.get("input") if isinstance(config.get("input"), dict) else {}
        keys = {key for key, value in given.items() if isinstance(value, str) and REFERENCE.fullmatch(value)}
        if not spec or not keys or not isinstance(config.get(spec[0]), str):
            return node
        if spec[1] == "js" and declares_input(config[spec[0]]):
            return node  # 读 input.k 本身就是错的,由 migrate-scripts-declaring-input-go-back 改回原文
        code = string_reads_keep_their_text(config[spec[0]], spec[1], keys)
        return node if code == config[spec[0]] else {**node, "config": {**config, spec[0]: code}}

    _rewrite_workflow_graphs(
        lambda graph: _walk_graph_nodes(graph, visit),
        "代码字段里字符串处的引用读回和插值同义的文字(对象 / 列表 / 布尔写成 JSON、空值是空串)",
        only=lambda workflow: workflow.id in touched,
    )


def _migrate_plugin_array_inputs_are_lists() -> None:
    """插件节点上声明成数组(非素材)的入参,存成了「名字 → 值」对象的,改成那些值的列表。

    节点表单此前把 JSON Schema 的 array 当 object,给的是映射编辑器,存下去的是 `{"a": "第一段", "b": "第二段"}`
    —— 交给插件的就不是数组。表单改成一行一项(见 plugins.nodes 的 `_SCHEMA_TYPES`),存着的值在这里跟上:
    按用户敲进去的顺序取值。哪一格是数组看**插件此刻报的** input_schema(连接的工具清单);认不出工具的节点不动。
    """
    if not {"workflows", "workflow_revisions", "plugin_instances"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import PluginInstance
    from app.domain.plugins.tools import all_tools

    arrays: dict[str, set[str]] = {}
    with Session(engine) as db:
        for instance in db.scalars(select(PluginInstance)).all():
            try:
                tools = all_tools(db, instance)
            except ValueError:  # 包记录没了、清单坏了(PluginDomainError / ManifestError 都是 ValueError)
                continue
            for tool in tools:
                properties = (tool.get("input_schema") or {}).get("properties") or {}
                keys = {
                    key for key, spec in properties.items()
                    if isinstance(spec, dict) and spec.get("type") == "array"
                    and not (isinstance(spec.get("items"), dict) and spec["items"].get("format") == "asset")
                }
                if keys:
                    arrays.setdefault(f"plugin.{instance.package_id}.{tool['name']}", set()).update(keys)
    if not arrays:
        return

    def visit(node: dict[str, Any]) -> dict[str, Any]:
        keys = arrays.get(str(node.get("type")))
        config = node["config"]
        stale = [key for key in keys or () if isinstance(config.get(key), dict)]
        if not stale:
            return node
        return {**node, "config": {**config, **{key: list(config[key].values()) for key in stale}}}

    _rewrite_workflow_graphs(
        lambda graph: _walk_graph_nodes(graph, visit),
        "插件节点的数组入参改成一行一项:存成「名字 → 值」的,按顺序改成值的列表",
    )


def _plugin_array_inputs_follow_their_declarations() -> None:
    """对账:插件节点的数组入参还存成「名字 → 值」对象的,按插件**此刻**报出的声明改成值的列表。

    一次性的那条(migrate-plugin-array-inputs-are-lists)只改得了它跑的那一刻认得出的 —— 那一刻连接停着、
    工具清单还没报上来的,节点原样留下,跑的时候交给插件的还是一个对象。清单会变,所以这是对账:每次启动按
    当前的声明(plugins.nodes 的节点类型,数组是 `"type": "list"`)走一遍规范化里的同一步
    (normalization.canonicalize_list_fields);没有可改的就什么都不做。改了的落一版修订,作者和担保人沿用上一版。
    """
    if not {"workflows", "workflow_revisions", "plugin_instances"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy.orm import Session

    from app.domain.plugins.nodes import plugin_node_types
    from app.domain.workflows.normalization import canonicalize_list_fields

    with Session(engine) as db:
        types = plugin_node_types(db)
    if not any(
        isinstance(spec, dict) and spec.get("type") == "list"
        for declared in types.values()
        for spec in (declared.get("config") or {}).values()
    ):
        return
    _rewrite_workflow_graphs(
        lambda graph: canonicalize_list_fields(graph, node_types=types),
        "插件节点的数组入参改成一行一项:存成「名字 → 值」的,按顺序改成值的列表",
    )


def _migrate_board_plugin_array_inputs_are_lists() -> None:
    """画板格子上插件工具的设置里,声明成数组(非素材)的入参存成了「名字 → 值」对象的,改成值的列表。

    和工作流那一条(`migrate-plugin-array-inputs-are-lists`)同一个起因:节点表单此前把 array 当 object。画板上存
    设置的地方是空格子的生成器(`form.producer` = `node:plugin.…`,设置在 `form.config`)和内容格的能力
    (`form.abilities["node:plugin.…"].config`)。哪一格是数组看插件此刻报的 input_schema;认不出工具的不动。
    改过的画板 revision +1(画板的并发写靠它判)。
    """
    if not {"boards", "plugin_instances"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Board, PluginInstance
    from app.domain.plugins.tools import all_tools

    arrays: dict[str, set[str]] = {}
    with Session(engine) as db:
        for instance in db.scalars(select(PluginInstance)).all():
            try:
                tools = all_tools(db, instance)
            except ValueError:
                continue
            for tool in tools:
                properties = (tool.get("input_schema") or {}).get("properties") or {}
                keys = {
                    key for key, spec in properties.items()
                    if isinstance(spec, dict) and spec.get("type") == "array"
                    and not (isinstance(spec.get("items"), dict) and spec["items"].get("format") == "asset")
                }
                if keys:
                    arrays.setdefault(f"node:plugin.{instance.package_id}.{tool['name']}", set()).update(keys)
        if not arrays:
            return

        def fixed(producer: Any, config: Any) -> Any:
            """一份设置的 config 改好的样子;不用改回 None。"""
            keys = arrays.get(str(producer or ""))
            if not keys or not isinstance(config, dict):
                return None
            stale = [key for key in keys if isinstance(config.get(key), dict)]
            if not stale:
                return None
            return {**config, **{key: list(config[key].values()) for key in stale}}

        for board in db.scalars(select(Board)).all():
            canvas = board.canvas if isinstance(board.canvas, dict) else {}
            items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
            touched = False
            new_items = []
            for item in items:
                form = item.get("form") if isinstance(item, dict) and isinstance(item.get("form"), dict) else None
                if form is None:
                    new_items.append(item)
                    continue
                new_form = dict(form)
                own = fixed(form.get("producer"), form.get("config"))
                if own is not None:
                    new_form["config"] = own
                abilities = form.get("abilities") if isinstance(form.get("abilities"), dict) else {}
                new_abilities = {}
                for producer, setting in abilities.items():
                    config = fixed(producer, setting.get("config") if isinstance(setting, dict) else None)
                    new_abilities[producer] = {**setting, "config": config} if config is not None else setting
                if abilities and new_abilities != abilities:
                    new_form["abilities"] = new_abilities
                if new_form != form:
                    touched = True
                    new_items.append({**item, "form": new_form})
                else:
                    new_items.append(item)
            if touched:
                board.canvas = {**json.loads(json.dumps(canvas)), "items": new_items}
                board.revision = (board.revision or 0) + 1
        db.commit()


def _migrate_plugin_union_array_inputs_are_lists() -> None:
    """插件节点上声明成**联合类型数组**(`"type": ["array", "null"]`,可以不填的数组)的入参,存成「名字 → 值」
    对象的,改成那些值的列表 —— 工作流(连同循环体 / 子图)和画板格子上的设置都改。

    前两条数组迁移(`migrate-plugin-array-inputs-are-lists`、`migrate-board-plugin-array-inputs-are-lists`)判
    「是不是数组」只认 `type == "array"`,联合类型的那几格没迁到:表单把它当一串编辑器(空白),运行时报「要的是
    一串值」。这一条按 plugins.inputs.schema_type 判(表单、运行时读的同一条),已经是列表的不动,重复跑是安全的。
    """
    tables = set(inspect(engine).get_table_names())
    if "plugin_instances" not in tables:
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Board, PluginInstance
    from app.domain.plugins.inputs import schema_type
    from app.domain.plugins.tools import all_tools

    arrays: dict[str, set[str]] = {}
    with Session(engine) as db:
        for instance in db.scalars(select(PluginInstance)).all():
            try:
                tools = all_tools(db, instance)
            except ValueError:  # 包记录没了、清单坏了(PluginDomainError / ManifestError 都是 ValueError)
                continue
            for tool in tools:
                properties = (tool.get("input_schema") or {}).get("properties") or {}
                keys = {
                    key for key, spec in properties.items()
                    if schema_type(spec) == "array"
                    and not (isinstance(spec.get("items"), dict) and spec["items"].get("format") == "asset")
                }
                if keys:
                    arrays.setdefault(f"plugin.{instance.package_id}.{tool['name']}", set()).update(keys)
    if not arrays:
        return

    def fixed(node_type: Any, config: Any) -> Any:
        """一份配置改好的样子;不用改回 None。"""
        keys = arrays.get(str(node_type or ""))
        if not keys or not isinstance(config, dict):
            return None
        stale = [key for key in keys if isinstance(config.get(key), dict)]
        if not stale:
            return None
        return {**config, **{key: list(config[key].values()) for key in stale}}

    if {"workflows", "workflow_revisions"} <= tables:
        def visit(node: dict[str, Any]) -> dict[str, Any]:
            config = fixed(node.get("type"), node["config"])
            return node if config is None else {**node, "config": config}

        _rewrite_workflow_graphs(
            lambda graph: _walk_graph_nodes(graph, visit),
            "插件节点的数组入参(可以不填的那种)改成一行一项:存成「名字 → 值」的,按顺序改成值的列表",
        )
    if "boards" not in tables:
        return
    #: 画板上存设置的地方:空格子的生成器(`form.producer` = `node:plugin.…`,设置在 `form.config`)和内容格的
    #: 能力(`form.abilities["node:plugin.…"].config`)。
    with Session(engine) as db:
        for board in db.scalars(select(Board)).all():
            canvas = board.canvas if isinstance(board.canvas, dict) else {}
            items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
            new_items = []
            for item in items:
                form = item.get("form") if isinstance(item, dict) and isinstance(item.get("form"), dict) else None
                if form is None:
                    new_items.append(item)
                    continue
                new_form = dict(form)
                own = fixed(str(form.get("producer") or "").removeprefix("node:"), form.get("config"))
                if own is not None:
                    new_form["config"] = own
                abilities = form.get("abilities") if isinstance(form.get("abilities"), dict) else {}
                new_abilities = {}
                for producer, setting in abilities.items():
                    config = fixed(producer.removeprefix("node:"), setting.get("config") if isinstance(setting, dict) else None)
                    new_abilities[producer] = setting if config is None else {**setting, "config": config}
                if new_abilities != abilities:
                    new_form["abilities"] = new_abilities
                new_items.append({**item, "form": new_form} if new_form != form else item)
            if new_items != items:
                board.canvas = {**json.loads(json.dumps(canvas)), "items": new_items}
                board.revision = (board.revision or 0) + 1
        db.commit()


def _migrate_session_allow_remembers_the_tier() -> None:
    """「本会话始终允许」的清单从工具名改成 (工具, 档位)(见 domain/agent/autopilot.SESSION_ALLOWABLE)。

    只记工具名时,点过一张 ai-cost 的 run_workflow,之后带 HTTP / 发布 / 代码节点(external)的 run_workflow 也
    直接放行。现在每条记的是当时那一档,只放行不高于它的卡。

    存着的那些条目**当时是哪一档已经不可知**,保守地取这个工具声明的下限档(静态表抄在这里,迁移不跟着领域
    代码变;插件工具一族的下限是 edit)。下限是撤不回的两档(external / destroy)的、认不出的工具,直接去掉 ——
    这两档不再给「始终允许」,留着也放行不了任何东西。用户要的话,在下一张卡上再点一次。
    已经是新形状的条目原样留着:幂等。
    """
    if "agent_sessions" not in set(inspect(engine).get_table_names()):
        return
    floors = {
        "browser_open": "edit", "create_workflow": "edit", "edit_board": "edit", "edit_timeline": "edit",
        "edit_workflow": "edit", "reparse_document": "edit", "run_board_item": "edit", "split_image_grid": "edit",
        "update_workflow": "edit",
        "convert_video_to_gif": "render-cost", "denoise_audio": "render-cost", "render_sequence": "render-cost",
        "separate_audio": "render-cost",
        "dub_subtitles": "ai-cost", "generate_audio": "ai-cost", "generate_image": "ai-cost",
        "generate_podcast": "ai-cost", "generate_sound": "ai-cost", "generate_video": "ai-cost",
        "run_workflow": "ai-cost",
    }

    def floor(name: str) -> str:
        if name.startswith("plugin__") and len(name) > len("plugin__"):
            return "edit"
        return floors.get(name, "")

    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, auto_allow_tools FROM agent_sessions")).mappings().all():
            raw = row["auto_allow_tools"]
            try:
                allowed = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                allowed = []
            if not isinstance(allowed, list):
                allowed = []
            converted = []
            for entry in allowed:
                if isinstance(entry, dict):
                    converted.append(entry)
                elif isinstance(entry, str) and floor(entry):
                    converted.append({"tool": entry, "permission": floor(entry)})
            if converted != allowed:
                conn.execute(
                    text("UPDATE agent_sessions SET auto_allow_tools = :v WHERE id = :id"),
                    {"v": json.dumps(converted, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_clip_edits_keep_a_change_journal() -> None:
    """片段级编辑的撤销记录改成「改动日志」(sequences/journal.py):payload 只认 `changes`。

    此前每种操作各存一种形状(移动存前后位置 + 让位右移的片段 + 落点切开的那一刀,波纹删除存原片段 +
    左移的片段……),各自配一对手写的还原。覆盖、修剪夹边、链接片段、跨轨波纹让一次编辑的副作用
    散到好几条轨上之后,撤销改为倒放一份逐条记下的改动日志。库里已有的记录在这里一次转成日志,
    撤销那一侧只认这一种形状 —— 已经做过、还能撤销 / 重做的编辑照样能撤。

    日志条目:`create` / `delete`(片段的全部字段)、`update`(改了哪几个字段的前后值)、
    `create_track`(分离音频时新建的那条轨)。已经是日志的(带 `changes`)不再动,所以重跑无害。
    """
    if "sequence_operations" not in set(inspect(engine).get_table_names()):
        return

    def clip(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "clip_id": payload["clip_id"],
            "track_id": payload["track_id"],
            "asset_id": payload.get("asset_id"),
            "timeline_start": payload["timeline_start"],
            "src_in": payload["src_in"],
            "src_out": payload["src_out"],
            "speed": payload.get("speed", 1.0),
            "gain": payload.get("gain", 1.0),
            "muted": payload.get("muted", False),
            "effects": payload.get("effects") or {},
            "transform": payload.get("transform") or {},
            "text_override": payload.get("text_override"),
        }

    def update(clip_id: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        return {"op": "update", "clip_id": clip_id, "before": before, "after": after}

    def made_room(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """插入编辑的让位:先在落点切一刀(原片段收短 + 尾段),再把后面的右移。"""
        entries: list[dict[str, Any]] = []
        split = payload.get("split")
        if split:
            tail = clip(split["tail"])
            entries.append(update(split["clip_id"], {"src_out": split["previous_src_out"]}, {"src_out": tail["src_in"]}))
            entries.append({"op": "create", "clip": tail})
        return entries + shifted(payload.get("shifted") or [])

    def shifted(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            update(entry["clip_id"], {"timeline_start": entry["previous_timeline_start"]},
                   {"timeline_start": entry["timeline_start"]})
            for entry in entries
        ]

    def replaced(edit: dict[str, Any]) -> list[dict[str, Any]]:
        """一个原片段换成若干新片段(切分、按文字剪)。"""
        return [{"op": "delete", "clip": clip(edit["original"])}] + [
            {"op": "create", "clip": clip(created)} for created in edit["created"]
        ]

    def journal(kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if kind == "insert_clip":
            return [{"op": "create", "clip": clip(payload)}] + made_room(payload)
        if kind == "insert_clips_batch":
            return [{"op": "create", "clip": clip(created)} for created in payload["created"]]
        if kind == "delete_clip":
            return [{"op": "delete", "clip": clip(payload)}]
        if kind == "delete_clips_batch":
            return [{"op": "delete", "clip": clip(entry)} for entry in payload["deleted"]]
        if kind == "ripple_delete_clip":
            return [{"op": "delete", "clip": clip(payload["original"])}] + shifted(payload["shifted"])
        if kind == "ripple_delete_clips_batch":
            return [
                change
                for entry in payload["entries"]
                for change in [{"op": "delete", "clip": clip(entry["original"])}] + shifted(entry["shifted"])
            ]
        if kind == "move_clip":
            previous_track = payload.get("previous_track_id") or payload["track_id"]
            moved = update(
                payload["clip_id"],
                {"timeline_start": payload["previous_timeline_start"], "track_id": previous_track},
                {"timeline_start": payload["timeline_start"], "track_id": payload["track_id"]},
            )
            return [moved] + made_room(payload)
        if kind == "move_clips_batch":
            return [
                update(
                    entry["clip_id"],
                    {"timeline_start": entry["previous_timeline_start"], "track_id": entry["previous_track_id"]},
                    {"timeline_start": entry["timeline_start"], "track_id": entry["track_id"]},
                )
                for entry in payload["moved"]
            ]
        if kind == "trim_clip":
            fields = ("timeline_start", "src_in", "src_out")
            return [update(payload["clip_id"], {name: payload["previous"][name] for name in fields},
                           {name: payload[name] for name in fields})]
        if kind in ("split_clip", "apply_transcript_edit"):
            return replaced(payload)
        if kind == "apply_transcript_edits_batch":
            return [change for edit in payload["edits"] for change in replaced(edit)]
        if kind == "set_clip_speed":
            return [update(payload["clip_id"], {"speed": payload["previous"]}, {"speed": payload["speed"]})]
        if kind == "detach_clip_audio":
            entries: list[dict[str, Any]] = []
            created_track = payload.get("created_track")
            if created_track:
                entries.append({"op": "create_track", "track": {**created_track, "kind": "audio", "role": ""}})
            audio = payload["audio_clip"]
            entries.append({"op": "create", "clip": clip({**audio, "clip_id": audio["id"]})})
            entries.append(update(payload["video_clip_id"], {"muted": payload["video_muted_prev"]}, {"muted": True}))
            return entries
        raise ValueError(kind)

    kinds = (
        "insert_clip", "insert_clips_batch", "delete_clip", "delete_clips_batch", "ripple_delete_clip",
        "ripple_delete_clips_batch", "move_clip", "move_clips_batch", "trim_clip", "split_clip",
        "apply_transcript_edit", "apply_transcript_edits_batch", "set_clip_speed", "detach_clip_audio",
    )
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, kind, payload FROM sequence_operations")).mappings().all()
        for row in rows:
            if row["kind"] not in kinds:
                continue
            raw = row["payload"]
            payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            if "changes" in payload:
                continue
            converted = {"changes": journal(row["kind"], payload)}
            conn.execute(
                text("UPDATE sequence_operations SET payload = :payload WHERE id = :id"),
                {"payload": json.dumps(converted, ensure_ascii=False), "id": row["id"]},
            )


def _migrate_clips_on_a_track_do_not_overlap() -> None:
    """同一条轨上已经叠在一起的片段,按「后开始的盖住先开始的」规整成不重叠。

    「同一轨上的片段不重叠」是预览和导出共同的前提(media/scene.py),而此前非波纹的插入 / 移动、
    修剪、慢放都能造出重叠。重叠时画面上是**先开始的那段赢**,后放上去的被它盖住 —— 这些重叠
    几乎都来自「把一段拖到另一段上」,用户要的是后放的那段。所以规整和现在的覆盖语义同一条规矩:
    后开始的(同时开始的,后建的)盖住先开始的;被盖住的部分裁掉,两头都露出来就切成两段,
    剩下不到最小余量(0.05 秒源时间)的碎片不留。关键帧 / 淡变按每一截自己的源区间重投影。

    **启动时一次规整完,而不是等用户第一次编辑那条序列**:编辑时规整会让「第一次编辑」顺带改掉
    别处的片段,而撤销那一步又会把重叠原样还回来;导出也不会等到有人编辑。代价是这次规整不在
    撤销栈里 —— 升级前做的编辑若撤回到重叠之前,撤销照它记下的样子还原。

    改过的序列 revision 加一:编辑器按 revision 轮询、浏览器按它的 ETag 缓存,不加的话会一直拿着
    规整之前的那份。重跑时已经没有重叠,什么都不做。
    """
    if "clips" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.sequences.coverage import piece_appearance

    epsilon, min_remainder = 1e-6, 0.05

    def end_of(row: dict[str, Any]) -> float:
        return row["timeline_start"] + (row["src_out"] - row["src_in"]) / (row["speed"] or 1.0)

    def as_json(value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else (value or {})

    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))]
        tracks: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute(text("SELECT rowid AS _rowid, * FROM clips")).mappings():
            row = dict(row)
            try:
                for name in ("timeline_start", "src_in", "src_out", "speed"):
                    row[name] = float(row[name] if row[name] is not None else 1.0)
            except (TypeError, ValueError):
                continue  # 量不出时间的行没法判断它盖住了谁,不动它
            tracks.setdefault(row["track_id"], []).append(row)
        touched_sequences: set[str] = set()
        for track_rows in tracks.values():
            ordered = sorted(track_rows, key=lambda row: (row["timeline_start"], row["_rowid"]))
            gone: set[str] = set()
            for index in range(len(ordered) - 1, -1, -1):
                cover = ordered[index]
                if cover["id"] in gone:
                    continue
                start, end = cover["timeline_start"], end_of(cover)
                for under in ordered[:index]:
                    if under["id"] in gone:
                        continue
                    under_start, under_end = under["timeline_start"], end_of(under)
                    if not (under_start < end - epsilon and under_end > start + epsilon):
                        continue
                    touched_sequences.add(under["sequence_id"])
                    speed = under["speed"] or 1.0
                    orig_in, orig_out = under["src_in"], under["src_out"]
                    left_out = orig_in + max(0.0, start - under_start) * speed
                    right_in = orig_in + max(0.0, end - under_start) * speed
                    keep_left = start > under_start + epsilon and left_out - orig_in > min_remainder
                    keep_right = end < under_end - epsilon and orig_out - right_in > min_remainder
                    transform, effects = as_json(under["transform"]), as_json(under["effects"])
                    if keep_right:
                        piece = {name: under[name] for name in columns}
                        piece.update(
                            id=uuid.uuid4().hex,
                            timeline_start=end,
                            src_in=right_in,
                            src_out=orig_out,
                            **{name: json.dumps(value) for name, value in piece_appearance(
                                transform, effects, orig_in, orig_out, right_in, orig_out).items()},
                        )  # 时间戳照抄:它是原片段的一截,不是新放上去的东西
                        conn.execute(
                            text(f"INSERT INTO clips ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})"),
                            piece,
                        )
                    if keep_left:
                        under.update(src_out=left_out)
                        sliced = (orig_in, orig_out, orig_in, left_out)
                    elif keep_right:
                        under.update(timeline_start=end, src_in=right_in)
                        sliced = (orig_in, orig_out, right_in, orig_out)
                    else:
                        gone.add(under["id"])
                        conn.execute(text("DELETE FROM clips WHERE id = :id"), {"id": under["id"]})
                        continue
                    under.update({name: json.dumps(value)
                                  for name, value in piece_appearance(transform, effects, *sliced).items()})
                    conn.execute(
                        text(
                            "UPDATE clips SET timeline_start = :timeline_start, src_in = :src_in, src_out = :src_out, "
                            "transform = :transform, effects = :effects WHERE id = :id"
                        ),
                        {name: under[name] for name in ("timeline_start", "src_in", "src_out", "transform", "effects", "id")},
                    )
        for sequence_id in touched_sequences:
            conn.execute(text("UPDATE sequences SET revision = revision + 1 WHERE id = :id"), {"id": sequence_id})


def _migrate_detached_audio_joins_its_video() -> None:
    """升级前「分离音频」分出去的那段音频,和它的画面补进同一个链接组。

    分离出去的音频是画面自己那段声音的一份拷贝,只有和画面对齐才有意义 —— 现在分离时两段就进同一组
    (之后默认一起动)。老的那些按撤销记录认:还生效的 detach_clip_audio(没被撤销)建的那段音频和
    它的画面,**两段都还在、而且还对得严丝合缝**(起点、入出点、倍速都一样)才补;用户已经把它们
    挪开过,说明他要的就是分开,不替他绑回去。画面已经在一个组里(先前分离过一次)就加进那一组。

    读的是改动日志的形状,排在 migrate-clip-edits-keep-a-change-journal 之后。已经有组的不动,重跑无害。
    补过组的序列 revision +1。
    """
    tables = set(inspect(engine).get_table_names())
    if "sequence_operations" not in tables or "clips" not in tables:
        return
    with engine.begin() as conn:
        operations = conn.execute(
            text(
                "SELECT payload FROM sequence_operations WHERE kind = 'detach_clip_audio' AND reverted = 0 "
                "ORDER BY revision_after"
            )
        ).scalars().all()
        for raw in operations:
            payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            changes = payload.get("changes") or []
            audio_id = next((entry["clip"]["clip_id"] for entry in changes if entry.get("op") == "create"), None)
            video_id = next((entry["clip_id"] for entry in changes if entry.get("op") == "update"), None)
            if not audio_id or not video_id:
                continue
            rows = {
                row["id"]: row
                for row in conn.execute(
                    text(
                        "SELECT id, timeline_start, src_in, src_out, speed, link_group FROM clips "
                        "WHERE id IN (:audio, :video)"
                    ),
                    {"audio": audio_id, "video": video_id},
                ).mappings()
            }
            audio, video = rows.get(audio_id), rows.get(video_id)
            if audio is None or video is None or audio["link_group"]:
                continue
            if any(abs(float(audio[name]) - float(video[name])) > 1e-6 for name in ("timeline_start", "src_in", "src_out", "speed")):
                continue
            group = video["link_group"] or uuid.uuid4().hex
            conn.execute(
                text("UPDATE clips SET link_group = :group WHERE id IN (:audio, :video)"),
                {"group": group, "audio": audio_id, "video": video_id},
            )
            # 编辑器按 revision 轮询、浏览器按它的 ETag 缓存:不换版本号就一直拿着补组之前的那份。
            conn.execute(
                text("UPDATE sequences SET revision = revision + 1 WHERE id = (SELECT sequence_id FROM clips WHERE id = :video)"),
                {"video": video_id},
            )


def _migrate_sequence_operation_clip_records_are_complete() -> None:
    """时间线操作日志里的每一份「片段记录」补齐到重建一个片段所需的全部字段。

    撤销 / 重做按这些记录重建片段(domain/sequences/undo/rows.restore_clip_row)。此前它对缺的字段
    逐个猜默认值:老记录只记了位置(插入、单段剪掉的原片段),或者早于某个字段出现。现在重放一律
    按键取,缺的由这里补成它们当时的含义:1 倍速、单位增益、未静音、无特效、无变换、无文字、不脱机。

    另补一份 `asset_snapshot`(素材的名字 / 类型 / 时长):素材在记录之后被删掉时,重建要还成一个
    脱机占位,而不是按旧 asset_id 撞上 RESTRICT 外键、让撤销栈卡死在这一条上。素材还在就照它抄;
    已经删掉的,从当时转成脱机的片段那里找(删素材时它们记下了同一份快照);都找不到就只留下 id ——
    名字已经无处可查。

    「片段记录」按形状认:同时有 asset_id / timeline_start / src_in / src_out 的字典,不管它挂在
    payload 的哪一层(改动日志 changes 里 create / delete 条目的 clip、删轨道记下的 clips……)。排在把老记录
    转成改动日志的那一步(clip-edits-keep-a-change-journal)之后,它转出来的片段记录同样在这里补齐。
    已经补齐的原样留着:幂等。静态的默认值抄在这里,迁移不跟着领域代码变。
    """
    tables = set(inspect(engine).get_table_names())
    if "sequence_operations" not in tables or "clips" not in tables or "assets" not in tables:
        return
    defaults: dict[str, Any] = {
        "speed": 1.0, "gain": 1.0, "muted": False, "effects": {}, "transform": {},
        "text_override": None, "link_group": None, "offline_asset": None,
    }
    clip_shape = ("asset_id", "timeline_start", "src_in", "src_out")

    def loads(raw: Any) -> Any:
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None

    with engine.begin() as conn:
        snapshots: dict[str, dict[str, Any]] = {}
        for row in conn.execute(text("SELECT offline_asset FROM clips WHERE offline_asset IS NOT NULL")):
            offline = loads(row[0])
            if isinstance(offline, dict) and isinstance(offline.get("asset_id"), str):
                snapshots.setdefault(offline["asset_id"], offline)
        for row in conn.execute(text("SELECT id, name, kind, media_info FROM assets")).mappings():
            info = loads(row["media_info"])
            snapshots[row["id"]] = {
                "asset_id": row["id"], "name": row["name"], "kind": row["kind"],
                "duration": info.get("duration") if isinstance(info, dict) else None,
            }

        def complete(node: Any) -> bool:
            touched = False
            if isinstance(node, list):
                for item in node:
                    touched = complete(item) or touched
                return touched
            if not isinstance(node, dict):
                return False
            if all(key in node for key in clip_shape):
                for key, value in defaults.items():
                    if key not in node:
                        node[key] = json.loads(json.dumps(value))
                        touched = True
                if "asset_snapshot" not in node:
                    asset_id = node["asset_id"]
                    node["asset_snapshot"] = (
                        None if not isinstance(asset_id, str)
                        else snapshots.get(asset_id, {"asset_id": asset_id, "name": "", "kind": "", "duration": None})
                    )
                    touched = True
            for value in node.values():
                touched = complete(value) or touched
            return touched

        for row in conn.execute(text("SELECT id, payload FROM sequence_operations")).mappings().all():
            payload = loads(row["payload"])
            if complete(payload):
                conn.execute(
                    text("UPDATE sequence_operations SET payload = :p WHERE id = :id"),
                    {"p": json.dumps(payload, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_removed_track_records_are_complete() -> None:
    """「删轨道」的撤销记录补齐轨道的全部状态,包括用途(role)。

    撤销按键取这几项(domain/sequences/undo/tracks.RemoveTrack)。早先的记录里没有 muted / solo / locked /
    duck(当时还没有这几列,或者没记),也从来没有 role —— 撤销删掉的配音轨,还回来的是一条普通轨,再配
    一次就另开一条新轨。缺的补成它们当时的含义:没有这个开关就是关着,没有用途就是普通轨(那份记录
    本来就不知道它是不是配音轨,撤销的结果和此前一样)。已经齐全的原样留着:幂等。
    """
    if "sequence_operations" not in set(inspect(engine).get_table_names()):
        return
    defaults: dict[str, Any] = {"muted": False, "solo": False, "locked": False, "duck": False, "role": ""}
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, payload FROM sequence_operations WHERE kind = 'remove_track'")
        ).mappings().all()
        for row in rows:
            raw = row["payload"]
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            missing = {key: value for key, value in defaults.items() if key not in payload}
            if missing:
                conn.execute(
                    text("UPDATE sequence_operations SET payload = :p WHERE id = :id"),
                    {"p": json.dumps({**payload, **missing}, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_added_track_records_list_what_moved() -> None:
    """「加轨道」的撤销记录补一项 `shifted`:为新轨让过位置的那几条(撤销时还回原来的行)。

    此前新轨一律排在最后,谁都不用让,所以老记录一律是空的。已经有这一项的原样留着:幂等。
    """
    if "sequence_operations" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, payload FROM sequence_operations WHERE kind = 'add_track'")
        ).mappings().all()
        for row in rows:
            raw = row["payload"]
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if isinstance(payload, dict) and "shifted" not in payload:
                conn.execute(
                    text("UPDATE sequence_operations SET payload = :p WHERE id = :id"),
                    {"p": json.dumps({**payload, "shifted": []}, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_assets_remember_where_they_came_from() -> None:
    """素材补两列:出处 `derived_from`(`[{asset_id, op}]`)和「含 AI 生成 / 合成的内容」`ai_generated`
    (见 domain/assets/lineage)。

    加列必须在 SCHEMA 之前:之后 ORM 上的 Asset 已经指望这两列在了。老素材的回填在 AFTER_SCHEMA 的
    backfill-asset-lineage —— 它要读生成记录和任务表。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(assets)"))}
        if not columns:
            return
        if "derived_from" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN derived_from JSON NOT NULL DEFAULT '[]'"))
        if "ai_generated" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN ai_generated BOOLEAN NOT NULL DEFAULT 0"))


def _migrate_assets_know_if_they_are_intermediate() -> None:
    """素材补一列 `intermediate`:这一份是不是某道工序逐条做出来的零件、是哪一种(见 domain/assets/intermediates);
    空串 = 素材库里的正常素材。顺手建素材库列表按它筛的索引。

    加列必须在 SCHEMA 之前:之后 ORM 上的 Asset 已经指望这一列在了。老素材的回填在 AFTER_SCHEMA 的
    backfill-intermediate-assets —— 它要读任务和时间线。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(assets)"))}
        if not columns:
            return
        if "intermediate" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN intermediate VARCHAR(24) NOT NULL DEFAULT ''"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_assets_workspace_intermediate_created "
            "ON assets (workspace_id, intermediate, created_at)"
        ))


def _migrate_assets_get_a_name_sort_key() -> None:
    """素材补一列 `name_sort_key`(按名称排序用的键,见 core/collation)并给每一行算好;建素材库按名称排时用的索引。

    素材库分页之后名称排序挪到了服务端,成了码位顺序,中文名不再按拼音 —— 此前浏览器里是 ICU 的中文排序。
    新写的名字由 ORM 在赋值时算(Asset 上的 `_name_sort_key`);这一步给已有的行补上,**用的是同一个函数**:
    键不一样的话,老素材和新素材在同一份列表里各排各的。加列必须在 SCHEMA 之前:之后 ORM 上的 Asset 指望这一列在。
    重跑:只算还空着的(名字不会是空的,算过的键一定不空)。
    """
    from app.core.collation import name_sort_key

    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(assets)"))}
        if not columns:
            return
        if "name_sort_key" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN name_sort_key TEXT NOT NULL DEFAULT ''"))
        rows = conn.execute(text("SELECT id, name FROM assets WHERE name_sort_key = ''")).all()
        for asset_id, name in rows:
            conn.execute(text("UPDATE assets SET name_sort_key = :key WHERE id = :id"),
                         {"key": name_sort_key(name or ""), "id": asset_id})
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_assets_workspace_intermediate_name "
            "ON assets (workspace_id, intermediate, name_sort_key, id)"
        ))


def _backfill_intermediate_assets() -> None:
    """老素材里推得出是工序零件的,标上是哪一种;推不出的留在素材库(空串)。

    逐句配音的一句(`dub_line`):
    - media_info 里记着 `dub_line`(那一句念的什么、谁念的 —— 字幕配音近来给每一句都写);
    - 更早的没写:来源是合成(tts),而且是字幕配音任务派出去的合成子任务交回的(jobs.parent_job_id 指着一个
      subtitle_dub 任务),或者放在配音轨(tracks.role = dub)上;
    - 长稿分段配音拼进一段 / 补过静音的那一句:来源是合成,而且是另一段合成音频的出处(那一段的 derived_from 里
      op 是 concat / pad)。
    对口型的一块(`lipsync_chunk`):
    - media_info 里记着 `dub_lipsync_chunk`(改好口型的那一块);
    - 切出来交给改口型的原片块、配音块:来源 derived、出处的 op 是 trim / mix(只有对口型这样登记过)。

    导出的成片、合成的整段、人自己拖上配音轨的导入音频都不动。推断规则写在这里、不调领域代码:迁移是历史快照。
    重跑:已经标上的不再动,其余照旧推不出。
    """
    tables = set(inspect(engine).get_table_names())
    if "assets" not in tables:
        return

    def loads(value: Any, empty: Any) -> Any:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return empty
        return value if isinstance(value, type(empty)) else empty

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, source, media_info, derived_from FROM assets WHERE intermediate = ''")
        ).mappings().all()
        sources = {row["id"]: row["source"] for row in rows}
        dubbed_by_job: set[str] = set()
        if "jobs" in tables:
            for (result,) in conn.execute(text(
                "SELECT child.result FROM jobs child JOIN jobs parent ON parent.id = child.parent_job_id "
                "WHERE child.kind = 'tts' AND parent.kind = 'subtitle_dub'"
            )):
                made = str(loads(result, {}).get("asset_id") or "")
                if made:
                    dubbed_by_job.add(made)
        on_dub_track: set[str] = set()
        if {"clips", "tracks"} <= tables:
            on_dub_track = {one for (one,) in conn.execute(text(
                "SELECT DISTINCT clips.asset_id FROM clips JOIN tracks ON tracks.id = clips.track_id "
                "WHERE tracks.role = 'dub' AND clips.asset_id IS NOT NULL"
            ))}

        marks: dict[str, str] = {}
        for row in rows:
            asset_id, source = row["id"], row["source"]
            info = loads(row["media_info"], {})
            parents = [one for one in loads(row["derived_from"], []) if isinstance(one, dict)]
            if "dub_line" in info:
                marks[asset_id] = "dub_line"
            elif "dub_lipsync_chunk" in info:
                marks[asset_id] = "lipsync_chunk"
            elif source == "tts" and (asset_id in dubbed_by_job or asset_id in on_dub_track):
                marks[asset_id] = "dub_line"
            elif source == "derived" and any(one.get("op") in ("trim", "mix") for one in parents):
                marks[asset_id] = "lipsync_chunk"
            if source == "tts":
                for one in parents:
                    parent = str(one.get("asset_id") or "")
                    if one.get("op") in ("concat", "pad") and sources.get(parent) == "tts":
                        marks.setdefault(parent, "dub_line")
        for asset_id, kind in marks.items():
            conn.execute(text("UPDATE assets SET intermediate = :kind WHERE id = :id"), {"kind": kind, "id": asset_id})


def _backfill_asset_lineage() -> None:
    """老素材补上出处和「含 AI」:从现有记录推得出来的补上,推不出来的留空。

    1. 自己就是 AI 做的:生成记录的每一份产出(generated_assets 一份一行;generation_jobs.result_asset_id
       兜一道),来源是合成配音 / 播客 / 数字人整段的(tts、podcast、digital_human)。
    2. 出处:
       - 切宫格、分离、降噪、转 GIF 此前各自把出处塞在 media_info 的 `derived_from_asset_id` + `derivation` 里 ——
         搬进 derived_from,media_info 里这两个键去掉(只留一处说法);derivation 不是这四种的原样留着;
       - 画板截取的任务(jobs.kind = trim,成功的):payload.asset_id → result.asset_id;
       - 导出任务(jobs.kind = render,成功的):成片的出处是它导出那一版时间线上的素材。只有时间线**还停在那一版**
         (sequences.revision 等于任务记的 sequence_revision)时才认得出;之后改过的推不出,留空。
       其余(取帧、对口型、插件……)当时没留下记录,推不出。
    3. 「含 AI」顺着出处往下传:子素材总比出处晚登记,按创建时间排一遍就传到底;再跑到不变为止兜一道。

    推断规则写在这里、不调领域代码:迁移是历史快照,领域以后怎么改,这一步重放出来的结果都不该变。
    重跑:已经有出处的不动,「含 AI」只会从无到有,media_info 里的两个键第一遍就去掉了。
    """
    tables = set(inspect(engine).get_table_names())
    if "assets" not in tables:
        return
    ops = {"image_grid_split": "grid_split", "separate_audio": "separate", "denoise": "denoise", "video_to_gif": "gif"}
    synthesized = ("tts", "podcast", "digital_human")

    def loads(value: Any, empty: Any) -> Any:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return empty
        return value if isinstance(value, type(empty)) else empty

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, source, media_info, derived_from, ai_generated FROM assets ORDER BY created_at, id")
        ).mappings().all()
        roots: set[str] = {row["id"] for row in rows if row["source"] in synthesized}
        if "generated_assets" in tables:
            roots |= {one for (one,) in conn.execute(text("SELECT asset_id FROM generated_assets"))}
        if "generation_jobs" in tables:
            roots |= {one for (one,) in conn.execute(
                text("SELECT result_asset_id FROM generation_jobs WHERE result_asset_id IS NOT NULL"))}

        inferred: dict[str, list[dict[str, str]]] = {}
        if "jobs" in tables:
            for kind, payload, result in conn.execute(
                text("SELECT kind, payload, result FROM jobs WHERE kind IN ('trim', 'render') AND status = 'succeeded' "
                     "ORDER BY created_at, id")
            ):
                payload, result = loads(payload, {}), loads(result, {})
                made = str(result.get("asset_id") or "")
                if not made:
                    continue
                if kind == "trim" and payload.get("asset_id"):
                    inferred[made] = [{"asset_id": str(payload["asset_id"]), "op": "trim"}]
                elif kind == "render" and {"sequences", "clips"} <= tables:
                    revision = conn.execute(text("SELECT revision FROM sequences WHERE id = :id"),
                                            {"id": str(payload.get("sequence_id") or "")}).scalar()
                    if revision is None or revision != payload.get("sequence_revision"):
                        continue
                    used = conn.execute(
                        text("SELECT asset_id FROM clips WHERE sequence_id = :id AND asset_id IS NOT NULL "
                             "ORDER BY timeline_start, id"),
                        {"id": str(payload["sequence_id"])},
                    ).scalars().all()
                    inferred[made] = [{"asset_id": one, "op": "export"} for one in dict.fromkeys(used) if one != made]

        lineage: dict[str, list[dict[str, str]]] = {}
        ai: dict[str, bool] = {}
        #: media_info 要改写的那些(去掉搬走的两个键)。
        infos: dict[str, dict[str, Any]] = {}
        for row in rows:
            asset_id = row["id"]
            info = loads(row["media_info"], {})
            parent, derivation = info.get("derived_from_asset_id"), info.get("derivation")
            moved: list[dict[str, str]] = []
            if parent and isinstance(derivation, str) and derivation in ops:
                # 认得的才搬、才去掉;认不得的原样留着,不替它猜。
                moved = [{"asset_id": str(parent), "op": ops[derivation]}]
                infos[asset_id] = {key: value for key, value in info.items()
                                   if key not in ("derived_from_asset_id", "derivation")}
            current = loads(row["derived_from"], []) or moved or inferred.get(asset_id, [])
            lineage[asset_id] = current
            ai[asset_id] = bool(row["ai_generated"]) or asset_id in roots

        grew = True
        while grew:
            grew = False
            for asset_id, parents in lineage.items():
                if not ai[asset_id] and any(ai.get(str(one.get("asset_id"))) for one in parents if isinstance(one, dict)):
                    ai[asset_id] = grew = True

        for row in rows:
            asset_id = row["id"]
            if lineage[asset_id] != loads(row["derived_from"], []) or ai[asset_id] != bool(row["ai_generated"]):
                conn.execute(text("UPDATE assets SET derived_from = :lineage, ai_generated = :ai WHERE id = :id"),
                             {"id": asset_id, "lineage": json.dumps(lineage[asset_id]), "ai": ai[asset_id]})
            if asset_id in infos:
                conn.execute(text("UPDATE assets SET media_info = :info WHERE id = :id"),
                             {"id": asset_id, "info": json.dumps(infos[asset_id], ensure_ascii=False)})


def _reindex_record_references() -> None:
    """引用表(record_references)是派生数据:抽取规则一变,整张按新规则重建。"""
    from app.db.references import reindex

    with engine.begin() as conn:
        reindex(conn)


def _migrate_existing_libraries_get_the_new_reference_prices() -> None:
    """老库补上这一版新增的内置参考价(见 domain/billing/price_reference)。

    参考价进库只有「预填」这一条路,新装的库也要点了才有;这一版新加的价(生视频按分辨率分档、GPT Image 的
    文字 / 参考图输入价、147ai 的 gpt-image-2-client、Evolink 的 Seedance、海螺 H3 的 2K)不补的话,老库里
    这些型号照旧按一档价记、或者一直未定价 —— 而紧接着的补算老账正要用到它们。

    照预填的规则走(只补不改、不混币种、只补模型行上真会用到的能力),而且**只看这一版新增的那些型号**:
    用户没点过预填的其余型号是他的选择,升级不替他补。不取目录(那要联网、要钥匙),只用内置价目表。
    """
    from app.core.unit_of_work import unit_of_work
    from app.db.models import ProviderProfile
    from app.domain.billing.pricing_prefill import prefill_profile_pricing

    models = frozenset({
        # 生视频按输出分辨率分档
        "wan2.5-t2v-preview", "wan2.6-t2v", "wan2.7-t2v", "wan2.5-i2v-preview", "wan2.6-i2v", "wan2.7-i2v",
        "wan2.7-r2v", "wan2.7-videoedit", "wan2.2-s2v", "MiniMax-H3",
        "doubao-seedance-2-5-260628", "doubao-seedance-2-0-260128", "dreamina-seedance-2-5-260628",
        "dreamina-seedance-2-0-260128", "veo-3.1-generate-preview", "veo-3.1-fast-generate-preview",
        "veo-3.1-lite-generate-preview",
        # GPT Image 的文字输入、参考图输入价;147ai 自己的型号名
        "gpt-image-2.5-sunburst", "gpt-image-2.5-flare", "gpt-image-2", "gpt-image-1.5", "gpt-image-1",
        "gpt-image-1-mini", "gpt-image-2-client",
        # Evolink 自己的价目
        "seedance-2.5-text-to-video", "seedance-2.5-image-to-video", "seedance-2.5-reference-to-video",
        "seedance-2.5-video-edit", "seedance-2.5-video-extend", "seedance-2.0-text-to-video",
        "seedance-2.0-image-to-video", "seedance-2.0-reference-to-video", "seedance-2.0-mini-text-to-video",
        "seedance-2.0-mini-image-to-video", "seedance-2.0-mini-reference-to-video",
    })
    with unit_of_work() as db:
        for profile in db.query(ProviderProfile).order_by(ProviderProfile.created_at):
            prefill_profile_pricing(db, profile, base_url=profile.base_url or "", catalog=[], only_models=models)


def _backfill_usage_costs() -> None:
    """补算老账:费用为空、但现在按价目或服务商回报算得出来的历史用量补上费用(可信度 backfilled);
    失败、当时按请求侧计量估了价、服务商什么都没回的那几条改成不计费的 0。保守的取舍见
    domain/billing/backfill。排在补参考价那一步之后 —— 它要用到刚补上的价。"""
    from app.core.unit_of_work import unit_of_work
    from app.domain.billing.backfill import backfill_usage_costs

    with unit_of_work() as db:
        backfill_usage_costs(db)


def _reprice_usage_billed_on_estimated_prompt_tokens() -> None:
    """补算老账的第二步:已经有费用、但明显是按旧规则「只算了估的提示词 token」少算的生图生视频(147ai 的
    gpt-image-2:回包里有图像输出 token,账上只按估的十几个输入 token 记了几十 micros),按现在的规则重算,
    可信度 backfilled。判据很窄,见 domain/billing/backfill.reprice_estimated_prompt_only。"""
    from app.core.unit_of_work import unit_of_work
    from app.domain.billing.backfill import reprice_estimated_prompt_only

    with unit_of_work() as db:
        reprice_estimated_prompt_only(db)


def _migrate_existing_libraries_get_the_evolink_gpt_image_prices() -> None:
    """老库补上 Evolink GPT Image 的内置参考价(gpt-image-2 / 2-beta / 2.5-flare / 2.5-sunburst)。

    「补新增参考价」那一步(上面的 migrate-existing-libraries-get-the-new-reference-prices)身体不能再改,所以另开一步;
    规则和点「预填」一样:只补模型行上配了的、只补不改、不混币种。连接上还没启用这几个型号的,启用之后点一次「预填」。
    """
    from app.core.unit_of_work import unit_of_work
    from app.db.models import ProviderProfile
    from app.domain.billing.pricing_prefill import prefill_profile_pricing

    models = frozenset({"gpt-image-2", "gpt-image-2-beta", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"})
    with unit_of_work() as db:
        for profile in db.query(ProviderProfile).filter(ProviderProfile.vendor == "evolink").order_by(ProviderProfile.created_at):
            prefill_profile_pricing(db, profile, base_url=profile.base_url or "", catalog=[], only_models=models)


def _migrate_existing_libraries_get_the_s2v_detect_price() -> None:
    """老库补上百炼说话照片人像预检(wan2.2-s2v-detect)的内置参考价,¥0.004/张(见 domain/billing/price_reference)。

    预检是说话照片**顺带**调的,不在连接的模型目录里,用户也不会把它配成模型行:预填现在跟着 wan2.2-s2v 一起补它
    (price_reference.BILLED_ALONGSIDE)。老库里配了 wan2.2-s2v 的百炼连接这里补一次;规则和点「预填」一样:只补不改、
    不混币种。此前预检每调一次扣一次钱,账上一笔都没有(付费实测)。
    """
    from app.core.unit_of_work import unit_of_work
    from app.db.models import ProviderProfile
    from app.domain.billing.pricing_prefill import prefill_profile_pricing

    models = frozenset({"wan2.2-s2v-detect"})
    with unit_of_work() as db:
        for profile in db.query(ProviderProfile).filter(ProviderProfile.vendor == "alibaba").order_by(ProviderProfile.created_at):
            prefill_profile_pricing(db, profile, base_url=profile.base_url or "", catalog=[], only_models=models)


def _migrate_existing_libraries_get_the_gemini_chat_prices() -> None:
    """老库补上 Gemini 对话的内置参考价(见 domain/billing/price_reference 的 Gemini 一段)。

    Google 连接这一版才能对话,此前它下面挂着的 Gemini 对话模型行只有一种来路:有人手动加了、标成对话,给素材分析的
    「原生视频」用 —— 那些调用一直在记账,却一直未定价。规则和点「预填」一样:只补模型行上配了的、只补不改、不混币种。
    连接上还没加这几个型号的,加了之后点一次「预填」。型号写死在这里:迁移说的是这一版补了哪些,不跟着价目表往后变。
    """
    from app.core.unit_of_work import unit_of_work
    from app.db.models import ProviderProfile
    from app.domain.billing.pricing_prefill import prefill_profile_pricing

    models = frozenset({
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-3.1-pro-preview-customtools", "gemini-3-flash-preview",
        "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
    })
    with unit_of_work() as db:
        for profile in db.query(ProviderProfile).filter(ProviderProfile.vendor == "google").order_by(ProviderProfile.created_at):
            prefill_profile_pricing(db, profile, base_url=profile.base_url or "", catalog=[], only_models=models)


def _migrate_speech_usage_follows_todays_booking() -> None:
    """语音合成的老账照现在的口径改:记在**连接的厂商**名下,免费的引擎记 0、可信度「免费」。

    两处都是记账口径改了、老账没跟上:

    - 百炼一条连接下的 CosyVoice 此前记成引擎 id `alibaba-cosyvoice`,而价目规则(「预填价格」填的、手写的)按厂商 `alibaba`
      配 —— 永远对不上,账上永远「未定价」。改成连接的厂商(映射照 `providers.connection_vendor_for_speech_engine`)。
    - Edge 配音从 1.9.0 起记 0、可信度 `free`(适配器的 `free_of_charge`),此前那些还是「没能定价」(费用为空):
      在「有 N 次没价」里算着,让人去配一条根本不存在的价。只改费用为空的,已经有数的不动。

    价目规则不在这里补:要不要按挂牌价给 CosyVoice 记账,由用户在成本规则里点「预填价格」时定。幂等:改过的不再满足条件。
    """
    from app.ai.providers import REMOTE_SPEECH_ADAPTERS, connection_vendor_for_speech_engine

    if "provider_usage_events" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for engine_id, adapter in REMOTE_SPEECH_ADAPTERS.items():
            vendor = connection_vendor_for_speech_engine(engine_id)
            if vendor != engine_id:
                conn.execute(
                    text("UPDATE provider_usage_events SET provider = :vendor WHERE provider = :engine AND capability = 'tts'"),
                    {"vendor": vendor, "engine": engine_id},
                )
            if getattr(adapter, "free_of_charge", False):
                conn.execute(
                    text(
                        "UPDATE provider_usage_events SET cost_micros = 0, cost_confidence = 'free' "
                        "WHERE provider = :engine AND capability = 'tts' AND cost_micros IS NULL"
                    ),
                    {"engine": engine_id},
                )


def _migrate_plugin_connection_errors_follow_the_reader() -> None:
    """连接的出错原因(`plugin_instances.capability_status` 里各项能力的 error)只存文案 key + 参数,给人看时按读的人的语言说。

    此前插件运行时说的那句(ComfyUI 的「连不上这台 ComfyUI……」)按刷新那一刻的语言说好,原样存进 `pluginErr_upstream`
    的 `detail`;更老的记录连 key 都没有,只存了一句话。中文界面刷新过的连接切到英文仍是中文。现在插件按语言分着交、
    宿主原样存(`{"__text": …}`,见 core/i18n.authored_text)。库里的旧记录在这里一次改掉:

    - `pluginErr_upstream` 带着一句死文字的:那是插件自己写的话,认不回文案 key —— 清掉;
    - 没有 key(或 key 已不在文案表里)、只有一句话的:认得出是哪条插件文案填出来的,改成 key + 参数;认不出 —— 清掉。

    清掉的只是这一次失败的原因(error / error_key / error_params),上一次成功的记录(模型数、刷新时间、指纹)留着;
    启动时后台会把每个连接刷一遍(catalog_watch.refresh_all),原因按新形状重新生成。幂等:新形状不再被认作旧的。
    """
    from string import Formatter

    from app.core.i18n import MESSAGES

    def key_for(said: str) -> tuple[str, dict[str, str]] | None:
        """这句话是哪条插件文案(在哪种语言下)按什么参数填出来的;认不出来回 None。
        只认**有字面部分**的模板:只有一个槽的(`{detail}`)什么话都套得上,认了等于没认。"""
        for key, templates in MESSAGES.items():
            if not key.startswith("pluginErr_"):
                continue
            for template in templates.values():
                parts = list(Formatter().parse(template))
                if not any(literal.strip() for literal, _, _, _ in parts):
                    continue
                pattern, seen = "", set()
                for literal, field, _, _ in parts:
                    pattern += re.escape(literal)
                    if field is not None:
                        pattern += f"(?P={field})" if field in seen else f"(?P<{field}>.+?)"
                        seen.add(field)
                matched = re.fullmatch(pattern, said, re.DOTALL)
                if matched:
                    return key, matched.groupdict()
        return None

    if "plugin_instances" not in set(inspect(engine).get_table_names()):
        return
    cleared = {"error": "", "error_key": "", "error_params": {}}
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, capability_status FROM plugin_instances")).fetchall()
        for instance_id, raw in rows:
            statuses = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(statuses, dict):
                continue
            changed = False
            for capability, status in statuses.items():
                if not isinstance(status, dict):
                    continue
                key = str(status.get("error_key") or "")
                params = status.get("error_params") if isinstance(status.get("error_params"), dict) else {}
                if key == "pluginErr_upstream" and isinstance(params.get("detail"), str):
                    statuses[capability] = {**status, **cleared}
                    changed = True
                elif key not in MESSAGES and (key or status.get("error")):
                    found = key_for(str(status.get("error") or ""))
                    statuses[capability] = {**status, **({"error_key": found[0], "error_params": found[1]} if found else cleared)}
                    changed = True
            if changed:
                conn.execute(
                    text("UPDATE plugin_instances SET capability_status = :status WHERE id = :id"),
                    {"status": json.dumps(statuses, ensure_ascii=False), "id": instance_id},
                )


def _migrate_board_failures_follow_the_reader() -> None:
    """画板上失败的格子改存失败的原样(原文 + 文案 key + 参数,和任务同形),给人看的那一句、原文、原因和怎么修在读的时候按读的人
    的语言出(见 domain/boards/failures)。

    此前回执存的是按回执那一刻的语言摘好的一句(`run.error`)、原文(`run.error_detail`)、拼好的一段提示(`run.error_hint`)。
    老格子认不回文案 key —— 那一句已经是某种语言的字了 —— 照原样挪进新形状,读出来和原来一样(还是写下时的那种语言):

    - 有原文的:`error` 换成原文,原来那一句挪进参数的 `summary`(失败摘要先用它,见 failure_summary.summarize);
    - 有提示的:挪进参数的 `hint.cause`(拆不开原因和步骤,不猜);
    - 只有一句的不动(读的时候那一句就是它自己)。

    改到的板版本号 +1。幂等:新形状里没有 `error_detail` / `error_hint`。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for board_id, raw, revision in conn.execute(text("SELECT id, canvas, revision FROM boards")).fetchall():
            try:
                canvas = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            changed = False
            for item in canvas["items"]:
                run = item.get("run") if isinstance(item, dict) else None
                if not isinstance(run, dict) or not ("error_detail" in run or "error_hint" in run):
                    continue
                detail, hint = run.pop("error_detail", None), run.pop("error_hint", None)
                params = dict(run.get("error_params") or {}) if isinstance(run.get("error_params"), dict) else {}
                said = run.get("error") if isinstance(run.get("error"), str) else ""
                if isinstance(detail, str) and detail.strip():
                    if said.strip():
                        params["summary"] = said.strip()
                    run["error"] = detail.strip()
                if isinstance(hint, str) and hint.strip():
                    params["hint"] = {"cause": hint.strip()}
                if params:
                    run["error_params"] = params
                changed = True
            if changed:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = :revision WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "revision": int(revision or 0) + 1, "id": board_id},
                )


def _migrate_failure_hints_say_cause_and_steps() -> None:
    """失败参数里认得出的原因(`error_params.hint`)从一整句话改成「原因 + 怎么修」:`{"cause": 一句, "steps": [{"text", "command"}]}`。

    此前插件交的 hint 是一句话(按语言分着存,`{"__text": …}`),要敲的命令埋在句子里;失败卡现在把原因、修的步骤和命令分开摆
    (命令一块等宽字、带复制),插件也改成分着交(见 plugins.runtime.failure_shape)。库里那几条旧的(这一形状只在 1.22.0 插件
    交出去过)原样挪进 `cause` —— 那句话本来就是原因加修法,拆不开也不猜,照旧整句给人看;没有步骤。

    任务(`jobs`)和生成记录(`generation_jobs`,失败原因抄了一份)两处都改。幂等:新形状是带 `cause` / `steps` 的字典,不再被认作旧的。
    """
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table in ("jobs", "generation_jobs"):
            if table not in tables:
                continue
            rows = conn.execute(text(f"SELECT id, error_params FROM {table} WHERE error_params LIKE '%\"hint\"%'")).fetchall()
            for row_id, raw in rows:
                params = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(params, dict) or "hint" not in params:
                    continue
                hint = params["hint"]
                if isinstance(hint, dict) and ("cause" in hint or "steps" in hint):
                    continue
                said = hint.get("__text") if isinstance(hint, dict) else hint
                if said:
                    params["hint"] = {"cause": hint}
                else:
                    params.pop("hint")
                conn.execute(text(f"UPDATE {table} SET error_params = :params WHERE id = :id"),
                             {"params": json.dumps(params, ensure_ascii=False), "id": row_id})


def _migrate_generation_results_keep_output_parameters_apart() -> None:
    """生成任务结果里「每份用的参数」(每张一个种子)从 `outputs` 挪到 `output_parameters`。

    `outputs` 是「这个任务交回了什么」(`[{type, …}]`,画板回执和任务详情都只认它);生成任务此前把
    `[{asset_id, parameters}]` 也记在这个键下,读的人看见 `outputs` 就不再看 `asset_ids` —— ComfyUI 跑几遍的那种
    生成在任务详情里什么都不显示。只挪认得出的那种(每一项都是带 asset_id、没有 type 的对照);幂等:挪过的不再有 `outputs`。
    """
    if "jobs" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, result FROM jobs WHERE kind = 'ai_generation' AND result LIKE '%\"outputs\"%'"
        )).fetchall()
        for job_id, raw in rows:
            result = json.loads(raw) if isinstance(raw, str) else raw
            outputs = result.get("outputs") if isinstance(result, dict) else None
            if not isinstance(outputs, list) or not outputs or not all(
                isinstance(one, dict) and "asset_id" in one and "type" not in one for one in outputs
            ):
                continue
            moved = {key: value for key, value in result.items() if key != "outputs"}
            moved["output_parameters"] = outputs
            conn.execute(text("UPDATE jobs SET result = :result WHERE id = :id"),
                         {"result": json.dumps(moved, ensure_ascii=False), "id": job_id})


def _migrate_local_services_remember_their_python() -> None:
    """本机服务那一行补一列 `python_minor`:让 Mosael 装的那一份装好时建 venv 用的 Python 小版本(ADR 0041 §4)。

    加列必须在 SCHEMA 之前:之后 ORM 上的 LocalService 已经指望它在了。已有的行都是「用我自己装的」(第一步只有这一种),
    留空就对 —— 那一种不看它。表还没有(从没用过本机服务的库)就什么都不做,SCHEMA 会建出带这一列的表。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(local_services)"))}
        if columns and "python_minor" not in columns:
            conn.execute(text("ALTER TABLE local_services ADD COLUMN python_minor VARCHAR(16) NOT NULL DEFAULT ''"))


def _migrate_local_services_share_model_folders() -> None:
    """本机服务那一行补一列 `shared_models`:共用的模型文件夹(ADR 0041 拍板 5),一项一个绝对路径。已有的行一个都没有(`[]`)。

    加列必须在 SCHEMA 之前:之后 ORM 上的 LocalService 已经指望它在了。表还没有就什么都不做(SCHEMA 建的表带这一列)。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(local_services)"))}
        if columns and "shared_models" not in columns:
            conn.execute(text("ALTER TABLE local_services ADD COLUMN shared_models JSON NOT NULL DEFAULT '[]'"))


def _migrate_local_services_stop_when_idle() -> None:
    """本机服务那一行补一列 `idle_stop_minutes`:闲置多少分钟自动停(释放显存),0 = 不停。已有的行按缺省 30 分钟 —— 第三步的
    「闲置自动停」对它们一样生效(「保持运行」的照旧不停)。

    加列必须在 SCHEMA 之前:之后 ORM 上的 LocalService 已经指望它在了。表还没有就什么都不做。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(local_services)"))}
        if columns and "idle_stop_minutes" not in columns:
            conn.execute(text("ALTER TABLE local_services ADD COLUMN idle_stop_minutes INTEGER NOT NULL DEFAULT 30"))


def _migrate_agent_skills_remember_the_drafting_session() -> None:
    """技能的索引行补一列 `agent_session_id`:智能体在哪次对话里建的(ADR 0043),设置页的来源标签点开就是那段对话。

    老行都是人在设置里建、导入、从对话「存成技能」的 —— 不是智能体经确认卡建的,落成 NULL 就是它们的真实情况。
    加列必须在 SCHEMA 之前:之后 ORM 上的 AgentSkill 已经指望它在了。表还没有就什么都不做(SCHEMA 会照模型建全)。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_skills)"))}
        if columns and "agent_session_id" not in columns:
            conn.execute(text(
                "ALTER TABLE agent_skills ADD COLUMN agent_session_id VARCHAR(64) "
                "REFERENCES agent_sessions(id) ON DELETE SET NULL"
            ))


def _migrate_agent_sessions_remember_where_they_were_opened() -> None:
    """对话记住在哪开的(ADR 0044 §1):`agent_sessions` 加「家」两列(`home_kind`、`home_id`)、`pending_view_at` 和按家取清单的索引。

    老对话的家全是 AI Studio(列的默认值)—— 维护者定的。同一步里两种例外,都是**记着的事实**,不是猜:

    - `project_id` 不空的(只能是经接口建的):家记成那个项目 —— 它当初就是冲着这个项目开的,项目级记忆也照旧注入
      (`project_id` 这一列由 SCHEMA 之后的 `_drop_agent_sessions_project_id` 删掉);
    - `origin = 'workflow'` 的(`/workflows/{id}/agent-session(s)` 那三条死路由建的):`origin` 改成 `ui`,家记成
      `external_key` 里那个工作流,`external_key` 清空;那几天建的没走认领、主人是空的,主人记成那个工作流的创建者(最早一版
      里有记录的作者,和 `_backfill_workflow_revision_authors` 同一个判据),找不到就是工作区的 owner。它们从此在 AI Studio 和
      那个工作流的面板里看得见。很老的库这时还没有 `owner_user_id` 列:由之后的 `_migrate_resource_ownership` 补成工作区 owner。

    加列必须在 SCHEMA 之前:之后 ORM 上的 AgentSession 已经指望它们在了。表还没有就什么都不做。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
        if not columns:
            return
        if "home_kind" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN home_kind VARCHAR(16) NOT NULL DEFAULT 'studio'"))
        if "home_id" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN home_id VARCHAR(700) NOT NULL DEFAULT ''"))
        if "pending_view_at" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN pending_view_at DATETIME"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_agent_sessions_ws_home "
            "ON agent_sessions (workspace_id, home_kind, home_id, updated_at)"
        ))
        if "project_id" in columns:
            conn.execute(text(
                "UPDATE agent_sessions SET home_kind = 'project', home_id = project_id "
                "WHERE project_id IS NOT NULL AND project_id != '' AND home_kind = 'studio'"
            ))
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
        revisions = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(workflow_revisions)"))}
            if "workflow_revisions" in tables else set()
        )
        for session_id, workspace_id, external_key in conn.execute(text(
            "SELECT id, workspace_id, external_key FROM agent_sessions WHERE origin = 'workflow'"
        )).all():
            key = external_key or ""
            workflow_id = key[len("workflow:"):].split(":", 1)[0] if key.startswith("workflow:") else ""
            conn.execute(
                text(
                    "UPDATE agent_sessions SET origin = 'ui', home_kind = :kind, home_id = :home, external_key = NULL "
                    "WHERE id = :id"
                ),
                {"kind": "workflow" if workflow_id else "studio", "home": workflow_id, "id": session_id},
            )
            if "owner_user_id" not in columns:
                continue
            creator = None
            if workflow_id and {"workflow_id", "created_by", "revision"} <= revisions and "users" in tables:
                creator = conn.execute(
                    text(
                        "SELECT r.created_by FROM workflow_revisions r JOIN users u ON u.id = r.created_by "
                        "WHERE r.workflow_id = :id ORDER BY r.revision LIMIT 1"
                    ),
                    {"id": workflow_id},
                ).scalar()
            if creator is None and "workspace_members" in tables:
                creator = conn.execute(
                    text(
                        "SELECT user_id FROM workspace_members WHERE workspace_id = :ws AND role = 'owner' "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"ws": workspace_id},
                ).scalar()
            conn.execute(
                text("UPDATE agent_sessions SET owner_user_id = :owner WHERE id = :id AND owner_user_id IS NULL"),
                {"owner": creator, "id": session_id},
            )


def _migrate_agent_sessions_know_who_named_them() -> None:
    """`agent_sessions.title_source`:这个名字是谁起的(维护者 2026-10-07 对 ADR 0044 的修订,见 domain/agent/titles)。

    `auto` 还由我们起、`generated` 第一轮问答之后模型起的、`manual` 人起的 —— 人起的永远不碰。老对话分不清哪些是人改过的,
    一律按人起的算(`manual`):名字已经在历史里认了好久,宁可不替它起,也不能盖掉一个人改的名字。还叫「新对话」的(说过话、
    却从没起过名的,比如只收到过别的对话的通知)留 `auto`,它下一次有人说话时照常起名。

    加列必须在 SCHEMA 之前:之后 ORM 上的 AgentSession 已经指望它在了。只在这一轮真加了列时回填。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
        if not columns or "title_source" in columns:
            return
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN title_source VARCHAR(16) NOT NULL DEFAULT 'auto'"))
        conn.execute(text("UPDATE agent_sessions SET title_source = 'manual' WHERE title != '新对话'"))


def _migrate_provider_models_remember_their_group() -> None:
    """`provider_models.declared_group`:连接说这个模型是哪样东西的哪个入口(ADR 0045,ComfyUI 一张工作流的完整工作流和
    它的表单是同一组)。只加列、不回填:它和 `declared_capabilities` 一样只由插件目录写,插件版本进了目录指纹,升级后第一次
    刷新就写上。加列必须在 SCHEMA 之前:之后 ORM 上的 ProviderModel 已经指望它在了。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_models)"))}
        if not columns or "declared_group" in columns:
            return
        conn.execute(text("ALTER TABLE provider_models ADD COLUMN declared_group JSON"))


def _migrate_plugin_instances_remember_applied_moves() -> None:
    """`plugin_instances.applied_moves`:插件报过的一次性改名,这个连接上做过哪几批(ADR 0045,见 domain/plugins/moves)。
    老连接一批都没做过(空表),升级后第一次刷新目录时做。加列必须在 SCHEMA 之前:之后 ORM 上的 PluginInstance 已经指望它在了。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plugin_instances)"))}
        if not columns or "applied_moves" in columns:
            return
        conn.execute(text("ALTER TABLE plugin_instances ADD COLUMN applied_moves JSON NOT NULL DEFAULT '{}'"))


def _migrate_webhook_secrets_are_hashed() -> None:
    """定时任务的 webhook 触发密钥从 `payload.webhook_secret`(明文)搬到 `webhook_secret_hash`(只存哈希)。

    明文那一份随列表接口发给工作区里的每个人,只读成员拿着它不用登录就能触发、取消以主人身份跑的运行。
    改成和会话令牌一样只存哈希(见 core/tokens.token_digest):外部系统手上那串没变,校验时再哈希一次就对得上 ——
    **已经接好的集成不会断**。`webhook_secret_set_at` 留空:这把密钥曾经对所有人可见,界面提醒主人重置一次。

    加列必须在 SCHEMA 之前:之后 ORM 上的 ScheduledTask 已经指望它们在了。幂等:payload 里没有明文的行不碰。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_tasks)"))}
        if not columns:
            return
        if "webhook_secret_hash" not in columns:
            conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN webhook_secret_hash VARCHAR(80)"))
        if "webhook_secret_set_at" not in columns:
            conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN webhook_secret_set_at DATETIME"))
        for row in conn.execute(text("SELECT id, payload FROM scheduled_tasks")).mappings().all():
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    continue
            if not isinstance(payload, dict) or "webhook_secret" not in payload:
                continue
            secret = payload.pop("webhook_secret")
            conn.execute(
                text("UPDATE scheduled_tasks SET payload = :payload, webhook_secret_hash = :hashed WHERE id = :id"),
                {
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "hashed": token_digest(str(secret)) if isinstance(secret, str) and secret else None,
                    "id": row["id"],
                },
            )


def _migrate_applied_moves_remember_old_names() -> None:
    """`plugin_instances.applied_moves` 从 `{能力: [key…]}` 改成 `{能力: {key: [旧名字…]}}`(见 domain/plugins/moves,PLG-2):
    一次性的改名按 key **和旧名字**记账 —— 同一批改名的几个名字不一定同一次报出来,只按 key 记,晚来的那几条会被当成做过了。

    老账只说「这个 key 做过」,没说做了哪几个名字。那一次是按当时插件报的全部名字做的(1.20 读得懂当时每一张表单),所以换成
    「这个连接现在有的全部名字」:生成目录是它的模型行的 id,工具清单是存着的工具名 —— 现在有的名字都已经是它们现在的意思,
    以后报上来的、这里没有的旧名字(之后才升级上来的那几张)照样改一次。别的能力(插件以后自己报的)没有可数的名字,记成空的
    一串。幂等:已经是新形状的那几格不动。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plugin_instances)"))}
        if "applied_moves" not in columns:
            return
        for instance_id, raw_moves, raw_tools in conn.execute(
            text("SELECT id, applied_moves, discovered_tools FROM plugin_instances")
        ).fetchall():
            try:
                ledger = json.loads(raw_moves) if isinstance(raw_moves, str) else (raw_moves or {})
            except ValueError:
                ledger = {}
            if not isinstance(ledger, dict) or not any(isinstance(keys, list) for keys in ledger.values()):
                continue
            names: dict[str, list[str]] = {
                "generation": sorted({str(row[0]) for row in conn.execute(text(
                    "SELECT m.model_id FROM provider_models m JOIN provider_profiles p ON p.id = m.provider_profile_id"
                    " WHERE p.plugin_instance_id = :i"), {"i": instance_id})}),
            }
            try:
                tools = json.loads(raw_tools) if isinstance(raw_tools, str) else (raw_tools or [])
            except ValueError:
                tools = []
            names["tools"] = sorted({str(one["name"]) for one in tools if isinstance(one, dict) and one.get("name")}) \
                if isinstance(tools, list) else []
            converted = {
                capability: ({key: names.get(capability, []) for key in keys if isinstance(key, str)}
                             if isinstance(keys, list) else keys)
                for capability, keys in ledger.items()
            }
            conn.execute(text("UPDATE plugin_instances SET applied_moves = :m WHERE id = :i"),
                         {"m": json.dumps(converted, ensure_ascii=False), "i": instance_id})


def _drop_empty_agent_sessions() -> None:
    """删掉从没说过话的那些空对话(维护者 2026-10-07 确认)。

    此前「新对话」一点就建一行、改一下模型也先建一行,历史里攒下一排「新对话」。现在打开智能体是一段还没建出来的草稿,
    第一句话发出去才建(见 frontend features/agent/currentAgentSession),这些空行没有任何东西指着,删掉。判据在下面:
    **有一条消息、一张卡、一笔用量的都不删**。它们的共享记录一起删(否则留下指向空的共享行)。

    排在 SCHEMA 之后、重建删列之后:那时死路由建的那批已经是 `ui` 了,空的一起删。
    """
    tables = set(inspect(engine).get_table_names())
    needed = {"agent_sessions", "agent_messages", "tool_confirmations", "agent_questions", "agent_skills", "provider_usage_events"}
    if not needed <= tables:
        return
    #: 「空的」:界面上从没说过话的那种 —— 没有一条消息(排着的话、任务回执也是消息)、没有确认卡、没有选择卡、没有技能记着它、
    #: 没有记在它名下的用量。只删界面建的(飞书那种不进界面清单)。
    empty_sql = (
        "SELECT s.id FROM agent_sessions s WHERE s.origin = 'ui'"
        " AND NOT EXISTS (SELECT 1 FROM agent_messages m WHERE m.session_id = s.id)"
        " AND NOT EXISTS (SELECT 1 FROM tool_confirmations c WHERE c.session_id = s.id)"
        " AND NOT EXISTS (SELECT 1 FROM agent_questions q WHERE q.session_id = s.id)"
        " AND NOT EXISTS (SELECT 1 FROM agent_skills k WHERE k.agent_session_id = s.id)"
        " AND NOT EXISTS (SELECT 1 FROM provider_usage_events u WHERE u.source_type = 'agent_session' AND u.source_id = s.id)"
    )
    with engine.begin() as conn:
        empty = [row[0] for row in conn.execute(text(empty_sql))]
        for session_id in empty:
            if "resource_shares" in tables:
                conn.execute(
                    text("DELETE FROM resource_shares WHERE kind = 'agent_session' AND resource_id = :id"), {"id": session_id}
                )
            conn.execute(text("DELETE FROM agent_sessions WHERE id = :id"), {"id": session_id})
    if empty:
        logger.info("deleted %d empty agent conversations (never had a message)", len(empty))


def _expire_orphaned_session_confirmations() -> None:
    """挂在对话上、还在等人的确认卡,作废(ADR 0007 修订 2026-10-08)。

    此前一轮结束(用户停止、卡等满 590 秒、整轮超时、失败)时,它正等着的那张卡原样留着:仍是 `pending`、仍能批、批了照样
    执行,而模型被告知「失败 / 没发生」、结果也送不回对话(全局确认中心里还一直挂着)。现在一轮收尾时 host 把这段对话还在等的
    卡结成 `expired`;这一步处理升级之前留下的那些。**迁移跑在启动时、任何一轮开跑之前**,所以这一刻挂在对话上的待决卡没有一张
    还有人在等,全部作废。没挂对话的(MCP 直连、工作流节点开的)不碰:它们不属于哪一轮。

    同一步把老的 `cancelled`(后端重启时作废的,`host.reconcile_orphaned_agent_sessions` 此前写的)也改成 `expired` ——
    「卡已作废」只剩一种状态,界面不留第二个分支。原因记成机器认的码(界面按它说人话)。幂等。
    """
    if "tool_confirmations" not in set(inspect(engine).get_table_names()):
        return
    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(tool_confirmations)"))}
        if not {"session_id", "status", "error", "resolved_at"} <= columns:
            return
        restarted = conn.execute(
            text("UPDATE tool_confirmations SET status = 'expired', error = 'backend_restarted' WHERE status = 'cancelled'")
        ).rowcount
        orphaned = conn.execute(
            text(
                "UPDATE tool_confirmations SET status = 'expired', error = 'orphaned', resolved_at = :now"
                " WHERE status = 'pending' AND session_id IS NOT NULL AND session_id != ''"
            ),
            {"now": stamp},
        ).rowcount
    if restarted or orphaned:
        logger.info("expired %d orphaned confirmation cards (and relabelled %d cancelled ones)", orphaned, restarted)


def _drop_dead_agent_session_columns() -> None:
    """删掉 `agent_sessions` 上早就没人读、模型上也没有了的列 —— 下一步重建这张表之前。

    重建(`_rebuild_dropping`)遇到模型上没有、又不在删除名单里的列会拒绝动手(那可能是谁的数据),所以老库里还留着的死列
    得先在这里点名删掉。翻遍这张表的历史(Alembic 0008 建表、之后的 ORM 和本文件的加列),模型上已经没有的只有这两列:

    - `adapter_session_id`:给 Claude Code CLI 那条适配器的 `--resume` 用的。`4a2e51e4b`「删掉 claude 适配器」之后再没人写、
      没人读,但从 Alembic 0008 那一代升上来的库里一直留着(维护者的库里 63 行全是 NULL;更老的装机可能还存着值,同样没有读者);
    - `sort_order`:`_migrate_agent_session_order` 删过一次,可那一步遇到不支持 DROP COLUMN 的老 SQLite 会跳过、并且照样记账,
      之后不会再试 —— 那种库里它还在。

    两列都没有索引、外键和约束,`DROP COLUMN` 直接删。删不掉就让启动报错(说清是哪一步),不悄悄跳过:跳过的话下一步重建照样拒绝。
    表还没有就什么都不做。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
        for dead in ("adapter_session_id", "sort_order"):
            if dead in columns:
                conn.execute(text(f"ALTER TABLE agent_sessions DROP COLUMN {dead}"))


def _drop_agent_sessions_project_id() -> None:
    """删掉 `agent_sessions.project_id`:它由家代替了(ADR 0044 §1,上一步已经把不空的那些转成家)。

    这一列带外键(`REFERENCES projects(id)`),SQLite 的 `DROP COLUMN` 对外键列直接报错 —— `provider_profiles` 那种「删不掉
    就跳过」在这里是**永远**跳过。所以重建这张表,见 `_rebuild_dropping`。排在 SCHEMA 之后:新表照现在的 ORM 建,那时 ORM
    要的列都已经在老表上了。
    """
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
    if "project_id" in columns:
        _rebuild_dropping("agent_sessions", ("project_id",))


def _migrate_publish_records_outlive_their_asset() -> None:
    """删素材不再连带删掉它的发布记录(MED-3):`publish_tasks.asset_id` 从「不可空、`ON DELETE CASCADE`」改成「可空、
    `SET NULL`」,并加上 `asset_name` —— 素材没了,记录还说得出发的是什么。

    此前删一份发过的成片腾空间,发布历史和平台上的作品 ID(`post`,之后查播放、评论的唯一线索)跟着没了。SQLite 改不了
    已有列的外键动作和可空性,只能照现在的 ORM 重建这张表(见 `_rebuild_dropping`,这里一列都不删)。重建之后按还在的素材
    回填 `asset_name`;建这一列之前就删掉的素材,连同记录早已级联删掉,无从回填。

    表还没有就什么都不做;外键、可空、列都已经是新形状就只补名字。幂等。
    """
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
        if "publish_tasks" not in tables:
            return
        # table_info: (cid, name, type, notnull, dflt_value, pk);foreign_key_list: (id, seq, table, from, to, on_update, on_delete, match)
        columns = {row[1]: row for row in conn.execute(text("PRAGMA table_info(publish_tasks)"))}
        on_delete = {row[3]: row[6] for row in conn.execute(text("PRAGMA foreign_key_list(publish_tasks)"))}
    if on_delete.get("asset_id") != "SET NULL" or columns["asset_id"][3] or "asset_name" not in columns:
        _rebuild_dropping("publish_tasks", ())
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE publish_tasks SET asset_name = "
            "(SELECT COALESCE(assets.name, '') FROM assets WHERE assets.id = publish_tasks.asset_id) "
            "WHERE asset_name = '' AND asset_id IN (SELECT id FROM assets)"
        ))


def _migrate_scheduled_tasks_vouch_for_what_they_run() -> None:
    """ADR 0047 D11:定时任务从这一版起,要「被执行的那一版有主人担保」才花主人的 AI 连接 / 插件连接。

    升级前它们就是这样在跑的,升级不该让它们一夜之间全停在「这一版要你认可」:给每个工作流任务的主人,对绑着的那张图的
    **当前版**、以及它字面量调用的子流程的当前版(顺下去),各记一条认可。已经是担保人的(作者、认可过的)不重复记。
    以后别人再改,要主人认可(只提醒、不拦,见 domain/scheduler/approvals)。

    自成一体,不调领域代码:领域的判据以后会变,迁移认的是这一刻的形状。子流程按字面量的 `workflow_id` 找
    (循环体、子图里的也算;写成引用、由数据边供的不算 —— 那是运行时才知道的)。幂等:重跑时都已是担保人,什么都不记。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"scheduled_tasks", "workflows", "workflow_revisions", "workflow_revision_attestations"} <= tables:
        return
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import ScheduledTask, Workflow, WorkflowRevision, WorkflowRevisionAttestation

    def called(graph: Any) -> list[str]:
        if not isinstance(graph, dict):
            return []
        edges = [edge for edge in graph.get("edges") or [] if isinstance(edge, dict)]
        found: list[str] = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            target = config.get("workflow_id")
            bound = any(edge.get("kind") == "data" and str(edge.get("target")) == str(node.get("id"))
                        and edge.get("target_input") == "workflow_id" for edge in edges)
            if node.get("type") == "call_workflow" and isinstance(target, str) and target.strip() \
                    and "{{" not in target and not bound:
                found.append(target.strip())
            found.extend(called(config.get("body")))
        return found

    with Session(engine) as db:
        for task in db.scalars(select(ScheduledTask).where(ScheduledTask.kind == "workflow")).all():
            owner = task.owner_user_id
            payload = task.payload if isinstance(task.payload, dict) else {}
            if not owner:
                continue
            frontier = [str(payload.get("workflow_id") or "")]
            seen: set[str] = set()
            while frontier:
                workflow_id = frontier.pop()
                if not workflow_id or workflow_id in seen:
                    continue
                seen.add(workflow_id)
                workflow = db.get(Workflow, workflow_id)
                if workflow is None or workflow.workspace_id != task.workspace_id:
                    continue
                revision = db.scalar(select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == workflow.id, WorkflowRevision.revision == workflow.revision))
                if revision is None:
                    continue
                attested = db.scalar(select(WorkflowRevisionAttestation.id).where(
                    WorkflowRevisionAttestation.revision_id == revision.id, WorkflowRevisionAttestation.user_id == owner))
                if revision.created_by != owner and attested is None:
                    db.add(WorkflowRevisionAttestation(revision_id=revision.id, user_id=owner))
                    # 同一版可能被这个主人的好几个任务绑着(或被调用好几次):先落下,下一次查得到。
                    db.flush()
                frontier.extend(called(revision.graph))
        db.commit()


def _migrate_deployments_know_their_web_address() -> None:
    """deployment_config 新增 web_url:成员用浏览器打开 Mosael 的地址(ADR 0054 D52)。空串 = 没有网页版(桌面单机),
    邀请只给 `mosael://` 深链。create_all 只建新表,不给已有表补列;加列要在 SCHEMA 之前。"""
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "web_url" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN web_url VARCHAR(500) NOT NULL DEFAULT ''"))


def _migrate_usage_remembers_who_spent() -> None:
    """provider_usage_events 新增 user_id:替谁花的钱(ADR 0050 D30)。不设外键 —— 审计信息,人删了这笔钱照样是他花的。
    加列要在 SCHEMA 之前;老账找人在 SCHEMA 之后那一步(`_migrate_usage_finds_who_spent_it`)。"""
    inspector = inspect(engine)
    if "provider_usage_events" not in set(inspector.get_table_names()):
        return
    if "user_id" in {c["name"] for c in inspector.get_columns("provider_usage_events")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_usage_events ADD COLUMN user_id VARCHAR(64)"))


def _migrate_deployments_keep_finished_jobs_for_a_year() -> None:
    """deployment_config 新增 job_retention_days:结束多少天的任务行由保留清理删掉(ADR 0050 D29),默认 365;空 = 永久。
    此前任务行只由「清空已结束」删(一个成员一点,全工作区的历史没了);这一版起清空只挪水位线,删交给保留清理。"""
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "job_retention_days" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN job_retention_days INTEGER DEFAULT 365"))


def _migrate_usage_finds_who_spent_it() -> None:
    """老账补上是谁花的(ADR 0050 D30、D31)。按线索逐类找,**找不到的留空**(管理概览里列「无归属」),不猜给工作区主人 ——
    猜错了比空着更糟。只填还空着的;找到的人得还在(用量的 `source_id` 是字符串,对不上任何账号的不填)。幂等。

    - 挂着任务的:任务的发起人(定时任务跑的是任务主人,当时就这样记在任务上);
    - 智能体那一轮(`agent_message_id`,或没挂上时 `source_id` 就是那条消息):会话主人;
    - 起名、技能草稿(`agent_session`):会话主人;
    - 生成(`generation_job`):生成会话的主人;
    - 念笔记、试听(`note_read_aloud` / `voice_preview`):`source_id` 就是那个人。

    `workflow` / `board` / `asset` 那几类只记了资源 id,不知道当时是谁点的,留空。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"provider_usage_events", "users"} <= tables:
        return
    columns = {c["name"] for c in inspect(engine).get_columns("provider_usage_events")}
    if "user_id" not in columns:
        return
    known = "EXISTS (SELECT 1 FROM users u WHERE u.id = {})"
    steps: list[str] = []
    if "jobs" in tables:
        steps.append(
            "UPDATE provider_usage_events SET user_id = (SELECT j.created_by FROM jobs j WHERE j.id = provider_usage_events.job_id)"
            " WHERE user_id IS NULL AND job_id IS NOT NULL AND "
            + known.format("(SELECT j.created_by FROM jobs j WHERE j.id = provider_usage_events.job_id)")
        )
    if {"agent_messages", "agent_sessions"} <= tables:
        owner_of_message = (
            "(SELECT s.owner_user_id FROM agent_messages m JOIN agent_sessions s ON s.id = m.session_id WHERE m.id = {})"
        )
        for message in ("provider_usage_events.agent_message_id", "provider_usage_events.source_id"):
            found = owner_of_message.format(message)
            guard = "agent_message_id IS NOT NULL" if message.endswith("agent_message_id") else "source_type = 'agent_message'"
            steps.append(f"UPDATE provider_usage_events SET user_id = {found} WHERE user_id IS NULL AND {guard} AND " + known.format(found))
    if "agent_sessions" in tables:
        found = "(SELECT s.owner_user_id FROM agent_sessions s WHERE s.id = provider_usage_events.source_id)"
        steps.append(
            f"UPDATE provider_usage_events SET user_id = {found} WHERE user_id IS NULL AND source_type = 'agent_session' AND "
            + known.format(found)
        )
    if {"generation_jobs", "generation_sessions"} <= tables:
        found = (
            "(SELECT gs.owner_user_id FROM generation_jobs g JOIN generation_sessions gs ON gs.id = g.session_id"
            " WHERE g.id = provider_usage_events.source_id)"
        )
        steps.append(
            f"UPDATE provider_usage_events SET user_id = {found} WHERE user_id IS NULL AND source_type = 'generation_job' AND "
            + known.format(found)
        )
    steps.append(
        "UPDATE provider_usage_events SET user_id = source_id WHERE user_id IS NULL"
        " AND source_type IN ('note_read_aloud', 'voice_preview') AND " + known.format("provider_usage_events.source_id")
    )
    with engine.begin() as conn:
        for statement in steps:
            conn.execute(text(statement))


def _migrate_registration_invites_become_invite_links() -> None:
    """注册邀请码(`registration_invites`)并进邀请链接(`invite_links`,ADR 0054 D50):不带工作区、部署管理员发的。

    老码**照样用到过期**:库里此前存的是原文(主键就是码),这里换成和会话令牌同一个哈希(core/tokens.token_digest),
    记下末尾四位给列表认;没过期的、用过的(记着这个账号是凭谁的码进来的)都搬,原文不再留在库里。「能顺带注册」
    记在发码的人头上 —— 只有部署管理员发得了码。搬完删掉旧表。幂等:旧表不在就什么都不做。
    """
    tables = set(inspect(engine).get_table_names())
    if "registration_invites" not in tables or "invite_links" not in tables:
        return
    with engine.begin() as conn:
        for row in conn.execute(text(
            "SELECT code, created_by, note, used_by, created_at, expires_at FROM registration_invites"
        )).mappings().all():
            code = str(row["code"] or "")
            if not code:
                continue
            digest = token_digest(code)
            if conn.execute(text("SELECT 1 FROM invite_links WHERE code_hash = :h"), {"h": digest}).first() is not None:
                continue
            conn.execute(
                text(
                    "INSERT INTO invite_links (id, code_hash, code_hint, workspace_id, role, created_by, note,"
                    " signup_approved_by, expires_at, used_by, used_at, created_at)"
                    " VALUES (:id, :h, :hint, NULL, '', :by, :note, :by, :expires, :used_by, :used_at, :created)"
                ),
                {
                    "id": uuid.uuid4().hex, "h": digest, "hint": code[-4:], "by": row["created_by"],
                    "note": row["note"] or "", "expires": row["expires_at"], "used_by": row["used_by"],
                    #: 老表没记用掉的时间:用发码时间顶上(只用来排序、显示「用过」)。
                    "used_at": row["created_at"] if row["used_by"] else None, "created": row["created_at"],
                },
            )
        conn.execute(text("DROP TABLE registration_invites"))


def _drop_invitations_and_notifications_of_people_who_are_gone() -> None:
    """指着已经不在的人的工作区邀请(受邀人或邀请人)和通知(收件人)删掉。

    外键写的是 ON DELETE CASCADE,可早先删账号时 SQLite 的外键检查没开,删掉的人留下了孤儿 —— 维护者库的
    `PRAGMA foreign_key_check` 报出两行:一条 2026-07-22 的待处理邀请(受邀人已不在)、一条团队通知(收件人已不在)。
    它们谁都看不见(列表按人连表,连不上的那行自然不出现),但每次核对外键都报,也挡着以后要开的外键检查。幂等。
    """
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        if {"workspace_invitations", "users"} <= tables:
            conn.execute(text(
                "DELETE FROM workspace_invitations WHERE invitee_id NOT IN (SELECT id FROM users)"
                " OR inviter_id NOT IN (SELECT id FROM users)"
            ))
        if {"notifications", "users"} <= tables:
            conn.execute(text("DELETE FROM notifications WHERE user_id NOT IN (SELECT id FROM users)"))


def _foreign_key_violations(sqlite: Any, tables: list[str]) -> Counter[tuple[str, str]]:
    """这几张表上「指向不存在的行」的外键,按 (子表, 父表) 计数。按计数比,不按 rowid:重建的那张表 rowid 会变。"""
    found: Counter[tuple[str, str]] = Counter()
    for table in tables:
        for row in sqlite.execute(f'PRAGMA foreign_key_check("{table}")'):
            found[(row[0], row[2])] += 1
    return found


def _rebuild_dropping(table: str, columns: tuple[str, ...]) -> None:
    """重建 `table`、去掉 `columns` —— 删带外键的列只能这样(SQLite 的 `DROP COLUMN` 对外键列报错)。按 SQLite 文档的十二步:

    **先关外键**(在事务外,事务里设它不生效)→ 照现在的 ORM 建 `<表>__rebuilt` → 原样搬数据 → 删旧表 → 改名 → 补索引 →
    外键检查 → 提交 → 开外键。

    **不关外键就删旧表,别的表指着它的 `ON DELETE CASCADE` 会一起删**:`agent_messages` 的全部消息、跟着消息走的用量记录
    (`SET NULL`)、技能上记着的「在哪次对话里建的」……所以关没关上要读回来确认,没关上就不动手。外键检查查的是**指着这张表**
    的那些表、比的是重建前后的**差**:重建能弄坏的只有「它们指着的行不见了」;库里本来就有的悬空引用(老版本留下的)不该让
    升级起不来,重建本身多出来的一条都不许。这张表自己的外键列是原样搬过来的,搬不出新的悬空。

    搬数据只搬新旧两边都有的列;旧表上有、ORM 上没有、又不在 `columns` 里的列 —— 重建会把它丢掉 —— 当场拒绝。整个过程一个
    事务:任何一步失败,库原样不动。
    """
    from sqlalchemy.schema import CreateIndex, CreateTable

    model = Base.metadata.tables[table]
    rebuilt = f"{table}__rebuilt"
    raw = engine.raw_connection()
    try:
        sqlite = raw.driver_connection
        sqlite.execute("PRAGMA foreign_keys=OFF")
        try:
            if sqlite.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
                raise RuntimeError(f"refusing to rebuild {table}: foreign keys are still on, dropping it would cascade")
            sqlite.execute("BEGIN")
            try:
                old = [row[1] for row in sqlite.execute(f'PRAGMA table_info("{table}")')]
                lost = sorted(set(old) - set(columns) - set(model.columns.keys()))
                if lost:
                    raise RuntimeError(f"refusing to rebuild {table}: these columns are not on the model and would be lost: {lost}")
                children = [
                    name for (name,) in sqlite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                    if any(row[2] == table for row in sqlite.execute(f'PRAGMA foreign_key_list("{name}")'))
                ]
                before = _foreign_key_violations(sqlite, children)
                create = str(CreateTable(model).compile(dialect=engine.dialect)).strip()
                head = f"CREATE TABLE {table} ("
                if not create.startswith(head):
                    raise RuntimeError(f"unexpected CREATE TABLE for {table}: {create[:80]}")
                sqlite.execute(f'DROP TABLE IF EXISTS "{rebuilt}"')
                sqlite.execute(f'CREATE TABLE "{rebuilt}" (' + create[len(head):])
                kept = ", ".join(f'"{column.name}"' for column in model.columns if column.name in old)
                sqlite.execute(f'INSERT INTO "{rebuilt}" ({kept}) SELECT {kept} FROM "{table}"')
                copied = sqlite.execute(f'SELECT count(*) FROM "{rebuilt}"').fetchone()[0]
                original = sqlite.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                if copied != original:
                    raise RuntimeError(f"rebuilding {table} copied {copied} of {original} rows")
                sqlite.execute(f'DROP TABLE "{table}"')
                sqlite.execute(f'ALTER TABLE "{rebuilt}" RENAME TO "{table}"')
                for index in model.indexes:
                    sqlite.execute(str(CreateIndex(index).compile(dialect=engine.dialect)))
                grown = _foreign_key_violations(sqlite, children) - before
                if grown:
                    raise RuntimeError(f"rebuilding {table} left new dangling foreign keys: {dict(grown)}")
                sqlite.commit()
            except BaseException:
                sqlite.rollback()
                raise
        finally:
            sqlite.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()


def _migrate_install_sources_get_pytorch_and_github() -> None:
    """「管理 → 下载源」多两行:PyTorch 源(`tts_config.pytorch_index`)、GitHub 镜像前缀(`tts_config.github_mirror`),
    给「让 Mosael 装」用(ADR 0041 §4)。空 = 官方 / 直连,和老库的行为一样。

    加列必须在 SCHEMA 之前:之后 ORM 上的 TtsConfig 已经指望它们在了。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(tts_config)"))}
        if not columns:
            return
        if "pytorch_index" not in columns:
            conn.execute(text("ALTER TABLE tts_config ADD COLUMN pytorch_index VARCHAR(200) NOT NULL DEFAULT ''"))
        if "github_mirror" not in columns:
            conn.execute(text("ALTER TABLE tts_config ADD COLUMN github_mirror VARCHAR(500) NOT NULL DEFAULT ''"))


def _create_current_schema() -> None:
    """The single boundary between migrations for existing tables and new-table creation."""

    Base.metadata.create_all(bind=engine)


def _steps(phase: MigrationPhase, *operations: Any) -> tuple[MigrationStep, ...]:
    """Give private Python operations stable, log-friendly migration identities.

    默认是**一次性**的:跑成功就记进 schema_migrations,下次启动跳过(见 migration_runner)。
    """

    return tuple(
        MigrationStep(operation.__name__.lstrip("_").replace("_", "-"), phase, operation)
        for operation in operations
    )


def _recurring(phase: MigrationPhase, *operations: Any) -> tuple[MigrationStep, ...]:
    """**对账**,不是迁移:每次启动都要跑,不记账。

    判据是「它处理的东西还会再出现」:孤儿共享记录会随新的删除再产生;job 的消息键要跟着
    文案表变;当前 schema 要为新表跑 create_all。而「把某列的旧形状转成新形状」只会有一次。
    """

    return tuple(
        MigrationStep(operation.__name__.lstrip("_").replace("_", "-"), phase, operation, once=False)
        for operation in operations
    )


def _migrate_speech_and_podcast_join_creation_sessions() -> None:
    """创作页之前做的语音、播客并进创作会话(ADR 0055 §8):每人每种一条「以前的语音」/「以前的播客」。

    此前它们只有任务行(`kind` 为 tts / podcast)和产出的素材,没有会话、没有记录;请求只在任务的 payload 里,文字只存了
    前 200 字(播客 500 字)。收的是:成功了的、顶层的(工作流派的子任务不收)、有人发起的、不是零件的(字幕配音逐句的
    `intermediate`)、产出还在而且不是零件、还没有记录指着它的任务。按(工作区、发起人、种类)各开一条会话,主人是发起人;
    每个任务一条记录,时间照任务的;文字只剩开头的,记录上标 `truncated`。补上 `generated_assets` 那一行;播客的对谈稿
    (`result.texts`)抄进素材的 `media_info.dialogue`、发音人抄进 `media_info.speakers`(还没有才抄)。

    任务行已经被「清空已结束」删掉的老产出,素材上没记是谁做的,开不了私人会话:**留在素材库里,不进会话**。分不出来源的
    顶层任务(画板「念出来」、笔记朗读)一并收进来 —— 宁可多收几条,不丢。音色名不在这里查(内置音色表是会变的代码),
    配音库里的嗓子写它的名字,别的留给界面按引擎的音色目录认。
    """
    needed = {"jobs", "generation_sessions", "generation_jobs", "generated_assets", "assets", "users"}
    tables = set(inspect(engine).get_table_names())
    if not needed <= tables:
        return
    titles = {"speech": "以前的语音", "podcast": "以前的播客"}
    kinds = {"tts": "speech", "podcast": "podcast"}
    limits = {"speech": 200, "podcast": 500}

    def _object(raw: Any) -> dict[str, Any]:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT j.id, j.workspace_id, j.kind, j.created_by, j.payload, j.result, j.created_at, j.updated_at "
            "FROM jobs j WHERE j.kind IN ('tts', 'podcast') AND j.status = 'succeeded' AND j.parent_job_id IS NULL "
            "AND j.created_by IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM generation_jobs g WHERE g.job_id = j.id) "
            "ORDER BY j.created_at, j.id"
        )).all()
        if not rows:
            return
        users = {one for (one,) in conn.execute(text("SELECT id FROM users"))}
        profiles = (
            {one for (one,) in conn.execute(text("SELECT id FROM provider_profiles"))}
            if "provider_profiles" in tables else set()
        )
        voice_names = (
            {one: name for one, name in conn.execute(text("SELECT id, name FROM voices"))} if "voices" in tables else {}
        )
        sessions: dict[tuple[str, str, str], str] = {}
        for job_id, workspace_id, job_kind, created_by, raw_payload, raw_result, created_at, updated_at in rows:
            payload, result = _object(raw_payload), _object(raw_result)
            if str(payload.get("intermediate") or "") or created_by not in users:
                continue
            asset_id = str(result.get("asset_id") or "")
            asset = conn.execute(
                text("SELECT media_info, intermediate FROM assets WHERE id = :id AND workspace_id = :ws"),
                {"id": asset_id, "ws": workspace_id},
            ).first() if asset_id else None
            if asset is None or asset[1]:
                continue
            kind = kinds[job_kind]
            if kind == "speech":
                voice_id = str(payload.get("voice_id") or "")
                provider = str(payload.get("engine") or "") or "builtin:clone"
                model = voice_id or str(payload.get("engine_voice") or "")
                prompt = str(payload.get("text") or "")
                request: dict[str, Any] = {"prompt": prompt, "voice": model}
                if voice_id in voice_names:
                    request["voice_label"] = voice_names[voice_id]
                if payload.get("clone_engine"):
                    request["clone_engine"] = str(payload["clone_engine"])
            else:
                provider, model = "builtin:volcano-podcast", "dialogue"
                mode = str(payload.get("mode") or "summarize")
                prompt = str(payload.get("topic") or "") if mode == "research" else str(payload.get("text") or "")
                speakers = [str(one) for one in payload.get("speakers") or [] if one]
                request = {"mode": mode, "prompt": prompt, "speakers": [{"value": one, "label": ""} for one in speakers]}
                media_info = _object(asset[0])
                texts = result.get("texts")
                if isinstance(texts, list) and texts and "dialogue" not in media_info:
                    media_info["dialogue"] = [
                        {"speaker": str(one.get("speaker") or ""), "text": str(one.get("text") or "")}
                        for one in texts if isinstance(one, dict)
                    ]
                    media_info.setdefault("speakers", [{"value": one, "label": ""} for one in speakers])
                    conn.execute(
                        text("UPDATE assets SET media_info = :info WHERE id = :id"),
                        {"info": json.dumps(media_info, ensure_ascii=False), "id": asset_id},
                    )
            #: payload 只存了开头(主题例外,它存的是全文):够长的就是被截过的,界面写「只保留了开头」。
            if len(prompt) >= limits[kind] and request.get("mode") != "research":
                request["truncated"] = True
            key = (workspace_id, created_by, kind)
            session_id = sessions.get(key)
            if session_id is None:
                session_id = uuid.uuid4().hex
                sessions[key] = session_id
                conn.execute(
                    text(
                        "INSERT INTO generation_sessions (id, workspace_id, owner_user_id, title, group_id, "
                        "provider_profile_id, model, kind, created_at, updated_at) "
                        "VALUES (:id, :ws, :owner, :title, NULL, NULL, :model, :kind, :created, :updated)"
                    ),
                    {"id": session_id, "ws": workspace_id, "owner": created_by, "title": titles[kind],
                     "model": provider, "kind": kind, "created": created_at, "updated": updated_at},
                )
            else:
                conn.execute(
                    text("UPDATE generation_sessions SET updated_at = :updated, model = :model WHERE id = :id"),
                    {"updated": updated_at, "model": provider, "id": session_id},
                )
            profile = str(payload.get("provider_profile_id") or "")
            conn.execute(
                text(
                    "INSERT INTO generation_jobs (id, workspace_id, session_id, job_id, provider_profile_id, provider, "
                    "model, kind, request, result_asset_id, error, error_key, error_params, created_at, updated_at) "
                    "VALUES (:id, :ws, :session, :job, :profile, :provider, :model, :kind, :request, :asset, NULL, '', "
                    "'{}', :created, :updated)"
                ),
                {"id": uuid.uuid4().hex, "ws": workspace_id, "session": session_id, "job": job_id,
                 "profile": profile if profile in profiles else None, "provider": provider, "model": model,
                 "kind": kind, "request": json.dumps(request, ensure_ascii=False), "asset": asset_id,
                 "created": created_at, "updated": updated_at},
            )
            if conn.execute(text("SELECT 1 FROM generated_assets WHERE asset_id = :id"), {"id": asset_id}).first() is None:
                conn.execute(
                    text(
                        "INSERT INTO generated_assets (asset_id, provider, model, prompt, parameters, job_id) "
                        "VALUES (:asset, :provider, :model, :prompt, :parameters, :job)"
                    ),
                    {"asset": asset_id, "provider": provider, "model": model, "prompt": prompt,
                     "parameters": json.dumps({key: value for key, value in request.items() if key != "prompt"},
                                              ensure_ascii=False),
                     "job": job_id},
                )


def _migrate_generation_sessions_get_an_origin() -> None:
    """生成会话记出处(ADR 0052 §1):`generation_sessions` 加 `origin_kind`(默认 `studio`)、`origin_id`(默认空)和「这个人在这一处
    的那条会话」按它找的索引。老会话的出处由 SCHEMA 之后的 `_migrate_generation_sessions_origin_from_facts` 按事实补。

    加列必须在 SCHEMA 之前:之后 ORM 上的 GenerationSession 已经指望它们在了。表还没有就什么都不做。幂等。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(generation_sessions)"))}
        if not columns:
            return
        if "origin_kind" not in columns:
            conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN origin_kind VARCHAR(16) NOT NULL DEFAULT 'studio'"))
        if "origin_id" not in columns:
            conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN origin_id VARCHAR(700) NOT NULL DEFAULT ''"))
        #: 很老的库这时还没有 `owner_user_id`(由 SCHEMA 之后的 `_migrate_resource_ownership` 补):索引等补出处那一步再建。
        if "owner_user_id" in columns:
            _index_generation_sessions_by_origin(conn)


def _index_generation_sessions_by_origin(conn: Any) -> None:
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_generation_sessions_origin "
        "ON generation_sessions (workspace_id, owner_user_id, origin_kind, origin_id)"
    ))


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _generation_origin_from_job_payload(kind: str, payload: dict[str, Any]) -> tuple[str, str] | None:
    """一个(祖先)任务说明了这次生成是在哪一处跑的:工作流(定时任务跑的工作流也是 —— 生成在那张工作流里)、画板上跑的能力、
    资产详情页、定时任务。和现在的漏斗同一个判据(workflows 执行器按作用域、定时任务按任务)。"""
    if payload.get("workflow_id"):
        return "workflow", str(payload["workflow_id"])
    if kind == "board_run" and payload.get("board_id"):
        return "board", str(payload["board_id"])
    if kind == "entity_draw" and payload.get("entity_id"):
        return "entity", str(payload["entity_id"])
    if payload.get("scheduled_task_id"):
        return "schedule", str(payload["scheduled_task_id"])
    return None


def _generation_origin_from_receipt(payload: dict[str, Any]) -> tuple[str, str] | None:
    """任务载荷上的回执:画板格子的生成(`board_item`)、智能体批准确认卡之后建的(`agent_session`)。"""
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    if receipt.get("kind") == "board_item" and receipt.get("board_id"):
        return "board", str(receipt["board_id"])
    if receipt.get("kind") == "agent_session" and receipt.get("session_id"):
        return "agent", str(receipt["session_id"])
    return None


def _migrate_generation_sessions_origin_from_facts() -> None:
    """老会话按**查得到的事实**归出处(ADR 0052 §4、D46),查不到的就是 `studio`;不合并老会话(一次一条的照旧各是一条)。

    一条会话的出处看它**第一条**生成记录(开出它的那一次):

    - 任务还在:祖先任务里最近的那个说了在哪跑的(工作流、画板上的能力、资产详情页、定时任务),否则看任务上的回执
      (画板格子、智能体的对话),否则是工作台跑的(记录上 `workbench`,出处是那台连接 + 那张工作流的路径),否则就是
      创作页开的 —— 任务在、什么都没说,那就是创作页;
    - 任务被「清空已结束」删了:工作台跑的照记录认;确认卡的结果里记着这条记录的,是那段对话;会话只有这一条、它的产出
      摆在某块画板的格子上的,是那块画板(引用表);别的是 `studio`。

    「以前的语音 / 播客」(ADR 0055 的迁移建的那两条)标成 `audio_page`、标题清空 —— 界面按读的人的语言写
    (`_migrate_speech_and_podcast_join_creation_sessions` 写死的是中文)。
    """
    needed = {"generation_sessions", "generation_jobs", "jobs"}
    tables = set(inspect(engine).get_table_names())
    if not needed <= tables:
        return
    with engine.begin() as conn:
        _index_generation_sessions_by_origin(conn)
        conn.execute(text(
            "UPDATE generation_sessions SET origin_kind = 'audio_page', origin_id = kind, title = '' "
            "WHERE origin_kind = 'studio' AND provider_profile_id IS NULL "
            "AND ((title = '以前的语音' AND kind = 'speech') OR (title = '以前的播客' AND kind = 'podcast'))"
        ))
        firsts = conn.execute(text(
            "SELECT s.id, g.id, g.job_id, g.request, g.provider_profile_id, g.model, g.result_asset_id, "
            "(SELECT COUNT(*) FROM generation_jobs c WHERE c.session_id = s.id) "
            "FROM generation_sessions s JOIN generation_jobs g ON g.session_id = s.id "
            "WHERE s.origin_kind = 'studio' AND g.id = ("
            "SELECT f.id FROM generation_jobs f WHERE f.session_id = s.id ORDER BY f.created_at, f.id LIMIT 1)"
        )).all()
        instances = (
            dict(conn.execute(text("SELECT id, plugin_instance_id FROM provider_profiles")).all())
            if "provider_profiles" in tables else {}
        )

        def job(job_id: str | None) -> tuple[str, dict[str, Any], str | None] | None:
            row = conn.execute(
                text("SELECT kind, payload, parent_job_id FROM jobs WHERE id = :id"), {"id": job_id}
            ).first() if job_id else None
            return (str(row[0]), _json_object(row[1]), row[2]) if row is not None else None

        for session_id, record_id, job_id, raw_request, profile_id, model, asset_id, records in firsts:
            request = _json_object(raw_request)
            workbench = (
                ("comfyui", f"{instances[profile_id]}/{model}")
                if request.get("workbench") and instances.get(profile_id) and model else None
            )
            origin: tuple[str, str] | None = None
            own = job(job_id)
            if own is not None:
                parent, seen = own[2], set()
                while parent and parent not in seen and origin is None:
                    seen.add(parent)
                    found = job(parent)
                    if found is None:
                        break
                    origin = _generation_origin_from_job_payload(found[0], found[1])
                    parent = found[2]
                origin = origin or _generation_origin_from_receipt(own[1]) or workbench
            else:
                origin = workbench
                if origin is None and "tool_confirmations" in tables:
                    agent = conn.execute(text(
                        "SELECT session_id FROM tool_confirmations WHERE session_id IS NOT NULL "
                        "AND json_extract(result, '$.generation_id') = :id LIMIT 1"
                    ), {"id": record_id}).scalar()
                    origin = ("agent", str(agent)) if agent else None
                if origin is None and records == 1 and asset_id and "record_references" in tables:
                    board = conn.execute(text(
                        "SELECT source_id FROM record_references WHERE source_kind = 'board' AND target_kind = 'asset' "
                        "AND target_id = :asset ORDER BY source_id LIMIT 1"
                    ), {"asset": asset_id}).scalar()
                    origin = ("board", str(board)) if board else None
            if origin is not None:
                conn.execute(
                    text("UPDATE generation_sessions SET origin_kind = :kind, origin_id = :id WHERE id = :session"),
                    {"kind": origin[0], "id": origin[1], "session": session_id},
                )


def _migrate_earlier_speech_and_podcast_find_their_origin() -> None:
    """「以前的语音 / 播客」里查得到出处的那几条归到各自的出处(ADR 0052;ADR 0055 的迁移当时一并收进来的画板「念出来」、
    智能体念的):任务载荷上有画板格子 / 对话的回执的,挪进那个人在那一处的会话 —— 有就进最近用过的那条(和生成漏斗
    `_resolve_session` 同一个找法),没有就开一条(标题空着,界面写出处的名字)。查不到的(笔记朗读没记是哪篇)留在原地。
    挪完空了的「以前的…」删掉。挪动过的会话按里面的记录重算种类(最后一条的)和更新时间。

    排在 `_migrate_generation_sessions_origin_from_facts` 之后:它先把那两条标成 `audio_page`、把老会话的出处补齐。
    """
    needed = {"generation_sessions", "generation_jobs", "jobs"}
    if not needed <= set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT g.id, s.id, s.workspace_id, s.owner_user_id, j.payload "
            "FROM generation_jobs g JOIN generation_sessions s ON s.id = g.session_id JOIN jobs j ON j.id = g.job_id "
            "WHERE s.origin_kind = 'audio_page' ORDER BY g.created_at, g.id"
        )).all()
        touched: set[str] = set()
        targets: dict[tuple[str, str | None, str, str], str] = {}
        for record_id, earlier_id, workspace_id, owner, raw_payload in rows:
            origin = _generation_origin_from_receipt(_json_object(raw_payload))
            if origin is None:
                continue
            key = (workspace_id, owner, origin[0], origin[1])
            target = targets.get(key)
            if target is None:
                target = conn.execute(text(
                    "SELECT id FROM generation_sessions WHERE workspace_id = :ws AND owner_user_id IS :owner "
                    "AND origin_kind = :kind AND origin_id = :origin ORDER BY updated_at DESC, id DESC LIMIT 1"
                ), {"ws": workspace_id, "owner": owner, "kind": origin[0], "origin": origin[1]}).scalar()
            if target is None:
                target = uuid.uuid4().hex
                stamp = now()
                conn.execute(text(
                    "INSERT INTO generation_sessions (id, workspace_id, owner_user_id, title, group_id, provider_profile_id, "
                    "model, kind, origin_kind, origin_id, created_at, updated_at) "
                    "VALUES (:id, :ws, :owner, '', NULL, NULL, '', 'speech', :kind, :origin, :stamp, :stamp)"
                ), {"id": target, "ws": workspace_id, "owner": owner, "kind": origin[0], "origin": origin[1], "stamp": stamp})
            targets[key] = target
            conn.execute(text("UPDATE generation_jobs SET session_id = :to WHERE id = :id"), {"to": target, "id": record_id})
            #: 任务中心「前往」打开的是记录所在的那条会话(job_catalog 的 record_field 读载荷里的 session_id)
            payload = _json_object(raw_payload)
            if payload.get("session_id"):
                conn.execute(
                    text("UPDATE jobs SET payload = :payload WHERE id = (SELECT job_id FROM generation_jobs WHERE id = :id)"),
                    {"payload": json.dumps({**payload, "session_id": target}, ensure_ascii=False), "id": record_id},
                )
            touched.update({earlier_id, target})
        for session_id in touched:
            latest = conn.execute(text(
                "SELECT kind, provider, created_at FROM generation_jobs WHERE session_id = :id "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ), {"id": session_id}).first()
            if latest is None:
                conn.execute(text("DELETE FROM generation_sessions WHERE id = :id"), {"id": session_id})
                continue
            first = conn.execute(text(
                "SELECT MIN(created_at) FROM generation_jobs WHERE session_id = :id"
            ), {"id": session_id}).scalar()
            conn.execute(text(
                "UPDATE generation_sessions SET kind = :kind, updated_at = MAX(updated_at, :latest), "
                "created_at = MIN(created_at, :first) WHERE id = :id"
            ), {"kind": latest[0], "latest": latest[2], "first": first, "id": session_id})


def migration_plan() -> MigrationPlan:
    """Declare startup migration order in one validated plan.

    The function bodies remain historical snapshots next to the data shapes they understand.  This
    plan is the one place that decides *when* they run.  In particular, table renames and column
    additions that must see the old schema cannot accidentally drift past ``create-current-schema``.
    """

    return MigrationPlan(
        (
            *_steps(
                MigrationPhase.BEFORE_SCHEMA,
                # **它必须排在所有读 `users.is_deployment_admin` 的迁移之前。** 三条迁移
                # (connections-get-an-owner、plugin-instances-get-an-owner、provider-credentials)
                # 用「谁是部署管理员」回填归属,而加这一列的正是这一步 —— 它此前排在它们后面。
                # 在一个老到还没有这一列的库上,后端**启动就炸**在 `no such column:
                # is_deployment_admin`;这一路此前没有任何测试跑过(见
                # test_schema_migrations_cover_the_models)。它只碰 users,没有前置。
                _migrate_deployment_admin,
                _migrate_provider_capabilities,
                _migrate_provider_defaults_per_person,
                # It scans ENCRYPTED_COLUMNS; migrations above must first expose those columns.
                _migrate_encrypt_secrets,
                _migrate_deployment_config,
                _migrate_drop_deployment_defaults,
                _migrate_connections_get_an_owner,
                _migrate_plugin_instances_get_an_owner,
                _migrate_capability_defaults_name_builtins,
                _migrate_drop_the_knowledge_base,
                _migrate_hash_session_tokens,
                _migrate_client_version,
                _migrate_client_surface,
                _drop_publish_account_profile_name,
                _drop_clip_linked_clip_id,
                _migrate_browser_action_leases,
                _drop_reviews_table,
                _migrate_job_actor,
                _migrate_provider_credentials,
                _drop_shared_credentials,
                _migrate_tool_confirmations_session,
                _migrate_auth_session_expiry,
                _migrate_permission_modes,
                _drop_member_perm_overrides,
                _migrate_tts_pip_index,
                _migrate_agent_thinking_level,
                _migrate_agent_session_plan,
                _migrate_agent_session_groups,
                _migrate_session_groups_serve_both,
                # 它 ALTER 表并搬文件。**必须在 SCHEMA 之前** —— create_all 不会给已有的表补列,
                # 而 SCHEMA 之后 ORM 上的 Scene3DModel 已经指望 file_key 存在了。
                _migrate_scene_models_to_disk,
                # 紧跟着上一步:它搬的是上一步刚落到磁盘上的那些文件,而且同样要在 SCHEMA
                # 之前 —— create_all 不会把已有表的 scene_id 换成 workspace_id。
                _migrate_scene_models_to_workspace,
                _migrate_scene_cameras_become_objects,
                _migrate_source_assets_get_a_role,
                _migrate_workflow_source_assets,
                _migrate_plugin_registry_url,
                _migrate_generation_job_message_keys,
                _migrate_agent_session_order,
                _migrate_agent_notice_envelope_out_of_content,
                _drop_generation_models,
                _adopt_deepseek_vendor,
                _merge_split_vendors,
                _merge_openai_tts_engine,
                _migrate_job_parent,
                _migrate_job_worker_leases,
                _migrate_browser_pool,
                _migrate_clip_offline_asset,
                # 加列必须在 SCHEMA 之前:之后 ORM 上的 Clip 已经指望 link_group 存在了。
                _migrate_clips_get_a_link_group,
                # 加列必须在 SCHEMA 之前:之后 ORM 上的 Track 已经指望 hidden 存在了。
                _migrate_subtitle_tracks_hide_instead_of_mute,
                _migrate_model_structured_output,
                _migrate_browser_profile_start_url,
                _migrate_usage_unpriced_reason,
                _migrate_pricing_time_prices,
                _migrate_pricing_rules_by_resolution,
                _migrate_shared_host_folders,
                _migrate_outbound_allowlist,
                # Must precede schema creation or an empty plugin_packages table hides legacy data.
                _migrate_plugin_instances,
                # 排在上一步之后:它可能刚把 plugin_instances 建出来。
                _migrate_plugin_generation_columns,
                _migrate_plugin_authorization_rejected,
                _migrate_provider_credentials_remember_rejected_refresh,
                _migrate_plugin_connections_choose_their_network,
                _migrate_plugin_connections_choose_package_sources,
                _migrate_drop_the_community_integration,
                _migrate_voices_declare_consent,
                _migrate_boards_remember_their_project,
                _migrate_asset_extractions_remember_page_images,
                # 加列必须在 SCHEMA 之前:之后 ORM 上的 GenerationJob 已经指望失败原因那三列在了。
                _migrate_generation_jobs_keep_their_failure,
                # 同上:ORM 上的 Asset 指望出处和「含 AI」两列在。
                _migrate_assets_remember_where_they_came_from,
                # 同上:ORM 上的 Asset 指望「是不是中间产物」这一列在。
                _migrate_assets_know_if_they_are_intermediate,
                # 同上:ORM 上的 Asset 指望按名称排序的键这一列在。排在上一步之后:索引里有 intermediate。
                _migrate_assets_get_a_name_sort_key,
                # 加列必须在 SCHEMA 之前:之后 ORM 上的 ToolConfirmation 已经指望 tool_call_id 在了。
                _migrate_tool_confirmations_name_their_tool_call,
                # 同上:ORM 上的 NoteRevision 指望来历、作者、恢复自哪一版这三列在。
                _migrate_note_revisions_remember_where_they_came_from,
                # 同上:ORM 上的 Note 指望保存序号这一列在。
                _migrate_notes_count_their_saves,
                # 同上:ORM 上的 NoteRevision 指望 started_at 和字数那几列在、group_start 不在。
                _migrate_note_revisions_take_the_merged_shape,
                # 同上:ORM 上的 LocalService 指望 python_minor 在(让 Mosael 装,ADR 0041)。
                _migrate_local_services_remember_their_python,
                # 同上:ORM 上的 TtsConfig 指望「PyTorch 源」「GitHub 镜像前缀」两列在。
                _migrate_install_sources_get_pytorch_and_github,
                # 同上:ORM 上的 LocalService 指望「共用的模型文件夹」那一列在。
                _migrate_local_services_share_model_folders,
                # 同上:「闲置多久自动停」那一列。
                _migrate_local_services_stop_when_idle,
                # 同上:ORM 上的 AgentSkill 指望「智能体在哪次对话里建的」那一列在(ADR 0043)。
                _migrate_agent_skills_remember_the_drafting_session,
                # 同上:ORM 上的 AgentSession 指望「家」两列和 pending_view_at 在(ADR 0044)。读 project_id 和 origin='workflow'
                # 那批转成家,所以排在 SCHEMA 之后删 project_id 的那一步之前。
                _migrate_agent_sessions_remember_where_they_were_opened,
                # 同上:ORM 上的 AgentSession 指望「名字是谁起的」那一列在。
                _migrate_agent_sessions_know_who_named_them,
                # 同上:ORM 上的 ProviderModel 指望「是哪样东西的哪个入口」那一列在(ADR 0045)。
                _migrate_provider_models_remember_their_group,
                # 同上:ORM 上的 PluginInstance 指望「做过哪几批改名」那一列在(ADR 0045)。
                _migrate_plugin_instances_remember_applied_moves,
                # 同上:ORM 上的 ScheduledTask 指望「触发密钥的哈希」两列在;明文从 payload 里摘掉、换成哈希。
                _migrate_webhook_secrets_are_hashed,
                # 同上:ORM 上的 DeploymentConfig 指望「网页地址」那一列在(ADR 0054)。
                _migrate_deployments_know_their_web_address,
                # 同上:ORM 上的 GenerationSession 指望「出处」两列在(ADR 0052)。
                _migrate_generation_sessions_get_an_origin,
                # 同上:ORM 上的 ProviderUsageEvent 指望「替谁花的钱」那一列在(ADR 0050)。
                _migrate_usage_remembers_who_spent,
                # 同上:ORM 上的 DeploymentConfig 指望「任务保留多久」那一列在(ADR 0050)。
                _migrate_deployments_keep_finished_jobs_for_a_year,
            ),
            #: create_all 每次启动都要跑 —— 新版本加的表靠它建出来,记账跳过就再也建不了。
            *_recurring(MigrationPhase.SCHEMA, _create_current_schema),
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_drop_local_publish_accounts,
                _migrate_board_revision,
                _migrate_comment_canvas_context,
                _migrate_agent_pending_view,
                _migrate_publish_task_claimed_by,
                _migrate_publish_task_post,
                _migrate_confirmation_summary_i18n,
                _migrate_board_canvas_state,
                _migrate_board_trim_slots_record_their_source,
                _migrate_board_sources_record_their_upstream,
                _migrate_board_frame_names_become_titles,
                _migrate_board_forms_name_their_producer,
                _migrate_board_wiring_tools_become_notes,
                _migrate_board_scene_render_shot_is_picked,
                # 排在上一步之后:它把镜头绑定搬进了表单,这一步再把表单搬到场景格上。
                _migrate_board_scene_cells_render_themselves,
                _backfill_browser_pool,
                _backfill_provider_models,
                _migrate_provider_default_model_fk,
                # The legacy columns are inputs to the two provider backfills above.
                _drop_legacy_profile_columns,
                _backfill_plugin_instances,
                _migrate_resource_ownership,
                _migrate_publish_task_options,
                _migrate_job_message_i18n,
                _migrate_prepared_publish_tasks,
                _migrate_track_role,
                _migrate_subtitle_tracks_carry_no_sound,
                # 片段级编辑的撤销记录改成改动日志;同一轨上叠着的片段按「后开始的盖住先开始的」规整。
                _migrate_clip_edits_keep_a_change_journal,
                _migrate_clips_on_a_track_do_not_overlap,
                # 读改动日志认出分离音频,排在上面那条之后。
                _migrate_detached_audio_joins_its_video,
                _migrate_provider_model_capability_ref,
                _migrate_generation_capability_profiles,
                _migrate_prompt_requirement_becomes_one_field,
                _migrate_browser_boolean_options,
                _migrate_official_workflow_data_bindings,
                # 必须在 _migrate_workflow_revisions 之前:补完输出节点,下面那一步才会把
                # 这次语义改动记成一条新的不可变修订。
                _migrate_node_names_are_not_i18n_keys,
                _migrate_called_workflows_declare_their_output,
                _migrate_line_fields_are_lists,
                _migrate_condition_literals_are_json,
                _migrate_condition_edges_use_source_handle,
                _migrate_audio_engines_are_providers,
                _migrate_transcription_engines_are_providers,
                _migrate_translation_engines_are_providers,
                _migrate_speech_engines_are_providers,
                _migrate_cloned_speech_remembers_its_voice,
                _migrate_workflow_revisions,
                _disable_tasks_bound_to_deleted_workflows,
                # 排在所有会落修订的迁移之后:它们写下的那几版也要有作者。
                _backfill_workflow_revision_authors,
                # Projection comes last so rows synthesized by earlier migrations are visible
                # immediately, rather than waiting for the next application startup.
                _backfill_activity_events,
            ),
            #: 这两条是**对账**不是迁移:孤儿共享会随以后的删除再产生,job 的消息键要跟着文案表变。
            *_recurring(
                MigrationPhase.AFTER_SCHEMA,
                _cleanup_orphan_resource_shares,
                _migrate_job_keys_are_keys,
                # 在装随包插件之前:它要把每个包的清单解析一遍。
                _upgrade_stored_plugin_manifests,
                # 随应用发的插件每个版本都可能变(见 domain/plugins/bundled)。排在所有一次性迁移
                # 之后、而且在要用到它的包记录的那些迁移之前。
                _install_bundled_plugins,
            ),
            #: 要用到上一步刚装好的 ComfyUI 插件包(ADR 0020)。
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_comfyui_connections_become_plugin_instances,
                # 插件 1.17.0 撤掉了「API 模板」:存着的连接配置里摘掉这一格。排在上一步之后 —— 它可能刚把老连接的模板
                # 搬进这一格。
                _migrate_comfyui_connections_drop_the_api_template,
                # MiniMax 音乐撤掉(ADR 0022 补充):清掉存着的指向。
                _remove_minimax_music_models,
                # Blender 连接的 `::1` 从来连不上(上游两头都是 IPv4 套接字),改成 127.0.0.1。
                _migrate_blender_host_is_ipv4,
                # 清单形状收紧之后,库里违反新规矩的包记录删掉(否则读它就抛,插件页对所有人报错)。
                _drop_plugin_packages_that_break_the_manifest_rules,
                # 四个对象存储插件合成随应用内置的「对象存储」:要用到上面刚装好的那个包。
                _merge_object_storage_plugins,
                # ComfyUI 插件删掉了通用的 run_workflow:清掉只挂着这个工具名的开关和会话放行;
                # 存着的节点由下面的对账按插件报出的清单改。
                _forget_comfyui_run_workflow_tool,
                # 生成能力要有正面证据:没写能力的模型行按新规则落成显式标签。排在 ComfyUI 那几步之后 ——
                # 插件连接的模型行由它们建好、自带能力,这里一概不碰。
                _migrate_generation_capabilities_need_evidence,
                # 3D 场景页建的画板绕开了新建格子的缺省,空槽没写产出者:按 normalize 那条规则补一遍。
                _migrate_board_empty_slots_name_their_producer,
            ),
            #: 对账:插件报出的新工具取代了老工具时,存着的老节点改写过去(依据是缓存的工具清单,它会变)。
            *_recurring(MigrationPhase.AFTER_SCHEMA, _rewrite_replaced_plugin_tools),
            #: 画板上的工具格搬到它接着的内容格上(能力)、改成空格子(生成器)或便签。判法读工具的声明 ——
            #: 要用到上面装好的随包插件的清单;排在对账之后,对账不再认识工具格。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_tool_cells_become_abilities),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_entity_voices_name_their_engine),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_entity_reference_roles_follow_kind),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_blender_models_are_named_after_their_scene),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_documents_can_be_written),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_scene_cells_hold_no_image),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_scene_render_drops_project),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_sequence_cells_name_their_producer),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_documents_keep_the_note_they_became),
            #: 失败格子上的原因:给人看的那一句和原文分开存(UC-06)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_failures_keep_their_original_error),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_agent_session_titles_drop_attachment_tokens),
            #: 后台任务的回执不再是用户消息:换成自己的角色,排着的那条改成「待送」。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_job_receipts_get_their_own_role),
            #: 具名浏览器会话的登录分区按工作区分开:写下搬家单,由 Electron 执行器在磁盘上搬(新表由 SCHEMA 建)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_named_browser_partitions_are_per_workspace),
            #: 具名 / 池档案会话的租约落进库里(局部唯一索引);建之前先收掉已经撞上的。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_browser_sessions_one_open_per_login),
            #: 搬家单的「搬没搬」改成每台电脑一张回执(回执表由 SCHEMA 建):全局落了终态的单回到 pending。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_partition_moves_are_settled_per_executor),
            #: 这几条都落新修订(commit_graph_revision),所以排在修订迁移之后。
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                # 改走 commit_graph_revision 之后它要现成的修订(老库的第一版由修订迁移补上),从上面挪到这里。
                _migrate_loop_scopes_are_not_outer_data_edges,
                # 1.8.1 里上面这条(和条件边那条)经修订迁移落的那一版没有作者:补上一版的作者和认可。
                _migrate_migration_revisions_keep_their_vouchers,
                _migrate_browser_nodes_fill_one_target_keeping_reference_fallbacks,
                # 1.8.1 那条「只填一样」(上面这条取代了它)删掉的「引用在前、兜底在后」的兜底,从它前一版修订里找回来。
                _migrate_browser_fallback_targets_come_back,
                _migrate_code_fields_read_references_from_input,
                # 1.8.1 那版代码字段迁移把自己声明了 input 的执行脚本也改成了读 input.k:改回原文、点名。
                _migrate_scripts_declaring_input_go_back,
                # 1.8.1 那版代码字段迁移在字符串里留下的 str() / String() 读法改回和插值同义的写法。
                _migrate_code_string_reads_keep_their_text,
                # 要读插件报的工具清单:排在装随包插件、改写被取代的工具之后(上面的对账)。
                _migrate_plugin_array_inputs_are_lists,
                _migrate_board_plugin_array_inputs_are_lists,
                _migrate_plugin_union_array_inputs_are_lists,
                _migrate_start_required_params_are_a_list,
                # 要读**升级前缓存的**工具清单(加节点那时插件报的名字):排在装随包插件、改写被取代的工具之后;
                # 清单要等启动之后才刷新,所以这里比对的还是旧名字。
                _migrate_plugin_node_names_follow_the_plugin,
            ),
            #: 对账:上面那条只改得了它那一刻认得出的;工具清单后来才报上来的,每次启动按当时的声明补改。
            *_recurring(MigrationPhase.AFTER_SCHEMA, _plugin_array_inputs_follow_their_declarations),
            #: 生成记录自己存失败原因、会话按种类分页、提示词里拆出画板补的素材对照。回填要读 jobs.error_key ——
            #: 它在很老的库上由上面的 migrate-job-message-i18n 补上,所以排在它后面。
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _backfill_generation_failures,
                _migrate_generation_sessions_know_their_kind,
                _migrate_generation_prompts_drop_the_source_legend,
                #: 排在素材对照那一步之后:对照后面跟着的文档已被它整段挪走,这一步只切还留在提示词里的。
                _migrate_generation_prompts_drop_the_reference_documents,
            ),
            #: 老素材补出处和「含 AI」:读生成记录、任务、时间线(jobs 的 payload / result 在很老的库上也是上面才齐)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _backfill_asset_lineage),
            #: 老素材里逐句配音的一句、对口型的一块标成中间产物:要读任务、时间线和出处(出处由上一步补齐)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _backfill_intermediate_assets),
            #: 「本会话始终允许」记成 (工具, 档位)。排在所有改写这份清单(工具改名、去掉退役工具)的迁移之后 ——
            #: 它们认的是旧的工具名列表。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_session_allow_remembers_the_tier),
            #: 撤销 / 重做按键取片段记录的每个字段:老记录先补齐。要读 clips.offline_asset;排在把老记录转成
            #: 改动日志的 clip-edits-keep-a-change-journal 之后,它转出来的片段记录也在这里补齐。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_sequence_operation_clip_records_are_complete),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_removed_track_records_are_complete),
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_added_track_records_list_what_moved),
            #: 老库补上这一版新增的内置参考价。要读模型行上的能力(插件连接的模型行由上面的 ComfyUI 那几步建好)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_existing_libraries_get_the_new_reference_prices),
            #: 补算老账:要用到上一步刚补上的参考价。
            *_steps(MigrationPhase.AFTER_SCHEMA, _backfill_usage_costs),
            #: 补算的第二步:按旧规则只算了估的提示词 token 的那批重算(要用到补上的参考图输入价)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _reprice_usage_billed_on_estimated_prompt_tokens),
            #: 老库补上 Evolink GPT Image 的参考价。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_existing_libraries_get_the_evolink_gpt_image_prices),
            #: 老版本的来历尽量补出来:要读任务、对话、运行事件,所以在 SCHEMA 之后。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_note_revisions_guess_where_they_came_from),
            #: 老库里的碎版本真正合并、版本号重排、引用改指:排在补来历之后(恢复出来的版本要单独成版)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_note_revisions_merge_consecutive_edits),
            #: 连接的出错原因按刷新时的语言存成了死文字:认得回文案 key 的改成 key + 参数,认不回的清掉(启动时后台刷新会重新生成)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_plugin_connection_errors_follow_the_reader),
            #: 语音合成的老账照现在的口径改:CosyVoice 记在厂商 alibaba 名下(对得上价目),Edge 记 0、可信度免费。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_speech_usage_follows_todays_booking),
            #: 生成任务结果里每份的参数挪出 `outputs`(那个键是「交回了什么」,画板和任务详情只认它)。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_generation_results_keep_output_parameters_apart),
            #: 失败参数里认得出的原因从一整句话改成「原因 + 怎么修」:旧的那一句挪进 `cause`。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_failure_hints_say_cause_and_steps),
            #: 画板失败的格子改存原样(原文 + key + 参数),给人看的在读的时候按读的人的语言出:老格子照原样挪进新形状。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_board_failures_follow_the_reader),
            #: 百炼说话照片之前的人像预检(wan2.2-s2v-detect)补上参考价:预检此前一笔都没进账。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_existing_libraries_get_the_s2v_detect_price),
            #: Google 连接能对话了:已有 Gemini 对话模型行的补上 Gemini 的参考价。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_existing_libraries_get_the_gemini_chat_prices),
            #: `agent_sessions.project_id` 由家代替(ADR 0044):带外键的列删不掉,重建这张表。要在 SCHEMA 之后 —— 新表照现在的
            #: ORM 建,那时 ORM 要的列都已经在老表上;要在上面 BEFORE_SCHEMA 那一步把 project_id 转成家之后。
            #: 重建之前先删老库里还留着的死列(`adapter_session_id`、没删掉的 `sort_order`),否则重建的守卫会拒绝动手。
            *_steps(MigrationPhase.AFTER_SCHEMA, _drop_dead_agent_session_columns, _drop_agent_sessions_project_id),
            #: 从没说过话的空对话删掉(打开智能体是草稿之后,它们没有任何东西指着)。排在上一步之后:死路由那批这时已是 ui。
            *_steps(MigrationPhase.AFTER_SCHEMA, _drop_empty_agent_sessions),
            #: 升级之前一轮结束时留下的、还挂在对话上等人的确认卡作废(此后由 host 在每一轮收尾时结掉,ADR 0007 修订)。
            #: 排在删空对话之后:被删的那些本来就没有卡。
            *_steps(MigrationPhase.AFTER_SCHEMA, _expire_orphaned_session_confirmations),
            #: 一次性改名的老账按 key 记,换成按 key 和旧名字记(PLG-2):数的是这个连接现在的模型行和工具名。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_applied_moves_remember_old_names),
            #: 删素材不再连带删掉发布记录(MED-3):外键改 SET NULL 只能重建表。要在 SCHEMA 之后 —— 新表照现在的 ORM 建,
            #: 那时 publish_tasks 上 ORM 要的其余列(options、claimed_by、post)都已由上面那几步补上。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_publish_records_outlive_their_asset),
            #: 创作页之前做的语音、播客并进创作会话(ADR 0055 §8)。要在 SCHEMA 之后:会话、记录的表照现在的 ORM 建好了。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_speech_and_podcast_join_creation_sessions),
            #: 被停下的任务有了自己的终态(ADR 0049):老库里记成 failed + jobErr_cancelled 的改过来,定时任务的运行记录跟着改。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_cancelled_jobs_get_their_own_status),
            #: 定时任务的主人为它此刻跑的那几版补一条认可(ADR 0047 D11):升级前它们就这样在跑,升级后要「有主人担保」
            #: 才花主人的连接。排在所有落新修订的迁移之后 —— 认可的是迁移完之后的当前版。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_scheduled_tasks_vouch_for_what_they_run),
            #: 注册邀请码并进邀请链接(ADR 0054 D50):新表由 SCHEMA 建好了;码换成哈希,老码照样用到过期,旧表删掉。
            #: 指着已经不在的人的邀请和通知一并清掉(维护者库里有 2026-07-22 留下的两行)。
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_registration_invites_become_invite_links,
                _drop_invitations_and_notifications_of_people_who_are_gone,
            ),
            #: 老会话按事实归出处,「以前的语音 / 播客」里查得到出处的挪过去(ADR 0052)。排在上一步之后:那两条由它建;
            #: 读引用表(画板格子上摆着哪些素材)—— 那是上一次启动对账建的,下面这次对账之前读,读到的照旧是它。
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_generation_sessions_origin_from_facts,
                _migrate_earlier_speech_and_podcast_find_their_origin,
            ),
            #: 老账补上是谁花的(ADR 0050):顺着任务、智能体消息、会话、生成会话找人,找不到的留空。
            *_steps(MigrationPhase.AFTER_SCHEMA, _migrate_usage_finds_who_spent_it),
            #: 对账:引用表按当前抽取规则建(见 db/references)。排在所有改写 JSON 的迁移之后 —— 那些是原生 SQL,
            #: 不经过 flush 时的维护;抽取规则的版本号变了才整张重建,平常是一次查询。
            *_recurring(MigrationPhase.AFTER_SCHEMA, _reindex_record_references),
            *_steps(
                MigrationPhase.FILESYSTEM,
                _migrate_shared_venvs,
                _migrate_thumbnails_keep_transparency,
                _migrate_mov_videos_become_mp4,
                _migrate_frame_rate_is_not_a_time_base,
                _migrate_documents_are_not_videos,
            ),
            #: 对账:随包解释器换次版本后,旧 venv 跑不起来了。放在搬共用 venv 之后,搬过来的也要过这一道。
            *_recurring(MigrationPhase.FILESYSTEM, _drop_venvs_built_on_another_python),
        )
    )
