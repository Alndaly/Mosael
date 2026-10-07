"""表单是工作流的入口(ADR 0045)带的加列迁移:老库上加得上、原有的行一条不少,再跑一次什么都不变。

- `provider_models.declared_group`:连接说这个模型是哪样东西的哪个入口。只加列、不回填(插件目录刷新时写)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_provider_models_remember_their_group
from app.db.models import ProviderModel
from tests.util import add_provider, fresh_client


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_模型行加上组那一列_原有的行原样_再跑一次不变() -> None:
    fresh_client()
    with SessionLocal() as db:
        add_provider(db, name="Local", vendor="openai-compatible", base_url="http://127.0.0.1:11434/v1",
                     api_key="k", model="some-model", capability_ids=["chat"], owner_username="tester")
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_models DROP COLUMN declared_group"))
    # SQLite 每条连接各自缓存表结构:DDL 之后换一批连接,迁移里的 inspect 才看得到 DROP 之后的样子
    engine.dispose()
    assert "declared_group" not in _columns("provider_models")

    _migrate_provider_models_remember_their_group()
    engine.dispose()
    assert "declared_group" in _columns("provider_models")
    with SessionLocal() as db:
        rows = db.query(ProviderModel).filter(ProviderModel.model_id == "some-model").all()
        assert [(row.model_id, row.declared_group) for row in rows] == [("some-model", None)], "不回填:插件目录刷新时写"

    _migrate_provider_models_remember_their_group()
    assert "declared_group" in _columns("provider_models")
