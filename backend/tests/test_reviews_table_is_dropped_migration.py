"""`reviews` 那张表被删掉的那一次迁移。

评审是一条**完整的后端功能,而界面上零入口**:表、领域、路由、测试都在,前端、i18n、MCP 工具、
智能体工具没有任何一处碰过它。2026-09-23 与用户确认后整条删掉。

判据三条:老库里那张表真的没了、**活动流里已有的评审记录原样留着**(那是发生过的事,不因为
功能没了就抹掉),以及跑第二次不炸(迁移必须可重入 —— 中途断电就是这个场景)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import engine
from app.db.migrations import _drop_reviews_table
from tests.util import fresh_client


def _tables() -> set[str]:
    return set(inspect(engine).get_table_names())


def test_老库里的评审表被删掉_活动流原样留着() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with engine.begin() as conn:
        # 老形状:这张表在,里面还有一行没决完的评审。
        conn.execute(text(
            "CREATE TABLE reviews (id VARCHAR(64) PRIMARY KEY, workspace_id VARCHAR(64), "
            "subject_type VARCHAR(40), subject_id VARCHAR(64), status VARCHAR(16))"
        ))
        conn.execute(text(
            "INSERT INTO reviews VALUES ('r1', 'ws', 'board', 'b1', 'pending')"
        ))
        # 活动流里那条"请求了评审"的记录:删功能不该连带抹掉历史。
        conn.execute(text(
            "INSERT INTO activity_events (id, workspace_id, actor_id, action, subject_type, subject_id, "
            "summary, payload, created_at) VALUES ('a1', :ws, NULL, 'review.requested', 'board', 'b1', "
            "'', '{}', CURRENT_TIMESTAMP)"
        ), {"ws": workspace})
    assert "reviews" in _tables()

    _drop_reviews_table()

    assert "reviews" not in _tables()
    with engine.connect() as conn:
        kept = conn.execute(text("SELECT action FROM activity_events WHERE id = 'a1'")).scalar()
    assert kept == "review.requested", "活动流里发生过的评审被一起抹掉了"


def test_跑第二次不炸() -> None:
    fresh_client()
    _drop_reviews_table()  # 新装的库上本来就没有这张表
    _drop_reviews_table()
    assert "reviews" not in _tables()
