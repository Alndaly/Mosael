"""笔记的乐观并发认「保存序号」(`save_seq`),不再认版本号。

此前 `Note.revision` 一身两职:既是乐观并发的基准(base_revision),又是版本记录里的版本号、来源 / 画板文档格 / 引用链接
钉住的那一版。于是「每次保存都得 +1」和「一组连续编辑只算一版」没法同时成立。现在拆开:

- `save_seq`:每次写入(哪怕只改了收藏)都 +1,保存 / 恢复 / 彻底删除都带 `base_save_seq` 做条件写;
- `revision`:只是版本号。

两个窗口拿着同一份去存,后存的那个照样被拦下来(409)。
"""

from __future__ import annotations

import sqlalchemy as sa

from tests.util import fresh_client


def _setup():
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    note = c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "周一"}).json()
    return c, ws, note


def test_两个窗口拿着同一份去存_后存的那个被拦下来() -> None:
    c, ws, note = _setup()
    assert note["save_seq"] == 1
    first = c.patch(f"/api/notes/{note['id']}", json={**note, "base_save_seq": note["save_seq"], "markdown": "周一开会"})
    assert first.status_code == 200, first.text
    assert first.json()["save_seq"] == 2

    second = c.patch(f"/api/notes/{note['id']}", json={**note, "base_save_seq": note["save_seq"], "markdown": "周一写脚本"})
    assert second.status_code == 409, "拿着旧的保存序号存,不能把另一个窗口刚存的冲掉"
    assert c.get(f"/api/notes/{note['id']}", params={"workspace_id": ws}).json()["markdown"] == "周一开会"

    again = c.patch(f"/api/notes/{note['id']}", json={**first.json(), "base_save_seq": 2, "markdown": "周一开会。"})
    assert again.status_code == 200 and again.json()["save_seq"] == 3


def test_恢复和彻底删除也认保存序号() -> None:
    c, ws, note = _setup()
    saved = c.patch(f"/api/notes/{note['id']}", json={**note, "base_save_seq": 1, "markdown": "周一开会"}).json()
    stale = c.post(f"/api/notes/{note['id']}/restore", json={"workspace_id": ws, "base_save_seq": 1, "revision": 1})
    assert stale.status_code == 409
    restored = c.post(f"/api/notes/{note['id']}/restore", json={"workspace_id": ws, "base_save_seq": saved["save_seq"], "revision": 1})
    assert restored.status_code == 200 and restored.json()["markdown"] == "周一"

    trashed = c.patch(f"/api/notes/{note['id']}", json={**restored.json(), "base_save_seq": restored.json()["save_seq"], "trashed": True}).json()
    url = f"/api/notes/{note['id']}"
    assert c.delete(url, params={"workspace_id": ws, "base_save_seq": trashed["save_seq"] - 1}).status_code == 409
    assert c.delete(url, params={"workspace_id": ws, "base_save_seq": trashed["save_seq"]}).status_code == 204


def test_迁移给老笔记补上保存序号_从当前版本号起_重跑不动() -> None:
    from app.core.db import engine
    from app.db import migrations

    c, ws, _ = _setup()
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE note_revisions"))
        conn.execute(sa.text("DROP TABLE notes"))
        conn.execute(sa.text(
            "CREATE TABLE notes (id VARCHAR(64) PRIMARY KEY, workspace_id VARCHAR(64) NOT NULL, project_id VARCHAR(64), "
            "title VARCHAR(240) NOT NULL, markdown TEXT NOT NULL, tags JSON NOT NULL, topics JSON NOT NULL, sources JSON NOT NULL, "
            "favorite BOOLEAN NOT NULL, trashed BOOLEAN NOT NULL, revision INTEGER NOT NULL, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        ))
        conn.execute(sa.text(
            "INSERT INTO notes VALUES ('n', :ws, NULL, '周报', '三', '[]', '[]', '[]', 0, 0, 7, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
        ), {"ws": ws})

    migrations._migrate_notes_count_their_saves()
    migrations._migrate_notes_count_their_saves()

    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT revision, save_seq FROM notes WHERE id = 'n'")).one() == (7, 7)
    fresh_client()
