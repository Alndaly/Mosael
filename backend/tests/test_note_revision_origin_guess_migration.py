"""老版本的来历尽量补出来(note-revisions-guess-where-they-came-from)。

补来历那一步(remember-where-they-came-from)只认得出第 1 版是新建、批准过的改笔记卡是智能体改的,其余一律记成
「手动编辑」。这一步再往下推,**只动说不出是谁写的老版本**(created_by 为空、记成新建 / 编辑的那些):

- 画板文档格写出来的:board_write 任务的产出里记着笔记和版本号 → 画板写入,作者是点「写」的人;
- 智能体经工具新建 / 追加的:对话记录里 create_note / append_note 的结果记着笔记和版本号 → 智能体修改,作者是对话的主人;
- 工作流的「存成笔记」节点建的:工作流运行事件里那个节点的产出记着笔记和第 1 版 → 工作流写入;
- 内容(标题、正文、来源)和更早的某一版一模一样、又和紧挨着的上一版不同 → 从那一版恢复;
- 在上一版末尾隔一个空行接了一段、来源也多了 → 存到笔记(追加);
- 推不出来的才留着「手动编辑」。和上一版内容一样的(只改了属性)不在这里管,由合并那一步清掉。
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from app.core.db import SessionLocal, engine
from tests.util import fresh_client


def _note(c, ws: str) -> str:
    return c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "周一"}).json()["id"]


def _old_versions(note_id: str, rows: list[tuple]) -> None:
    """把一篇笔记的版本换成「老库里那样」:作者为空,来历只有新建 / 编辑。"""
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM note_revisions WHERE note_id = :n"), {"n": note_id})
        for revision, origin, title, markdown, sources, created_by in rows:
            conn.execute(sa.text(
                "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_by, chars_added, chars_removed, "
                "title_changed, started_at, created_at) VALUES (:n, :r, :s, :o, :by, 0, 0, 0, :at, :at)"
            ), {"n": note_id, "r": revision, "o": origin, "by": created_by, "at": f"2026-10-0{revision} 10:00:00",
                "s": json.dumps({"title": title, "markdown": markdown, "sources": sources, "favorite": False})})


def _origins(note_id: str) -> list[tuple]:
    with engine.begin() as conn:
        return [tuple(row) for row in conn.execute(sa.text(
            "SELECT revision, origin, restored_from, created_by FROM note_revisions WHERE note_id = :n ORDER BY revision"
        ), {"n": note_id})]


def test_从任务_对话记录_工作流事件_内容里推出老版本的来历_推不出的才算手动编辑_重跑不动() -> None:
    from app.db import migrations
    from app.db.models import AgentMessage, AgentSession, Job, TaskEvent, User

    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter(User.username == "tester").one().id
    source = {"kind": "url", "id": "", "label": "原文", "quote": "", "url": "https://example.com"}

    by_content, by_board, by_agent, by_workflow = (_note(c, ws) for _ in range(4))
    _old_versions(by_content, [
        (1, "create", "周报", "周一", [], None),
        (2, "edit", "周报", "周一开会", [], None),
        (3, "edit", "周报", "周一", [], None),                                 # 和第 1 版一模一样 → 从第 1 版恢复
        (4, "edit", "周报", "周一", [], None),                                 # 和上一版一样(只改了属性)→ 不管
        (5, "edit", "周报", "周一\n\n> 原话", [source], None),                  # 末尾接了一段、多了来源 → 追加
        (6, "edit", "周报", "周一\n\n> 原话\n\n自己打的", [source], None),       # 没多来源 → 手动编辑
        (7, "edit", "周报", "周一开会", [], me),                               # 说得出是谁的不动
    ])
    _old_versions(by_board, [(1, "create", "周报", "周一", [], None), (2, "edit", "周报", "画板写的", [], None)])
    _old_versions(by_agent, [(1, "create", "调研", "第一段", [], None)])
    _old_versions(by_workflow, [(1, "create", "诊断", "报告", [], None)])

    with SessionLocal() as db:
        db.add(Job(workspace_id=ws, kind="board_write", status="done", created_by=me,
                   result={"outputs": [{"type": "note", "note_id": by_board, "revision": 2, "title": "周报"}]}))
        session = AgentSession(workspace_id=ws, owner_user_id=me)
        db.add(session)
        db.flush()
        created = {"id": by_agent, "revision": 1, "title": "调研"}
        db.add(AgentMessage(session_id=session.id, role="assistant", payload={"timeline": [{"type": "tool", "tool": {
            "name": "create_note", "status": "done", "result": {"content": [{"type": "text", "text": json.dumps(created)}]}}}]}))
        run = Job(workspace_id=ws, kind="workflow", status="done", created_by=me)
        db.add(run)
        db.flush()
        db.add(TaskEvent(job_id=run.id, type="workflow.node.finished", payload={"node_id": "save_note", "outputs": {
            "note_id": by_workflow, "title": "诊断", "revision": 1, "citation_url": f"#/notes?note={by_workflow}&revision=1"}}))
        db.commit()

    migrations._migrate_note_revisions_guess_where_they_came_from()
    migrations._migrate_note_revisions_guess_where_they_came_from()

    assert _origins(by_content) == [
        (1, "create", None, None), (2, "edit", None, None), (3, "restore", 1, None), (4, "edit", None, None),
        (5, "append", None, None), (6, "edit", None, None), (7, "edit", None, me),
    ]
    assert _origins(by_board) == [(1, "create", None, None), (2, "board", None, me)]
    assert _origins(by_agent) == [(1, "agent", None, me)]
    assert _origins(by_workflow) == [(1, "workflow", None, me)]


def test_同一口气里打了几个字又删回去_不算恢复() -> None:
    """自动保存几秒一次:打两个字、又删掉,第 3 版和第 1 版一模一样 —— 那是编辑,不是从第 1 版恢复。
    在用户库的副本上,不加这一条时 20 个「恢复」里 20 个都是这种。"""
    from app.db import migrations

    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    note = _note(c, ws)
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM note_revisions WHERE note_id = :n"), {"n": note})
        for revision, markdown, at in [(1, "周一", "10:00:00"), (2, "周一开", "10:00:02"), (3, "周一", "10:00:04"),
                                       (4, "周一开会", "10:20:00"), (5, "周一", "10:20:03")]:
            conn.execute(sa.text(
                "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_by, chars_added, chars_removed, "
                "title_changed, started_at, created_at) VALUES (:n, :r, :s, :o, NULL, 0, 0, 0, :at, :at)"
            ), {"n": note, "r": revision, "o": "create" if revision == 1 else "edit", "at": f"2026-10-04 {at}",
                "s": json.dumps({"title": "周报", "markdown": markdown, "sources": []})})

    migrations._migrate_note_revisions_guess_where_they_came_from()

    #: 第 5 版和第 3 版一样,而第 3 版在二十分钟前那一口气里 —— 中间停过笔,算从第 3 版恢复。
    assert [row[:3] for row in _origins(note)] == [
        (1, "create", None), (2, "edit", None), (3, "edit", None), (4, "edit", None), (5, "restore", 3),
    ]
