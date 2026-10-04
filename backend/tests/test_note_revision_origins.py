"""笔记的每一版记下**怎么来的、谁写的**:版本记录里要看得出哪一版是手动编辑、哪一版是智能体改的、哪一版是从版本 N 恢复的。

此前 note_revisions 只有快照和时间,列表里一排「版本 7 / 版本 6 …」,看不出任何一版的来历。现在每个写笔记的入口
都得说出自己是谁(`origin` 没有缺省,漏说就是 TypeError):

- 编辑器的自动保存(PATCH)是 edit;页面上新建是 create;「存到笔记」追加是 append;
- 智能体:edit_note 确认卡批准后落的那一版、经工具通道的 create_note / append_note,都是 agent;
- 恢复是 restore,并记下从哪一版恢复(restored_from);
- 画板文档格写出来的是 board,工作流的知识节点建的是 workflow。

老库里的版本由迁移回填:第 1 版是新建;批准过的 edit_note 卡落下的那一版是智能体改的(卡的结果里记着笔记和修订号,
批的人记成作者);其余推不出来(恢复、追加当时没留痕),记成编辑。
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from tests.test_note_passage_edits import Chat
from tests.util import fresh_client


def _versions(client, workspace_id: str, note_id: str) -> list[dict]:
    response = client.get(f"/api/notes/{note_id}/revisions", params={"workspace_id": workspace_id})
    assert response.status_code == 200, response.text
    return response.json()


def _tool(chat: Chat, name: str, arguments: dict) -> dict:
    response = chat.client.post(
        f"/api/agent/tools/{name}", json={"arguments": arguments, "requested_by": "pi"},
        headers={"Authorization": f"Bearer {chat.token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_页面上的新建_编辑_追加_恢复各记各的来历_作者是做这件事的人() -> None:
    c = fresh_client()
    me = c.get("/api/auth/me").json()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    n = c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "周一"}).json()
    edited = c.patch(f"/api/notes/{n['id']}", json={**n, "base_revision": 1, "markdown": "周一开会"}).json()
    appended = c.post(f"/api/notes/{n['id']}/append", json={"workspace_id": ws, "markdown": "> 原话", "sources": []}).json()
    restored = c.post(
        f"/api/notes/{n['id']}/restore", json={"workspace_id": ws, "base_revision": appended["revision"], "revision": 1}
    ).json()
    assert restored["revision"] == 4

    versions = _versions(c, ws, n["id"])
    assert [(v["revision"], v["origin"], v["restored_from"]) for v in versions] == [
        (4, "restore", 1), (3, "append", None), (2, "edit", None), (1, "create", None),
    ]
    assert edited["revision"] == 2
    assert {v["created_by"] for v in versions} == {me["id"]}
    assert {v["created_by_name"] for v in versions} == {me["display_name"] or me["username"]}


def test_智能体落下的版本记成智能体() -> None:
    chat = Chat()
    created = _tool(chat, "create_note", {"workspace_id": chat.workspace_id, "title": "调研", "markdown": "第一段。"})
    note_id = created["result"]["id"]
    _tool(chat, "append_note", {"workspace_id": chat.workspace_id, "note_id": note_id, "base_revision": 1, "markdown": "第二段。"})
    card = _tool(chat, "edit_note", {"workspace_id": chat.workspace_id, "note_id": note_id,
                                     "operations": [{"kind": "replace", "find": "第一段。", "text": "开头。"}]})["result"]
    assert chat.approve(card["confirmation_id"])["status"] == "executed"

    versions = _versions(chat.client, chat.workspace_id, note_id)
    assert [(v["revision"], v["origin"]) for v in versions] == [(3, "agent"), (2, "agent"), (1, "agent")]


def test_写笔记的入口都得说出自己是谁() -> None:
    """`origin` 没有缺省:新加一个写笔记的地方而忘了说来历,在这里就炸,不会悄悄记成「编辑」。"""
    import inspect

    from app.domain import notes

    for writer in (notes.create_note, notes.save_note, notes.append_note):
        parameter = inspect.signature(writer).parameters["origin"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty, writer.__name__


def test_迁移给老版本补上来历_第一版是新建_批准过的改笔记卡是智能体_重跑不动() -> None:
    from app.core.db import engine
    from app.db import migrations

    c = fresh_client()
    me = c.get("/api/auth/me").json()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE note_revisions"))
        conn.execute(sa.text(
            "CREATE TABLE note_revisions (note_id VARCHAR(64) NOT NULL REFERENCES notes(id) ON DELETE CASCADE, "
            "revision INTEGER NOT NULL, snapshot JSON NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (note_id, revision))"
        ))
        conn.execute(sa.text(
            "INSERT INTO notes (id, workspace_id, title, markdown, tags, topics, sources, favorite, trashed, revision, created_at, updated_at) "
            "VALUES ('n', :ws, '周报', '三', '[]', '[]', '[]', 0, 0, 3, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
        ), {"ws": ws})
        for revision in (1, 2, 3):
            conn.execute(sa.text(
                "INSERT INTO note_revisions (note_id, revision, snapshot, created_at) VALUES ('n', :r, :s, '2026-10-01 00:00:00')"
            ), {"r": revision, "s": json.dumps({"title": "周报", "markdown": str(revision)})})
        conn.execute(sa.text(
            "INSERT INTO tool_confirmations (id, workspace_id, tool, permission, status, result, decided_by, payload, summary, "
            "summary_key, summary_params, requested_by, decision_mode, created_at) "
            "VALUES ('card', :ws, 'edit_note', 'edit', 'executed', :result, :me, '{}', '', '', '{}', 'pi', 'manual', "
            "'2026-10-01 00:00:00')"
        ), {"ws": ws, "me": me["id"], "result": json.dumps({"note_id": "n", "revision": 3})})

    migrations._migrate_note_revisions_remember_where_they_came_from()
    migrations._migrate_note_revisions_remember_where_they_came_from()

    with engine.begin() as conn:
        rows = conn.execute(sa.text(
            "SELECT revision, origin, created_by, restored_from FROM note_revisions WHERE note_id = 'n' ORDER BY revision"
        )).all()
    assert [tuple(row) for row in rows] == [(1, "create", None, None), (2, "edit", None, None), (3, "agent", me["id"], None)]
    fresh_client()
