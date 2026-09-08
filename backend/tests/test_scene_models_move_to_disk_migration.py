"""3D 模型的字节从数据库挪到磁盘的那一次迁移。

这类迁移只在"老装机第一次跑新版本"时发生一次,肉眼几乎不可能复验,而它错了就是**模型全部
打不开** —— 行还在、文件不在,视口只会说加载失败。

判据四条:字节原样落到磁盘、`file_key` / `size` 回填、老的 `data` 列消失(留着的话库文件
不会变小,这次搬迁就白做),以及**跑第二次不炸**(迁移必须可重入 —— 中途断电就是这个场景)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import engine
from app.core.config import settings
from app.db.migrations import _migrate_scene_models_to_disk
from app.media.paths import resolve_key
from tests.util import fresh_client

GLB = b"glTF" + bytes(64)


def _old_shaped_table(workspace_id: str, scene_id: str) -> None:
    """把 scene_3d_models 退回迁移前的形状(字节在 data 列里)。

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
            "data BLOB NOT NULL)"
        ))
        conn.execute(text("DELETE FROM scenes_3d"))
        conn.execute(text(
            "INSERT INTO scenes_3d (id, workspace_id, name, content, revision, created_at, updated_at) "
            "VALUES (:s, :w, 'S', '{}', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ), {"s": scene_id, "w": workspace_id})
        conn.execute(text("INSERT INTO scene_3d_models VALUES ('m-1', :s, 'Model', 'glb', :d)"),
                     {"s": scene_id, "d": GLB})
    engine.dispose()


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("scene_3d_models")}


def test_bytes_move_to_disk_and_the_blob_column_goes_away() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _old_shaped_table(workspace_id, "sc-1")
    assert "data" in _columns()

    _migrate_scene_models_to_disk()

    with engine.begin() as conn:
        key, size = conn.execute(text("SELECT file_key, size FROM scene_3d_models WHERE id='m-1'")).one()
    assert resolve_key(key).read_bytes() == GLB, "字节没落到磁盘 —— 模型会全部打不开"
    assert size == len(GLB)
    assert key.startswith("media/"), "必须落在 media 下面,否则备份不会带上它"
    assert resolve_key(key).is_relative_to(settings.media_dir / "scene-models" / workspace_id / "sc-1")
    assert "data" not in _columns(), "老列还在,库文件不会变小,这次搬迁就白做了"


def test_running_it_again_is_a_no_op() -> None:
    # 中途断电就是这个场景:文件已经写了一部分,列还没 DROP。下一次启动必须能接着跑完。
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _old_shaped_table(workspace_id, "sc-2")

    _migrate_scene_models_to_disk()
    _migrate_scene_models_to_disk()

    with engine.begin() as conn:
        key = conn.execute(text("SELECT file_key FROM scene_3d_models WHERE id='m-1'")).scalar()
    assert resolve_key(key).read_bytes() == GLB
