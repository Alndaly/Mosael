"""migrate-provider-profiles-get-a-tombstone:老的 provider_profiles 表补上 deleted_at。

`create_all` 只建缺失的**表**、不给已存在的表加列 —— 没有这一步,升级的机器上后端起不来
(no such column: provider_profiles.deleted_at)。

喂的是**加列之前的形状**:把列退回去(老库没有它),再跑一遍这一步,然后看这一列到得了、
老库里的连接没有被误标成「已删」、再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_provider_profiles_get_a_tombstone as add_column
from app.db.models import ProviderProfile
from tests.util import fresh_client


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("provider_profiles")}


def test_老表补上墓碑那一列_老连接都算还在_再跑一次什么都不做() -> None:
    client = fresh_client()
    created = client.post(
        "/api/settings/providers",
        json={
            "name": "老连接",
            "vendor": "openai-compatible",
            "config": {"base_url": "https://x.example/v1", "default_model": "m", "api_key": "k"},
        },
    )
    assert created.status_code == 200, created.text
    profile_id = created.json()["id"]

    # 退回加列之前的形状:老库的 provider_profiles 没有这一列。
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_profiles DROP COLUMN deleted_at"))

    add_column()
    add_column()  # 再跑一次什么都不做

    assert "deleted_at" in _columns()
    with SessionLocal() as db:
        assert db.get(ProviderProfile, profile_id).deleted_at is None, "老库里的连接不是「已删」——这一步不搬数据"
