"""老库里的碎版本在存储上真正合并(note-revisions-merge-consecutive-edits)。

写入时合并只管以后。老库里每次自动保存都落了一行,这一步按同一条判据把它们并起来:

- 和上一版一模一样的版本(只改了属性,或一口气写了又写回去)删掉,指向它的引用改指到上一版;
- 连续的手动编辑(同一个人、相邻都是编辑、停笔不到 5 分钟、一版从开始写起不到 30 分钟)合成一版:留下组里最后一版的
  内容和时间,开始时间取组里第一版的;组里其余的行删掉;
- 智能体改的、恢复的、追加的、新建的、画板和工作流写的单独成版;
- 版本号重排成从 1 起连着的(界面上不出现跳号),笔记的当前版本号跟着改;
- 库里所有指向老版本号的引用改指到新的号:笔记的来源和正文里的 `#/notes?note=…&revision=N` 链接(含各版快照里的)、
  画板文档格钉住的版本、改笔记确认卡的结果、任务产出、对话记录 —— 任何 JSON 里 note_id 旁边的 revision /
  note_revision、kind 为 note 的来源,以及任何文字里的笔记引用链接;
- 「相对上一版改了多少」按合并后的上一版重算;
- 重跑不改任何东西。
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from app.core.db import SessionLocal, engine
from tests.util import fresh_client


def _link(note_id: str, revision: int) -> str:
    return f"#/notes?note={note_id}&revision={revision}"


def _seed():
    from app.db.models import AgentMessage, AgentSession, Job, TaskEvent, ToolConfirmation, User

    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    n = c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "周一"}).json()["id"]
    m = c.post("/api/notes", json={"workspace_id": ws, "title": "汇总", "markdown": "见周报"}).json()["id"]
    board = c.post("/api/boards", json={"workspace_id": ws, "name": "企划"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter(User.username == "tester").one().id

    versions = [
        (1, "create", "周一", False, None, "2026-10-03 12:39:50"),
        (2, "edit", "周一开会", False, None, "2026-10-04 11:24:47"),
        (3, "edit", "周一开会。", False, None, "2026-10-04 11:24:48"),
        (4, "edit", "周一开会。周二", False, None, "2026-10-04 11:24:54"),
        (5, "edit", "周一开会。周二", True, None, "2026-10-04 11:25:04"),      # 只改了收藏
        (6, "agent", "周一和剪辑组开会。周二", False, None, "2026-10-04 11:26:04"),
        (7, "edit", "周一和剪辑组开会。周二。周三", False, None, "2026-10-04 13:26:04"),
        (8, "restore", "周一开会。", False, 3, "2026-10-04 13:27:04"),
    ]
    mentions = f"见周报 {_link(n, 8)}"
    cite = [{"kind": "note", "id": n, "label": "周报", "quote": "", "revision": 3}]
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM note_revisions WHERE note_id = :n"), {"n": n})
        for revision, origin, markdown, favorite, restored_from, at in versions:
            conn.execute(sa.text(
                "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_by, restored_from, chars_added, "
                "chars_removed, title_changed, started_at, created_at) VALUES (:n, :r, :s, :o, NULL, :rf, 0, 0, 0, :at, :at)"
            ), {"n": n, "r": revision, "o": origin, "rf": restored_from, "at": at, "s": json.dumps(
                {"title": "周报", "markdown": markdown, "sources": [], "favorite": favorite, "tags": []}, ensure_ascii=False)})
        conn.execute(sa.text("UPDATE notes SET revision = 8, save_seq = 8, markdown = '周一开会。' WHERE id = :n"), {"n": n})
        conn.execute(sa.text("UPDATE notes SET markdown = :md, sources = :src WHERE id = :m"),
                     {"m": m, "md": mentions, "src": json.dumps(cite)})
        conn.execute(sa.text("UPDATE note_revisions SET snapshot = :s WHERE note_id = :m"), {"m": m, "s": json.dumps(
            {"title": "汇总", "markdown": mentions, "sources": cite}, ensure_ascii=False)})
        conn.execute(sa.text("UPDATE boards SET canvas = :canvas WHERE id = :b"), {"b": board, "canvas": json.dumps({"items": [
            {"id": "doc", "kind": "document", "note_id": n, "note_revision": 4, "text": "周报"}], "edges": []})})
    with SessionLocal() as db:
        card = ToolConfirmation(workspace_id=ws, tool="edit_note", permission="edit", status="executed",
                                result={"note_id": n, "revision": 6})
        job = Job(workspace_id=ws, kind="board_write", status="done", created_by=me,
                  result={"outputs": [{"type": "note", "note_id": n, "revision": 7}], "other": {"note_id": n, "revision": 99}})
        session = AgentSession(workspace_id=ws, owner_user_id=me)
        db.add_all([card, job, session])
        db.flush()
        message = AgentMessage(session_id=session.id, role="assistant", content=f"见 {_link(n, 5)}",
                               payload={"quote": {"kind": "note", "note_id": n, "revision": 4}})
        event = TaskEvent(job_id=job.id, type="workflow.node.finished", payload={"outputs": {"sequence_id": "s", "revision": 3}})
        db.add_all([message, event])
        db.commit()
        ids = {"card": card.id, "job": job.id, "message": message.id, "event": event.id}
    return c, ws, n, m, board, ids


def _state(n: str, m: str, board: str, ids: dict) -> dict:
    with engine.begin() as conn:
        one = lambda sql, **params: conn.execute(sa.text(sql), params).scalar()
        return {
            "versions": [tuple(row) for row in conn.execute(sa.text(
                "SELECT revision, origin, restored_from, started_at, created_at, chars_added, chars_removed, title_changed, "
                "json_extract(snapshot, '$.markdown') FROM note_revisions WHERE note_id = :n ORDER BY revision"
            ), {"n": n})],
            "note": tuple(conn.execute(sa.text("SELECT revision, save_seq FROM notes WHERE id = :n"), {"n": n}).one()),
            "m_markdown": one("SELECT markdown FROM notes WHERE id = :m", m=m),
            "m_sources": json.loads(one("SELECT sources FROM notes WHERE id = :m", m=m)),
            "m_snapshot": json.loads(one("SELECT snapshot FROM note_revisions WHERE note_id = :m", m=m)),
            "canvas": json.loads(one("SELECT canvas FROM boards WHERE id = :b", b=board)),
            "card": json.loads(one("SELECT result FROM tool_confirmations WHERE id = :i", i=ids["card"])),
            "job": json.loads(one("SELECT result FROM jobs WHERE id = :i", i=ids["job"])),
            "message": one("SELECT content FROM agent_messages WHERE id = :i", i=ids["message"]),
            "payload": json.loads(one("SELECT payload FROM agent_messages WHERE id = :i", i=ids["message"])),
            "event": json.loads(one("SELECT payload FROM task_events WHERE id = :i", i=ids["event"])),
        }


def test_碎版本真正合并_只改属性的删掉_版本号重排_所有引用改指过去_重跑不动() -> None:
    from app.db import migrations

    c, ws, n, m, board, ids = _seed()
    migrations._migrate_note_revisions_merge_consecutive_edits()
    after = _state(n, m, board, ids)

    assert after["versions"] == [
        (1, "create", None, "2026-10-03 12:39:50", "2026-10-03 12:39:50", 2, 0, 0, "周一"),
        #: 第 2、3、4 版(七秒之内)合成一版;第 5 版只改了收藏,删掉。
        (2, "edit", None, "2026-10-04 11:24:47", "2026-10-04 11:24:54", 5, 0, 0, "周一开会。周二"),
        (3, "agent", None, "2026-10-04 11:26:04", "2026-10-04 11:26:04", 4, 0, 0, "周一和剪辑组开会。周二"),
        (4, "edit", None, "2026-10-04 13:26:04", "2026-10-04 13:26:04", 3, 0, 0, "周一和剪辑组开会。周二。周三"),
        #: 从老的第 3 版恢复 —— 它并进了新的第 2 版。
        (5, "restore", 2, "2026-10-04 13:27:04", "2026-10-04 13:27:04", 0, 9, 0, "周一开会。"),
    ]
    assert after["note"] == (5, 8), "当前版本号跟着重排,保存序号不动"
    assert after["m_sources"][0]["revision"] == 2
    assert after["m_markdown"] == f"见周报 {_link(n, 5)}"
    assert after["m_snapshot"]["sources"][0]["revision"] == 2 and after["m_snapshot"]["markdown"] == after["m_markdown"]
    assert after["canvas"]["items"][0]["note_revision"] == 2
    assert after["card"] == {"note_id": n, "revision": 3}
    assert after["job"]["outputs"][0]["revision"] == 4
    assert after["job"]["other"] == {"note_id": n, "revision": 99}, "指向不存在的版本的,原样不动"
    assert after["message"] == f"见 {_link(n, 2)}", "只改了属性的那一版,改指到内容和它一样的那一版"
    assert after["payload"]["quote"]["revision"] == 2
    assert after["event"] == {"outputs": {"sequence_id": "s", "revision": 3}}, "不是笔记的 revision 不碰"

    migrations._migrate_note_revisions_merge_consecutive_edits()
    assert _state(n, m, board, ids) == after

    opened = c.get(f"/api/notes/{n}/revisions/2", params={"workspace_id": ws})
    assert opened.status_code == 200 and opened.json()["markdown"] == "周一开会。周二"
    fresh_client()


def test_一口气写了又写回上一版的样子_这一组并进上一版_一次就收到不动点() -> None:
    """智能体改出第 2 版之后,用户打了几个字又删回去(第 3、4 版):这一组最后和第 2 版一模一样,不留。
    在用户库的副本上,没有这一条时第二次跑还会再删掉 4 版、改指 17 处引用 —— 一次没收到不动点。"""
    from app.db import migrations

    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    note = c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "一"}).json()["id"]
    other = c.post("/api/notes", json={"workspace_id": ws, "title": "汇总", "markdown": f"见 {_link(note, 4)}"}).json()["id"]
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM note_revisions WHERE note_id = :n"), {"n": note})
        for revision, origin, markdown, at in [(1, "create", "一", "09:00:00"), (2, "agent", "一二", "09:10:00"),
                                               (3, "edit", "一二三", "10:00:00"), (4, "edit", "一二", "10:00:02")]:
            conn.execute(sa.text(
                "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_by, restored_from, chars_added, "
                "chars_removed, title_changed, started_at, created_at) VALUES (:n, :r, :s, :o, NULL, NULL, 0, 0, 0, :at, :at)"
            ), {"n": note, "r": revision, "o": origin, "at": f"2026-10-04 {at}",
                "s": json.dumps({"title": "周报", "markdown": markdown, "sources": []}, ensure_ascii=False)})
        conn.execute(sa.text("UPDATE notes SET revision = 4 WHERE id = :n"), {"n": note})

    migrations._migrate_note_revisions_merge_consecutive_edits()
    with engine.begin() as conn:
        versions = [tuple(row) for row in conn.execute(sa.text(
            "SELECT revision, origin, json_extract(snapshot, '$.markdown') FROM note_revisions WHERE note_id = :n ORDER BY revision"
        ), {"n": note})]
        linked = conn.execute(sa.text("SELECT markdown FROM notes WHERE id = :m"), {"m": other}).scalar()
        current = conn.execute(sa.text("SELECT revision FROM notes WHERE id = :n"), {"n": note}).scalar()
    assert versions == [(1, "create", "一"), (2, "agent", "一二")]
    assert (linked, current) == (f"见 {_link(note, 2)}", 2)

    migrations._migrate_note_revisions_merge_consecutive_edits()
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM note_revisions WHERE note_id = :n"), {"n": note}).scalar() == 2
        assert conn.execute(sa.text("SELECT markdown FROM notes WHERE id = :m"), {"m": other}).scalar() == linked
    fresh_client()
