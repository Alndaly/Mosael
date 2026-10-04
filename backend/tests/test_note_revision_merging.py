"""连续的手动编辑在**存储上**合成一版:窗口内的自动保存改写最新那一版,不再每次新开一行。

编辑器停笔 700ms 就自动保存一次。此前每次保存都落一行 note_revisions,版本记录里「版本 3 到 6」常在 7 秒内连着出现。
现在(见 domain/notes/history):

- 这次保存和最新那一版都是编辑器里的保存(origin = edit)、是同一个人、离那一版最后一次保存不到 5 分钟、
  那一版从开始写起不到 30 分钟 —— 改写那一版(版本号不动,内容、时间、改了多少跟着更新);
- 否则开新的一版。智能体改的、恢复的、追加的、新建的、画板和工作流写的永远单独成版,它后面的编辑也另起一版;
- 保存序号照样每次 +1,并发冲突照样拦得住。

每一版记下从什么时候开始写(started_at)、最后一次保存(created_at),以及相对上一版新加 / 删掉多少字、标题改没改。
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.core.db import SessionLocal, engine
from tests.util import fresh_client


def _setup():
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    note = c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "周一开会。"}).json()
    return c, ws, note


def _save(c, ws: str, note: dict, **change) -> dict:
    response = c.patch(f"/api/notes/{note['id']}", json={**note, **change, "workspace_id": ws, "base_save_seq": note["save_seq"]})
    assert response.status_code == 200, response.text
    return response.json()


def _versions(c, ws: str, note_id: str) -> list[dict]:
    response = c.get(f"/api/notes/{note_id}/revisions", params={"workspace_id": ws})
    assert response.status_code == 200, response.text
    return response.json()


def _content(c, ws: str, note_id: str, revision: int) -> str:
    return c.get(f"/api/notes/{note_id}/revisions/{revision}", params={"workspace_id": ws}).json()["markdown"]


def _shift(note_id: str, revision: int, column: str, minutes: int) -> None:
    """把某一版的某个时间往前拨。"""
    with engine.begin() as conn:
        conn.execute(sa.text(
            f"UPDATE note_revisions SET {column} = datetime({column}, :shift) WHERE note_id = :n AND revision = :r"
        ), {"shift": f"-{minutes} minutes", "n": note_id, "r": revision})


def test_同一个人接连保存_改写同一版_不再一次一行() -> None:
    c, ws, note = _setup()
    for text in ("周一和剪辑组开会。", "周一和剪辑组开会。\n\n周二写脚本。", "周一和剪辑组开会。\n\n周二写完脚本。"):
        note = _save(c, ws, note, markdown=text)
    assert (note["revision"], note["save_seq"]) == (2, 4), "版本号只走了一步,保存序号每次都走"

    versions = _versions(c, ws, note["id"])
    assert [(v["revision"], v["origin"]) for v in versions] == [(2, "edit"), (1, "create")]
    edit = versions[0]
    assert edit["started_at"] <= edit["created_at"]
    #: 相对第 1 版「周一开会。」—— 加了「和剪辑组」「周二写完脚本。」,没删字。
    assert (edit["chars_added"], edit["chars_removed"], edit["title_changed"]) == (11, 0, False)
    assert _content(c, ws, note["id"], 2) == "周一和剪辑组开会。\n\n周二写完脚本。"
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM note_revisions WHERE note_id = :n"), {"n": note["id"]}).scalar() == 2


def test_停笔超过五分钟_再动笔是新的一版() -> None:
    c, ws, note = _setup()
    note = _save(c, ws, note, markdown="周一开会了。")
    _shift(note["id"], 2, "created_at", 6)
    note = _save(c, ws, note, markdown="周一开会了。周二也开。")
    assert note["revision"] == 3
    assert [v["revision"] for v in _versions(c, ws, note["id"])] == [3, 2, 1]
    assert _content(c, ws, note["id"], 2) == "周一开会了。", "停笔之前那一版定住了"


def test_一版最长半小时_一直不停笔也会切开() -> None:
    c, ws, note = _setup()
    note = _save(c, ws, note, markdown="一")
    _shift(note["id"], 2, "started_at", 31)
    note = _save(c, ws, note, markdown="一二")
    assert note["revision"] == 3


def test_中间夹着智能体修改_恢复_追加都单独成版_后面的编辑另起一版() -> None:
    from tests.test_note_passage_edits import Chat

    chat = Chat()
    note = chat.note("周一开会。周二写脚本。")
    c, ws = chat.client, chat.workspace_id
    note = _save(c, ws, note, markdown="周一开会。周二写完脚本。")
    card = chat.edit(note["id"], [{"kind": "replace", "find": "周一开会。", "text": "周一和剪辑组开会。"}])["result"]
    assert chat.approve(card["confirmation_id"])["status"] == "executed"
    note = chat.read(note["id"])
    note = _save(c, ws, note, markdown=note["markdown"] + "周三拍素材。")
    note = _save(c, ws, note, markdown=note["markdown"] + "周四剪。")
    restored = c.post(f"/api/notes/{note['id']}/restore", json={"workspace_id": ws, "base_save_seq": note["save_seq"], "revision": 1}).json()
    note = _save(c, ws, restored, title="第一周")
    appended = c.post(f"/api/notes/{note['id']}/append", json={"workspace_id": ws, "markdown": "> 原话", "sources": []}).json()

    assert [(v["revision"], v["origin"]) for v in _versions(c, ws, note["id"])] == [
        (7, "append"), (6, "edit"), (5, "restore"), (4, "edit"), (3, "agent"), (2, "edit"), (1, "create"),
    ]
    assert appended["revision"] == 7
    assert _content(c, ws, note["id"], 4).endswith("周三拍素材。周四剪。"), "智能体那一版之后的两次保存合成第 4 版"


def test_换了一个人写_另起一版() -> None:
    from app.db.models import User
    from app.domain.note_types import NoteContent
    from app.domain.notes import save_note
    from tests.util import second_client

    c, ws, note = _setup()
    note = _save(c, ws, note, markdown="周一开会。周二写脚本。")
    second_client()
    with SessionLocal() as db:
        colleague = db.query(User).filter(User.username != "tester").first()
        assert colleague is not None
        saved = save_note(db, ws, note["id"], note["save_seq"], NoteContent(title="周报", markdown="周一开会。周二写完脚本。"),
                          actor=colleague.id, origin="edit")
        db.commit()
        assert saved.revision == 3
    assert [v["created_by"] == colleague.id for v in _versions(c, ws, note["id"])] == [True, False, False]


def _old_table(columns: str) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE note_revisions"))
        conn.execute(sa.text(
            "CREATE TABLE note_revisions (note_id VARCHAR(64) NOT NULL REFERENCES notes(id) ON DELETE CASCADE, "
            f"revision INTEGER NOT NULL, snapshot JSON NOT NULL, {columns}created_at DATETIME NOT NULL, "
            "PRIMARY KEY (note_id, revision))"
        ))


@pytest.mark.parametrize("columns", [
    #: 跑过 1.8.3 开发期那一步(界面上分组)的老库:有 group_start 和字数列。
    "origin VARCHAR(16) NOT NULL DEFAULT 'edit', created_by VARCHAR(64), restored_from INTEGER, "
    "group_start INTEGER NOT NULL DEFAULT 0, chars_added INTEGER NOT NULL DEFAULT 0, "
    "chars_removed INTEGER NOT NULL DEFAULT 0, title_changed BOOLEAN NOT NULL DEFAULT 0, ",
    #: 只补过来历的老库:两样都没有。
    "origin VARCHAR(16) NOT NULL DEFAULT 'edit', created_by VARCHAR(64), restored_from INTEGER, ",
])
def test_迁移把版本表收成合并后的样子_补上开始写的时间_去掉分组那一列_重跑不动(columns: str) -> None:
    import json

    from app.db import migrations

    c, ws, _ = _setup()
    _old_table(columns)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO notes (id, workspace_id, title, markdown, tags, topics, sources, favorite, trashed, revision, save_seq, "
            "created_at, updated_at) VALUES ('n', :ws, '周报', '', '[]', '[]', '[]', 0, 0, 1, 1, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
        ), {"ws": ws})
        conn.execute(sa.text(
            "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_at) VALUES ('n', 1, :s, 'create', '2026-10-03 12:39:50')"
        ), {"s": json.dumps({"title": "周报", "markdown": "周一"})})

    migrations._migrate_note_revisions_take_the_merged_shape()
    migrations._migrate_note_revisions_take_the_merged_shape()

    with engine.begin() as conn:
        found = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(note_revisions)"))}
        assert "group_start" not in found
        assert {"started_at", "chars_added", "chars_removed", "title_changed"} <= found
        assert conn.execute(sa.text("SELECT started_at, created_at FROM note_revisions")).one() == (
            "2026-10-03 12:39:50", "2026-10-03 12:39:50")
    fresh_client()
