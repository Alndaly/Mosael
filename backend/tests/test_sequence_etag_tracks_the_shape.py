"""ETag 要跟着**载荷形状**一起变,不只跟着数据变。

用户撞到的:我给片段加了 `asset_kind` 字段,后端也确实返回了(单测能证明),而界面上那个按钮
整个消失 —— 因为浏览器手里还攥着**加字段之前**的响应体。

`/projects/{id}/sequences` 的 ETag 是 `W/"<序列id>-<revision>"`,注释写着「revision 变 iff body
变」。这句话对**数据**成立,对**代码**不成立:序列一个字没改,而序列化器多了一个字段 —— body
确实变了,ETag 却没变,于是服务端一路回 304,浏览器一路用旧的。

**用户看到的不是"新字段没生效",而是一个功能凭空消失**,而且刷新、重启后端都没用:重启只清进程内
那层缓存,清不掉浏览器里的。这类 bug 在发版之后才发作,在开发机上极难复现。

判据:ETag 要能代表"这次响应长什么样",而那由**数据 + 序列化器**共同决定。所以把响应模型的
schema 摘要也编进去 —— 它变一次,所有 ETag 失效一次,正好是需要的粒度。
"""

from __future__ import annotations

from tests.util import fresh_client


def _project_with_sequence(client) -> tuple[str, str]:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": workspace_id, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": workspace_id, "project_id": project["id"], "name": "S"}
    ).json()
    return project["id"], sequence["id"]


def test_an_unchanged_sequence_still_revalidates_to_304() -> None:
    """缓存本身要留着 —— 编辑器一直在轮询它,这是它最省的一层。"""
    client = fresh_client()
    project_id, _ = _project_with_sequence(client)

    first = client.get(f"/api/projects/{project_id}/sequences")
    etag = first.headers["etag"]

    again = client.get(f"/api/projects/{project_id}/sequences", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_the_etag_changes_when_the_payload_shape_changes(monkeypatch) -> None:
    """序列化器多一个字段 → ETag 必须变,否则浏览器永远拿不到那个字段。"""
    from app.api.routes import sequences as routes

    client = fresh_client()
    project_id, _ = _project_with_sequence(client)
    before = client.get(f"/api/projects/{project_id}/sequences").headers["etag"]

    # 模拟"代码变了":响应模型的形状摘要换一个值。
    monkeypatch.setattr(routes, "_PAYLOAD_SHAPE", "some-other-shape")
    after = client.get(f"/api/projects/{project_id}/sequences").headers["etag"]

    assert before != after, "形状变了 ETag 没变 —— 浏览器会一直用旧的响应体"


def test_the_shape_digest_comes_from_the_model_not_a_hand_bumped_constant() -> None:
    """摘要**自己跟着模型走**。手写一个常量意味着改了模型要记得改它,而忘记的代价是
    「功能在老客户端上凭空消失」—— 一个没人会想到去查缓存的症状。"""
    from app.api.routes import sequences as routes

    assert len(routes._PAYLOAD_SHAPE) >= 8
    assert routes._PAYLOAD_SHAPE == routes._payload_shape_digest()
