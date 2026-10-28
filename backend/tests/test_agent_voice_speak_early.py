"""念回复时先出声的开关:一列默认值 + 两条保存路径(迁移 / 设置接口)。

`agent_voice_prefs.speak_early` 默认 1(先出声)。这一列**只有对话类读**;文件类(工作流
「语音合成」节点、画板音配音、笔记「存成素材」)永远整段一次,连它都不看。这里只钉住"存得下、
读得回、老库升上来不炸"。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(agent_voice_prefs)"))}


def _old_table() -> None:
    """升级前的形状(有 asr_engine、没有 speak_early),里面有一行已经配好的对话音色。"""
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
            "asr_engine VARCHAR(100) NOT NULL DEFAULT '', "
            "updated_at DATETIME NOT NULL)"))
        conn.execute(text(
            "INSERT INTO agent_voice_prefs (owner_user_id, engine, engine_voice, speed, enabled, updated_at) "
            "VALUES ('u-old', 'edge', 'zh-CN-XiaoxiaoNeural', 1.25, 1, '2026-01-01 00:00:00')"))


def _row() -> tuple:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT engine, engine_voice, speed, enabled, asr_engine, speak_early "
            "FROM agent_voice_prefs WHERE owner_user_id = 'u-old'")).one()










def _settings(client, **extra: object):
    body = {"voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"}, "speed": 1, "enabled": False}
    body.update(extra)
    return client.put("/api/settings/agent-voice", json=body)


def test_没设过时先出声_设成等整段读得回_再省掉这一格又回到默认() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    assert client.get("/api/settings/agent-voice").json()["speak_early"] is True

    reply = _settings(client, speak_early=False)
    assert reply.status_code == 200, reply.text
    assert reply.json()["speak_early"] is False
    assert client.get("/api/settings/agent-voice").json()["speak_early"] is False

    #: 老客户端/别的调用方不带这一格:按默认(先出声)存,不要把上一份值卡住。
    assert _settings(client).json()["speak_early"] is True
    assert client.get("/api/settings/agent-voice").json()["speak_early"] is True
