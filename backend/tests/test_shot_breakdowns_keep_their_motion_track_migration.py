"""镜头表补上「曲线去哪了」那一列(`_migrate_shot_breakdowns_keep_their_motion_track`)。

曲线是这一版才留的:老库里的 `shot_breakdowns` 没有 `motion_track`,而 `create_all` 只建新表、不给已有的表补列。
补上之后老行是 `{}` = 没有曲线(那时量完就丢了,没有可以补出来的东西)。

**这条和 test_schema_migrations_cover_the_models 里那条端到端的种子测试是两回事**:那条让这条迁移在一个
有数据的老库上跑一遍,这条说清「跑完补成什么样、再跑一次是不是什么都不做」。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import ShotBreakdown
from tests.util import fresh_client, insert_asset


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(shot_breakdowns)"))}


def test_老库的镜头表补上曲线摘要这一列() -> None:
    from app.db.migrations import _migrate_shot_breakdowns_keep_their_motion_track

    client = fresh_client()  # 建好当前的库
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset_id = insert_asset(ws_id, kind="video", name="老片", file_key="", media_info={})
    with SessionLocal() as db:
        db.add(ShotBreakdown(asset_id=asset_id, workspace_id=ws_id, lang="zh", params={}, meta={},
                             cuts=[], shots=[], sheets=[], motion_track={"hz": 5, "points": 19, "digest": "sha256:x"}))
        db.commit()

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE shot_breakdowns DROP COLUMN motion_track"))
    assert "motion_track" not in _columns()

    _migrate_shot_breakdowns_keep_their_motion_track()
    assert "motion_track" in _columns()
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT motion_track FROM shot_breakdowns")).scalar()
    assert raw == "{}", "老行 = 没有曲线(那时量完就丢了),不是空值也不是猜出来的一条"

    _migrate_shot_breakdowns_keep_their_motion_track()  # 再跑一次不报 duplicate column
