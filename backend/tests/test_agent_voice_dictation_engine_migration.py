"""迁移 ``migrate-agent-voice-dictation-engine``:给已有库的 ``agent_voice_prefs`` 补 ``asr_engine``。

这一列空串 = 跟随转写默认 —— 正是升级前所有行的行为,所以**不回填任何引擎名**:替人挑一个没选过的引擎,
和替人挑一个没选过的音色是同一类错误。老行里已经存着的音色、语速、开关一个字都不动;再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_agent_voice_dictation_engine, migration_plan
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(agent_voice_prefs)"))}


def _old_table() -> None:
    """升级前的形状(没有 asr_engine),里面有一行已经配好的对话音色。"""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE agent_voice_prefs"))
        conn.execute(text(
            "CREATE TABLE agent_voice_prefs ("
            "owner_user_id VARCHAR(64) PRIMARY KEY, "
            "engine VARCHAR(40) NOT NULL DEFAULT '', "
            "engine_voice VARCHAR(120) NOT NULL DEFAULT '', "
            "engine_voice_resource VARCHAR(200) NOT NULL DEFAULT '', "
            "engine_model VARCHAR(120) NOT NULL DEFAULT '', "
            "provider_profile_id VARCHAR(64), "
            "voice_id VARCHAR(64), "
            "speed FLOAT NOT NULL DEFAULT 1.0, "
            "enabled BOOLEAN NOT NULL DEFAULT 0, "
            "updated_at DATETIME NOT NULL)"))
        conn.execute(text(
            "INSERT INTO agent_voice_prefs (owner_user_id, engine, engine_voice, speed, enabled, updated_at) "
            "VALUES ('u-old', 'edge', 'zh-CN-XiaoxiaoNeural', 1.25, 1, '2026-01-01 00:00:00')"))


def _row() -> tuple:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT engine, engine_voice, speed, enabled, asr_engine FROM agent_voice_prefs "
            "WHERE owner_user_id = 'u-old'")).one()


def test_迁移登记在计划里() -> None:
    assert "migrate-agent-voice-dictation-engine" in {step.name for step in migration_plan().steps}


def test_老库补上这一列_老行是空串_别的字段不动() -> None:
    fresh_client()
    _old_table()
    assert "asr_engine" not in _columns()

    _migrate_agent_voice_dictation_engine()

    assert "asr_engine" in _columns()
    assert tuple(_row()) == ("edge", "zh-CN-XiaoxiaoNeural", 1.25, 1, ""), "空串 = 跟随转写默认"


def test_再跑一次什么都不做() -> None:
    fresh_client()
    _old_table()
    _migrate_agent_voice_dictation_engine()
    before = _row()

    _migrate_agent_voice_dictation_engine()  # 不报 duplicate column,也不改已有的值

    assert _row() == before


def test_没有这张表的老库不建半张() -> None:
    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE agent_voice_prefs"))

    _migrate_agent_voice_dictation_engine()

    assert _columns() == set()
