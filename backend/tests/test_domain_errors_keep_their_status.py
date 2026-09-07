"""领域异常在边界上翻出来的状态码,必须还是原来那几个。

领域层不认识 HTTP(见 tests/test_domain_does_not_raise_http.py),但**用户看到的状态码不能
因此改变**。这两条约束是一起的:前者管代码结构,后者管对外行为 —— 只有前者的话,一次
"把 HTTPException 换成领域异常"的重构可以悄悄把 409 变成 422,而谁都不会发现。

所以这里不测异常类,测**经过真实路由之后的响应**:领域抛什么、边界翻成什么、客户端收到什么。
"""

from __future__ import annotations

from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "Scenes"}).json()["id"]


def test_场景不存在是_404_而不是_403() -> None:
    """404 是故意的:不是这个工作区的人,连"它存在"都不该告诉他。"""
    c = fresh_client()
    ws = _workspace(c)
    assert c.get("/api/scenes/nope", params={"workspace_id": ws}).status_code == 404


def test_过期的修订号是_409() -> None:
    c = fresh_client()
    ws = _workspace(c)
    scene = c.post("/api/scenes", json={"workspace_id": ws, "name": "demo"}).json()
    stale = c.patch(f"/api/scenes/{scene['id']}", json={
        "workspace_id": ws, "base_revision": scene["revision"] + 90,
        "name": "x", "content": scene["content"]})
    assert stale.status_code == 409, stale.text
    # 而且要说清是被别人改过了,不是"请求格式不对"。
    assert "elsewhere" in stale.json()["detail"]


def test_引用别处的模型是_422() -> None:
    c = fresh_client()
    ws = _workspace(c)
    scene = c.post("/api/scenes", json={"workspace_id": ws, "name": "demo"}).json()
    content = {**scene["content"],
               "objects": [{"id": "o1", "kind": "model", "name": "m", "model_id": "not-mine"}]}
    r = c.patch(f"/api/scenes/{scene['id']}", json={
        "workspace_id": ws, "base_revision": scene["revision"], "name": "demo", "content": content})
    assert r.status_code == 422, r.text


def test_建场景时就引用模型是_422() -> None:
    """模型要先有场景才能导入 —— 这是顺序问题,不是"找不到"。"""
    c = fresh_client()
    ws = _workspace(c)
    r = c.post("/api/scenes", json={"workspace_id": ws, "name": "x", "content": {
        **c.post("/api/scenes", json={"workspace_id": ws, "name": "seed"}).json()["content"],
        "objects": [{"id": "o1", "kind": "model", "name": "m", "model_id": "any"}]}})
    assert r.status_code == 422, r.text


def test_笔记的三档也没变() -> None:
    """同一条约束,笔记域这边一起钉住 —— 它是第一个改成领域异常的。"""
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "Notes"}).json()["id"]
    assert c.get("/api/notes/nope", params={"workspace_id": ws}).status_code == 404
    note = c.post("/api/notes", json={"workspace_id": ws, "markdown": "正文"}).json()
    body = {**note, "base_revision": note["revision"], "markdown": "改过"}
    assert c.patch(f"/api/notes/{note['id']}", json=body).status_code == 200
    assert c.patch(f"/api/notes/{note['id']}", json=body).status_code == 409   # 修订号已过期
    assert c.post("/api/notes", json={"workspace_id": ws, "tags": ["x" * 81]}).status_code == 422
