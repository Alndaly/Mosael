"""删掉一个还被引用的东西,同一层里只能有**一种**答案。

## 现场

此前有三种,而只有两种是想过的:

| 被删的 | 行为 | 在哪一层决定 |
| --- | --- | --- |
| 导入模型 | **拒绝**,并点名还有哪几个场景在用 | 领域(`domain/scenes.delete_model`) |
| 笔记 | 允许;画板上那条坏引用仍可移动、可删除(专门留了豁免) | 领域(`boards/canvas`) |
| 3D 场景 | 允许,**且没有任何人检查画板** | **路由**里一句裸的 `db.delete(scene)` |

第三条的后果可验证:画板保存时 `_validate_references` 要求每个 `scene_id` 都属于本
工作区。场景删掉之后,引用它的那张画板**此后任何一次保存都 422** —— 哪怕用户只是挪了一张
便签;错误里不说是哪一个节点,唯一的出路是自己找到那个 3D 节点删掉。

**为什么看不出来**:`domain/ownership.py` 那份归属地图管的是**建行**,而且明确豁免了
`app/api/routes/`。删除既不在地图的语义里,路由层又被豁免 —— 那句 `db.delete(scene)` 不会被
任何东西看见。`delete_model` 的说明把这件事想得很透(「删掉就是在别处留一个加载失败的空位,
而那个空位没有任何线索说明它本来是什么」),那段推理对场景一字不差地成立,只是没人搬过去,
**因为场景的删除不在领域层**。

三种答案不是三次权衡,是两次权衡加一次空缺。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.domain.scenes import SceneDomainError, boards_using_scene, delete_scene
from tests.util import fresh_client


def _scene_on_a_board(client, ws: str) -> tuple[str, str]:
    scene = client.post("/api/scenes", json={"workspace_id": ws, "name": "主场景"}).json()
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "分镜板"}).json()
    saved = client.patch(
        f"/api/boards/{board['id']}",
        json={
            "workspace_id": ws,
            "base_revision": board.get("revision", 0),
            "canvas": {"items": [{
                "id": "i1", "kind": "scene", "scene_id": scene["id"],
                "x": 0, "y": 0, "width": 320, "height": 180,
            }]},
        },
    )
    assert saved.status_code in (200, 201), saved.text
    return scene["id"], board["id"]


def test_画板还摆着这个场景时不让删_并点名() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    scene_id, _ = _scene_on_a_board(client, ws)

    with SessionLocal() as db:
        assert boards_using_scene(db, ws, scene_id) == ["分镜板"]
        with pytest.raises(SceneDomainError, match="分镜板"):
            delete_scene(db, ws, scene_id)


def test_没人用的场景照常删得掉() -> None:
    """拒绝是为了不留坏引用,不是为了不让删。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    scene = client.post("/api/scenes", json={"workspace_id": ws, "name": "草稿场景"}).json()

    assert client.delete(f"/api/scenes/{scene['id']}?workspace_id={ws}").status_code == 204
    assert client.get(f"/api/scenes/{scene['id']}?workspace_id={ws}").status_code == 404


def test_接口那条路也走领域的判断() -> None:
    """路由是薄转译:引用完整性的决定不在它这儿。此前它是一句裸的 `db.delete(scene)`。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    scene_id, board_id = _scene_on_a_board(client, ws)

    refused = client.delete(f"/api/scenes/{scene_id}?workspace_id={ws}")
    assert refused.status_code >= 400, "接口把场景删掉了 —— 那张画板从此保存不了"
    assert "分镜板" in refused.text

    # 而且画板此后照样保存得了(它引用的场景还在)。
    board = client.get(f"/api/boards/{board_id}?workspace_id={ws}").json()
    again = client.patch(
        f"/api/boards/{board_id}",
        json={"workspace_id": ws, "base_revision": board["revision"], "canvas": board["canvas"]},
    )
    assert again.status_code in (200, 201), again.text


def test_删除的决定写在领域层() -> None:
    """判据不是"有没有检查",是"检查**在哪一层**" —— 放在路由里的话,下一个入口(智能体、
    工作流、定时任务)不会经过它。"""
    from app.api.routes import scenes as scene_routes
    from tests.util import executable_source

    # **剥掉注释和 docstring 再看** —— 上面那段说明里正好引用了被删掉的旧代码,
    # 直接搜源码文本会打到自己身上(见 tests/util.executable_source 的说明)。
    assert "db.delete(scene)" not in executable_source(scene_routes), "删除的引用完整性决定又回到路由里了"
