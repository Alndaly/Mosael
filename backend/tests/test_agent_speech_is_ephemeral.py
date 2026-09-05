"""智能体念出来的话:**说完就没了**。

对话里念的每一句都登记成素材的话,说十句就是十个音频文件躺在素材库里 —— 而它们说完就没用了。
配音是另一回事:那段音频要进成片、要能重放、要挂在任务上,所以它走 job + register_file_asset。
两条路共用同一个合成核心(voices.speak_to_file),只在**产物归谁**这一步分开。

音色也和配音分开:配音要质量(本地克隆、首次加载十几分钟也认),对话要延迟。**没设过就说
没设** —— 语音回复按字符计费,替他挑一个他没选过的音色去念,和替他挑一个模型去回答一样不行。
"""

from __future__ import annotations

from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Asset, Job, User
from app.domain.voices import agent_voice
from tests.util import fresh_client


def _me() -> str:
    with SessionLocal() as db:
        return db.query(User).first().id


def _choose_voice(**overrides) -> None:
    with SessionLocal() as db:
        agent_voice.upsert(db, _me(), **{"engine": "edge", "engine_voice": "zh-CN-XiaoxiaoNeural", **overrides})


def test_没设过音色就说没设而不是替他挑一个() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    reply = client.post("/api/agent/speech", json={"text": "念一句", "workspace_id": workspace["id"]})
    assert reply.status_code == 409, reply.text
    assert "语音对话" in reply.json()["detail"]


def test_念一句不留下素材也不留下任务(monkeypatch) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _choose_voice()

    def _fake_speak(_db, **kwargs):
        out = Path(kwargs["out_dir"]) / "speech.mp3"
        out.write_bytes(b"ID3fake-audio")
        return out

    from app.domain.voices import voices as voices_domain

    monkeypatch.setattr(voices_domain, "speak_to_file", _fake_speak)
    with SessionLocal() as db:
        before = (db.query(Asset).count(), db.query(Job).count())

    reply = client.post("/api/agent/speech", json={"text": "这句话说完就没了", "workspace_id": workspace["id"]})
    assert reply.status_code == 200, reply.text
    assert reply.content == b"ID3fake-audio"
    assert reply.headers["content-type"].startswith("audio/")

    with SessionLocal() as db:
        assert (db.query(Asset).count(), db.query(Job).count()) == before, "念一句留下了素材或任务"


def test_合成失败是结果不是服务端故障(monkeypatch) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _choose_voice()

    from app.domain.voices import voices as voices_domain

    def _boom(_db, **_kwargs):
        raise RuntimeError("这条连接没有配 API Key")

    monkeypatch.setattr(voices_domain, "speak_to_file", _boom)
    reply = client.post("/api/agent/speech", json={"text": "念", "workspace_id": workspace["id"]})
    assert reply.status_code == 422
    assert "API Key" in reply.json()["detail"]


def test_对话音色和配音默认是两行配置() -> None:
    """两者共用一个默认的话,必然在某一边是错的 —— 这条钉的是它们互不影响。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    assert client.get("/api/settings/agent-voice").json()["enabled"] is False
    saved = client.put(
        "/api/settings/agent-voice",
        json={"engine": "edge", "engine_voice": "zh-CN-XiaoxiaoNeural", "speed": 1.25, "enabled": True},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["engine"] == "edge" and saved.json()["speed"] == 1.25

    # 配音那一格没有因此被设上 —— 它是另一份配置。
    tts_default = [row for row in client.get("/api/settings/provider-defaults").json() if row["capability"] == "tts"]
    assert tts_default and not tts_default[0]["provider_profile_id"]


def test_语速被夹在可用区间里() -> None:
    """各家引擎对超范围的语速反应不一:有的当场拒,有的悄悄夹取 —— 那两种都不好解释。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    reply = client.put(
        "/api/settings/agent-voice",
        json={"engine": "edge", "engine_voice": "x", "speed": 9.0, "enabled": True},
    )
    assert reply.json()["speed"] == 2.0
