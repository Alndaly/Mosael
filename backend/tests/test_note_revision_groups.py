"""连续的手动编辑归成一版:版本记录里一组一项,带一句「改了多少」。

编辑器停笔 700ms 就自动保存一次,而每次保存都是一版(修订号同时是乐观并发的基准、来源 / 画板文档格 / 引用链接
钉住的那一版,所以**每次保存照旧落一行、一行都不删不改**)。于是版本记录里「版本 3 到 6」常在 7 秒内连着出现。

现在每一版落库时记下它归在哪一组(`group_start`:这一组第一版的号),判据:

- 这一版和上一版都是**编辑器里的保存**(origin = edit),而且是**同一个人**;
- 离上一版不到 EDIT_PAUSE(5 分钟)—— 停笔超过 5 分钟再动笔,是新的一版;
- 离这一组第一版不到 EDIT_SPAN(30 分钟)—— 一口气写一个小时,版本记录里也每半小时有一个能回去的点;
- 智能体改的、恢复的、追加的、新建的、画板和工作流写的,**永远单独成一版**,它后面的编辑也另起一组。

每一版还记下相对**这一组之前那一版**改了多少:新加 / 删掉的字数(不算空白)、标题改没改。版本记录一组一项,
用的是这一组最新那一版的这几个数,就是这一组一共改了多少。
"""

from __future__ import annotations

import json

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


def _versions(c, ws: str, note_id: str, **params) -> list[dict]:
    response = c.get(f"/api/notes/{note_id}/revisions", params={"workspace_id": ws, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _age(note_id: str, revision: int, minutes: int) -> None:
    """把某一版的落库时间往前拨。"""
    with engine.begin() as conn:
        conn.execute(sa.text(
            "UPDATE note_revisions SET created_at = datetime(created_at, :shift) WHERE note_id = :n AND revision = :r"
        ), {"shift": f"-{minutes} minutes", "n": note_id, "r": revision})


def test_同一个人接连保存_归成一版_展开看得到每一次() -> None:
    c, ws, note = _setup()
    for text in ("周一和剪辑组开会。", "周一和剪辑组开会。\n\n周二写脚本。", "周一和剪辑组开会。\n\n周二写完脚本。"):
        note = _save(c, ws, note, markdown=text)
    assert note["save_seq"] == 4

    versions = _versions(c, ws, note["id"])
    assert [(v["revision"], v["group_start"], v["saves"], v["origin"]) for v in versions] == [
        (4, 2, 3, "edit"), (1, 1, 1, "create"),
    ]
    edits = versions[0]
    assert edits["started_at"] <= edits["created_at"]
    #: 这一组一共改了多少:相对第 1 版「周一开会。」—— 加了「和剪辑组」「周二写完脚本。」,没删字。
    assert (edits["chars_added"], edits["chars_removed"], edits["title_changed"]) == (11, 0, False)

    inside = _versions(c, ws, note["id"], group=2)
    assert [(v["revision"], v["saves"]) for v in inside] == [(4, 1), (3, 1), (2, 1)]


def test_停笔超过五分钟_再动笔是新的一版() -> None:
    c, ws, note = _setup()
    note = _save(c, ws, note, markdown="周一开会了。")
    _age(note["id"], 2, minutes=6)
    note = _save(c, ws, note, markdown="周一开会了。周二也开。")
    assert [(v["revision"], v["group_start"]) for v in _versions(c, ws, note["id"])] == [(3, 3), (2, 2), (1, 1)]


def test_一版最长半小时_一直不停笔也会切开() -> None:
    c, ws, note = _setup()
    note = _save(c, ws, note, markdown="一")
    note = _save(c, ws, note, markdown="一二")
    _age(note["id"], 2, minutes=31)
    note = _save(c, ws, note, markdown="一二三")
    assert [(v["revision"], v["group_start"], v["saves"]) for v in _versions(c, ws, note["id"])] == [
        (4, 4, 1), (3, 2, 2), (1, 1, 1),
    ]


def test_恢复和追加单独成版_后面的编辑另起一组_标题改了记得住() -> None:
    c, ws, note = _setup()
    note = _save(c, ws, note, markdown="周一开会。周二写脚本。")
    restored = c.post(f"/api/notes/{note['id']}/restore", json={"workspace_id": ws, "base_save_seq": 2, "revision": 1}).json()
    note = _save(c, ws, restored, title="第一周周报")
    appended = c.post(f"/api/notes/{note['id']}/append", json={"workspace_id": ws, "markdown": "> 原话", "sources": []}).json()

    versions = _versions(c, ws, note["id"])
    assert [(v["revision"], v["origin"], v["group_start"]) for v in versions] == [
        (5, "append", 5), (4, "edit", 4), (3, "restore", 3), (2, "edit", 2), (1, "create", 1),
    ]
    assert appended["revision"] == 5
    retitled = versions[1]
    assert (retitled["chars_added"], retitled["chars_removed"], retitled["title_changed"]) == (0, 0, True)
    assert (versions[2]["chars_added"], versions[2]["chars_removed"]) == (0, 6), "恢复回第 1 版:删掉了「周二写脚本。」"


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
        save_note(db, ws, note["id"], note["save_seq"], NoteContent(title="周报", markdown="周一开会。周二写完脚本。"),
                  actor=colleague.id, origin="edit")
        db.commit()
    versions = _versions(c, ws, note["id"])
    assert [(v["revision"], v["group_start"], v["created_by"] == colleague.id) for v in versions] == [
        (3, 3, True), (2, 2, False), (1, 1, False),
    ]


def test_迁移给老版本分组并补上改了多少_重跑不动() -> None:
    from app.db import migrations

    c, ws, _ = _setup()
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE note_revisions"))
        conn.execute(sa.text(
            "CREATE TABLE note_revisions (note_id VARCHAR(64) NOT NULL REFERENCES notes(id) ON DELETE CASCADE, "
            "revision INTEGER NOT NULL, snapshot JSON NOT NULL, origin VARCHAR(16) NOT NULL DEFAULT 'edit', "
            "created_by VARCHAR(64), restored_from INTEGER, created_at DATETIME NOT NULL, PRIMARY KEY (note_id, revision))"
        ))
        conn.execute(sa.text(
            "INSERT INTO notes (id, workspace_id, title, markdown, tags, topics, sources, favorite, trashed, revision, created_at, updated_at) "
            "VALUES ('n', :ws, '周报', '', '[]', '[]', '[]', 0, 0, 6, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
        ), {"ws": ws})
        rows = [
            (1, "create", "周报", "周一", "2026-10-03 12:39:50"),
            (2, "edit", "周报", "周一开会", "2026-10-04 11:24:47"),
            (3, "edit", "周报", "周一开会。", "2026-10-04 13:02:14"),
            (4, "edit", "周报", "周一开会。周二", "2026-10-04 13:02:15"),
            (5, "edit", "第一周", "周一开会。周二写", "2026-10-04 13:02:21"),
            (6, "agent", "第一周", "周一开会。", "2026-10-04 13:03:38"),
        ]
        for revision, origin, title, markdown, at in rows:
            conn.execute(sa.text(
                "INSERT INTO note_revisions (note_id, revision, snapshot, origin, created_at) VALUES ('n', :r, :s, :o, :at)"
            ), {"r": revision, "o": origin, "at": at, "s": json.dumps({"title": title, "markdown": markdown})})

    migrations._migrate_note_revisions_fold_consecutive_edits()
    migrations._migrate_note_revisions_fold_consecutive_edits()

    with engine.begin() as conn:
        got = conn.execute(sa.text(
            "SELECT revision, group_start, chars_added, chars_removed, title_changed FROM note_revisions "
            "WHERE note_id = 'n' ORDER BY revision"
        )).all()
    assert [tuple(row) for row in got] == [
        (1, 1, 2, 0, 0),
        (2, 2, 2, 0, 0),   # 隔了将近一天:新的一版
        (3, 3, 1, 0, 0),   # 隔了一个半小时:新的一版
        (4, 3, 3, 0, 0),   # 一秒之后:并进第 3 版那一组,相对第 2 版加了「。周二」
        (5, 3, 4, 0, 1),   # 又过了六秒,标题也改了
        (6, 6, 0, 3, 0),   # 智能体改的单独成版
    ]
    fresh_client()
