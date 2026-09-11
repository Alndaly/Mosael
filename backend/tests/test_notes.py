from tests.util import fresh_client, second_client, make_video_asset


def setup():
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "Notes"}).json()["id"]
    return c, ws


def test_notes_search_revision_conflict_trash_and_restore():
    c, ws = setup()
    n = c.post("/api/notes", json={"workspace_id": ws, "title": "采访", "markdown": "选题来自真实生活", "topics": ["研究"]}).json()
    assert n["revision"] == 1
    assert c.get("/api/notes", params={"workspace_id": ws, "q": "真实"}).json()[0]["id"] == n["id"]
    assert c.get("/api/notes", params={"workspace_id": ws, "q": "%"}).json() == []
    body = {**n, "base_revision": 1, "markdown": "更新后的正文"}
    saved = c.patch(f"/api/notes/{n['id']}", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert c.patch(f"/api/notes/{n['id']}", json=body).status_code == 409
    old = c.get(f"/api/notes/{n['id']}/revisions/1", params={"workspace_id": ws}).json()
    assert old["markdown"] == n["markdown"]
    restored = c.post(f"/api/notes/{n['id']}/restore", json={"workspace_id": ws, "base_revision": 2, "revision": 1}).json()
    assert restored["revision"] == 3 and restored["markdown"] == n["markdown"]
    c.patch(f"/api/notes/{n['id']}", json={**restored, "base_revision": 3, "trashed": True})
    assert c.get("/api/notes", params={"workspace_id": ws}).json() == []
    assert len(c.get("/api/notes", params={"workspace_id": ws, "trashed": True}).json()) == 1


def test_notes_sources_and_revisions_cannot_cross_workspace_or_user():
    c, ws = setup()
    other_ws = c.post("/api/workspaces", json={"name": "Private"}).json()["id"]
    asset = make_video_asset(c, other_ws)
    source = {"kind": "asset", "id": asset["id"], "start": 1, "end": 3}
    assert c.post("/api/notes", json={"workspace_id": ws, "sources": [source]}).status_code == 404
    assert c.post("/api/notes", json={"workspace_id": ws, "sources": [{"kind": "url", "url": "javascript:alert(1)"}]}).status_code == 422
    n = c.post("/api/notes", json={"workspace_id": ws, "title": "private"}).json()
    assert c.get(f"/api/notes/{n['id']}", params={"workspace_id": other_ws}).status_code == 404
    other = second_client()
    assert other.get(f"/api/notes/{n['id']}", params={"workspace_id": ws}).status_code in (403, 404)
    assert other.get(f"/api/notes/{n['id']}/revisions/1", params={"workspace_id": ws}).status_code in (403, 404)


def test_append_preserves_text_and_provenance_and_pins_note_revision():
    c, ws = setup()
    asset = make_video_asset(c, ws)
    n = c.post("/api/notes", json={"workspace_id": ws, "markdown": "研究问题"}).json()
    appended = c.post(f"/api/notes/{n['id']}/append", json={"workspace_id": ws,
        "markdown": "> 原话", "sources": [{"kind": "asset", "id": asset["id"], "start": 1, "end": 3, "quote": "原话"}]}).json()
    assert appended["markdown"] == "研究问题\n\n> 原话"
    assert appended["sources"][0]["start"] == 1
    linked = c.post("/api/notes", json={"workspace_id": ws, "sources": [{"kind": "note", "id": n["id"]}]}).json()
    assert linked["sources"][0]["revision"] == 2


def test_saved_provenance_survives_original_trash_and_restore():
    c, ws = setup()
    original = c.post("/api/notes", json={"workspace_id": ws, "markdown": "原始资料"}).json()
    linked = c.post("/api/notes", json={"workspace_id": ws, "sources": [{"kind": "note", "id": original["id"]}]}).json()
    c.patch(f"/api/notes/{original['id']}", json={**original, "base_revision": 1, "trashed": True})
    edited = c.patch(f"/api/notes/{linked['id']}", json={**linked, "base_revision": 1, "markdown": "继续写作"})
    assert edited.status_code == 200
    cleared = c.patch(f"/api/notes/{linked['id']}", json={**edited.json(), "base_revision": 2, "sources": []})
    assert cleared.status_code == 200
    restored = c.post(f"/api/notes/{linked['id']}/restore", json={"workspace_id": ws, "base_revision": 3, "revision": 1})
    assert restored.status_code == 200
    assert restored.json()["sources"] == linked["sources"]
    assert c.post("/api/notes", json={"workspace_id": ws, "sources": [{"kind": "note", "id": original["id"]}]}).status_code == 409


def test_permanent_delete_requires_trash_access_and_current_revision():
    c, ws = setup()
    n = c.post("/api/notes", json={"workspace_id": ws, "markdown": "正文"}).json()
    url = f"/api/notes/{n['id']}"
    assert c.delete(url, params={"workspace_id": ws, "base_revision": 1}).status_code == 409
    c.patch(url, json={**n, "base_revision": 1, "trashed": True})
    assert c.delete(url, params={"workspace_id": ws, "base_revision": 1}).status_code == 409
    other = second_client()
    assert other.delete(url, params={"workspace_id": ws, "base_revision": 2}).status_code in (403, 404)
    assert c.delete(url, params={"workspace_id": ws, "base_revision": 2}).status_code == 204
    assert c.get(url, params={"workspace_id": ws}).status_code == 404
    assert c.get(url + "/revisions/1", params={"workspace_id": ws}).status_code == 404
    from app.core.db import SessionLocal
    from app.db.models import NoteRevision
    with SessionLocal() as db:
        assert db.get(NoteRevision, (n["id"], 1)) is None


def test_追加不被过期的修订号挡住_也不覆盖并发编辑():
    """追加到末尾与文档别处的编辑可交换,不该判成冲突。

    现场:一边从逐字稿往笔记里追加句子,一边有人开着这篇文档在写。此前客户端要带
    `base_revision`,而它来自笔记列表那次查询——追一句就旧一次,于是第二句起全是 409。
    """
    c, ws = setup()
    n = c.post("/api/notes", json={"workspace_id": ws, "markdown": "开头"}).json()
    # 有人先编辑了一版,笔记来到 revision 2;下面追加时手里那份仍然是 revision 1。
    c.patch(f"/api/notes/{n['id']}", json={**n, "base_revision": 1, "markdown": "开头(改过)"})

    for line in ("第一句", "第二句", "第三句"):
        r = c.post(f"/api/notes/{n['id']}/append", json={"workspace_id": ws, "markdown": line})
        assert r.status_code == 200, r.text

    latest = c.get(f"/api/notes/{n['id']}", params={"workspace_id": ws}).json()
    # 编辑的那一版没被覆盖,三句都在,顺序不乱。
    assert latest["markdown"] == "开头(改过)\n\n第一句\n\n第二句\n\n第三句"
    assert latest["revision"] == 5


def test_追加不能复活回收站里的笔记():
    c, ws = setup()
    n = c.post("/api/notes", json={"workspace_id": ws, "markdown": "正文"}).json()
    c.patch(f"/api/notes/{n['id']}", json={**n, "base_revision": 1, "trashed": True})
    r = c.post(f"/api/notes/{n['id']}/append", json={"workspace_id": ws, "markdown": "追加"})
    assert r.status_code == 409


def test_追加仍然校验来源归属():
    """放宽的是修订号,不是鉴权——跨工作区的来源照旧拒绝。"""
    c, ws = setup()
    other = c.post("/api/workspaces", json={"name": "别人的"}).json()["id"]
    asset = make_video_asset(c, other)
    n = c.post("/api/notes", json={"workspace_id": ws, "markdown": "正文"}).json()
    r = c.post(f"/api/notes/{n['id']}/append", json={"workspace_id": ws, "markdown": "引用",
        "sources": [{"kind": "asset", "id": asset["id"], "start": 1, "end": 3}]})
    assert r.status_code == 404


def test_笔记和画板的详情路由不带_workspace_id_也能读():
    """引用胶囊的探活用的是 /api/notes/{id} 这个形状,不带查询参数。

    它此前是必填的,于是点笔记和画板的胶囊**永远** 422 —— 而 useReferencePreview 把任何
    失败都当成「它已经不在了」,界面于是对着一条明明还在的笔记说它没了。素材和工作流的
    详情路由本来就不需要(资源自带归属),这两条是少数派。

    带上 workspace_id 仍按它查:拿到别的工作区的 id 也不该读得出来。
    """
    c = fresh_client()
    mine = c.post('/api/workspaces', json={'name': '我的'}).json()['id']
    other = c.post('/api/workspaces', json={'name': '别人的'}).json()['id']
    note = c.post('/api/notes', json={'workspace_id': mine, 'title': '引用目标'}).json()
    board = c.post('/api/boards', json={'workspace_id': mine, 'name': '画板目标'}).json()

    assert c.get(f"/api/notes/{note['id']}").status_code == 200
    assert c.get(f"/api/boards/{board['id']}").status_code == 200
    # 带上就按它查 —— 换一个工作区的 id 读不出来。
    assert c.get(f"/api/notes/{note['id']}?workspace_id={mine}").status_code == 200
    assert c.get(f"/api/notes/{note['id']}?workspace_id={other}").status_code == 404
    assert c.get(f"/api/boards/{board['id']}?workspace_id={other}").status_code == 404
