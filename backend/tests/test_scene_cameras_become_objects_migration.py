"""相机从「镜头里的一串关键帧」变成场景物体的那一次迁移。

这类迁移只在"老装机第一次跑新版本"时发生一次,而它错了就是**所有 3D 场景打不开** ——
新的 SceneShot 要求 camera_id,老内容里没有,读一次就是 422。

判据四条:运镜原样搬到相机物体的 track 上、镜头改成引用它、**历史版本快照也一起改写**
(不然升级后所有旧版本都恢复不了)、以及跑第二次不再改动任何东西。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_scene_cameras_become_objects
from app.domain.scene_types import SceneContent
from tests.util import fresh_client

OLD_CONTENT = {
    "version": 1,
    "objects": [{"id": "box-1", "kind": "box", "name": "盒子"}],
    "shots": [{
        "id": "shot-1", "name": "环绕", "duration": 6, "aspect": "16:9", "easing": "smooth",
        "frames": [
            {"time": 0, "position": [8, 5, 8], "target": [0, 1, 0], "fov": 45},
            {"time": 6, "position": [-8, 5, 8], "target": [0, 1, 0], "fov": 50},
        ],
    }],
    "background": "#20242c",
    "ambient": 1.5,
}


def _seed(workspace_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM scenes_3d"))
        conn.execute(text(
            "INSERT INTO scenes_3d (id, workspace_id, name, content, revision, created_at, updated_at) "
            "VALUES ('sc-1', :w, 'S', :c, 2, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ), {"w": workspace_id, "c": json.dumps(OLD_CONTENT)})
        conn.execute(text("DELETE FROM scene_3d_revisions"))
        conn.execute(text(
            "INSERT INTO scene_3d_revisions (scene_id, revision, snapshot, created_at) "
            "VALUES ('sc-1', 1, :s, '2026-01-01 00:00:00')"
        ), {"s": json.dumps({"name": "S", "content": OLD_CONTENT})})


def _content() -> dict:
    with engine.begin() as conn:
        return json.loads(conn.execute(text("SELECT content FROM scenes_3d WHERE id='sc-1'")).scalar())


def _snapshot() -> dict:
    with engine.begin() as conn:
        raw = conn.execute(text("SELECT snapshot FROM scene_3d_revisions WHERE scene_id='sc-1'")).scalar()
    return json.loads(raw)


def test_the_shot_becomes_a_camera_object_that_owns_the_move() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _seed(workspace_id)

    _migrate_scene_cameras_become_objects()

    content = _content()
    shot = content["shots"][0]
    assert "frames" not in shot, "运镜还留在镜头上 —— 那正是这次要搬走的东西"
    camera = next(o for o in content["objects"] if o["id"] == shot["camera_id"])
    assert camera["kind"] == "camera"
    assert camera["name"] == "环绕"                       # 机位沿用镜头的名字,不是一个新词
    assert [f["time"] for f in camera["track"]] == [0, 6]  # 运镜原样搬过来
    assert camera["position"] == [8, 5, 8]                 # 静态位置取第一帧
    assert camera["fov"] == 45
    assert any(o["id"] == "box-1" for o in content["objects"]), "原有物体不该被动"

    # 最要紧的一条:改写完的内容必须能被新模型读出来。
    parsed = SceneContent.model_validate(content)
    assert parsed.shots[0].camera_id == camera["id"]


def test_old_revisions_are_rewritten_too_or_they_can_never_be_restored() -> None:
    # 快照平时是原样返回的(不过校验),但"恢复某个版本"会把它送回保存那条路 ——
    # 不改写的话,升级之后所有旧版本都恢复不了,而报错是一次 422,说的是 shots 缺 camera_id。
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _seed(workspace_id)

    _migrate_scene_cameras_become_objects()

    snapshot = _snapshot()
    assert "frames" not in snapshot["content"]["shots"][0]
    SceneContent.model_validate(snapshot["content"])


def test_a_still_shot_does_not_get_an_empty_track() -> None:
    # 单帧的镜头是"固定机位":没有运动就不必留一条轨,静态位置已经说完了。
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    still = json.loads(json.dumps(OLD_CONTENT))
    still["shots"][0]["frames"] = [still["shots"][0]["frames"][0]]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM scenes_3d"))
        conn.execute(text(
            "INSERT INTO scenes_3d (id, workspace_id, name, content, revision, created_at, updated_at) "
            "VALUES ('sc-1', :w, 'S', :c, 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ), {"w": workspace_id, "c": json.dumps(still)})

    _migrate_scene_cameras_become_objects()

    camera = next(o for o in _content()["objects"] if o["kind"] == "camera")
    assert camera["track"] == []


def test_running_it_again_changes_nothing() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _seed(workspace_id)

    _migrate_scene_cameras_become_objects()
    once = _content()
    _migrate_scene_cameras_become_objects()

    assert _content() == once, "第二次又长出一台相机 —— 中途断电重跑就会翻倍"
