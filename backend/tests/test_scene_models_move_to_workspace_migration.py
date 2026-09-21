"""3D 模型从「归场景」改成「归工作区」的那一次迁移。

这类迁移只在"老装机第一次跑新版本"时发生一次,肉眼几乎不可能复验,而它错了就是**模型全部
打不开** —— 行还在、文件不在,视口只会说加载失败。

判据五条:文件从按场景分的目录提到按工作区分的目录、`file_key` 跟着改、`scene_id` 换成
`workspace_id`、场景已经不在的孤儿行跟着丢掉,以及**跑第二次不炸**(迁移必须可重入 ——
中途断电就是这个场景)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.db import engine
from app.db.migrations import _migrate_scene_models_to_workspace
from app.media.paths import resolve_key
from tests.util import fresh_client

GLB = b"glTF" + bytes(64)


def _old_shaped_table(workspace_id: str, scenes: dict[str, str]) -> None:
    """把 scene_3d_models 退回迁移前的形状(挂在 scene_id 上,文件按场景分目录)。

    **DDL 之后必须 dispose 连接池**:SQLite 每条连接各自缓存表结构,而迁移里的
    `inspect(engine)` 可能拿到另一条 —— 那一条还记着 DROP 之前的样子。macOS 上往往撞不到,
    Linux 的 CI 上必现(见 test_auth_session_expiry_migration 的同一条注释)。
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS scene_3d_models"))
        conn.execute(text(
            "CREATE TABLE scene_3d_models ("
            "id VARCHAR(64) NOT NULL PRIMARY KEY, "
            "scene_id VARCHAR(64) NOT NULL, "
            "name VARCHAR(160) NOT NULL, "
            "format VARCHAR(10) NOT NULL, "
            "file_key VARCHAR(512) NOT NULL DEFAULT '', "
            "size INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text("DELETE FROM scenes_3d"))
        for model_id, scene_id in scenes.items():
            conn.execute(text(
                "INSERT INTO scenes_3d (id, workspace_id, name, content, revision, created_at, updated_at) "
                "VALUES (:s, :w, 'S', '{}', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            ), {"s": scene_id, "w": workspace_id})
            key = f"media/scene-models/{workspace_id}/{scene_id}/{model_id}.glb"
            path = resolve_key(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(GLB)
            conn.execute(text(
                "INSERT INTO scene_3d_models VALUES (:m, :s, 'Model', 'glb', :k, :n)"
            ), {"m": model_id, "s": scene_id, "k": key, "n": len(GLB)})
    engine.dispose()


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("scene_3d_models")}


def test_模型提到工作区_文件跟着搬_场景那一列消失() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _old_shaped_table(workspace_id, {"m-1": "sc-1", "m-2": "sc-2"})
    assert "scene_id" in _columns()

    _migrate_scene_models_to_workspace()

    assert "workspace_id" in _columns() and "scene_id" not in _columns()
    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, file_key FROM scene_3d_models")).all())
        owners = {row[0] for row in conn.execute(text("SELECT workspace_id FROM scene_3d_models")).all()}
    assert owners == {workspace_id}
    for key in rows.values():
        path = resolve_key(key)
        assert path.read_bytes() == GLB, "字节没跟着搬 —— 模型会全部打不开"
        assert path.parent == settings.media_dir / "scene-models" / workspace_id, "目录要按工作区分,不再按场景"
    assert set(rows) == {"m-1", "m-2"}


def test_场景已经不在的孤儿行跟着丢掉() -> None:
    """它的场景没了,没有任何入口能再看到它 —— 搬过去只是一行指着一个谁也不认识的文件。"""
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _old_shaped_table(workspace_id, {"m-1": "sc-1"})
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO scene_3d_models VALUES ('orphan', 'gone', 'X', 'glb', '', 0)"))

    _migrate_scene_models_to_workspace()

    with engine.begin() as conn:
        assert [row[0] for row in conn.execute(text("SELECT id FROM scene_3d_models")).all()] == ["m-1"]


def test_跑第二次不炸() -> None:
    # 中途断电就是这个场景:文件已经搬了一部分,表还没换。下一次启动必须能接着跑完。
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _old_shaped_table(workspace_id, {"m-1": "sc-1"})

    _migrate_scene_models_to_workspace()
    _migrate_scene_models_to_workspace()

    with engine.begin() as conn:
        key = conn.execute(text("SELECT file_key FROM scene_3d_models WHERE id='m-1'")).scalar()
    assert resolve_key(key).read_bytes() == GLB
