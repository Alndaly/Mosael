"""配音节点运行时说一句「这次用的是哪把嗓子」(`voice_note`)—— 按**实际**念的引擎和音色说,不是建图时写死的。

带货口播的完成通知此前写的是建图那一刻的判断(「配音用的是免费的 Edge 音色:建这张图时配音库里没有克隆音色」):
之后在节点里换上克隆音色,通知照样这么说。用的不是克隆音色时,顺带说清楚配音库里有没有能用的克隆音色。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.unit_of_work import unit_of_work
from app.db.models import Workflow
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client, make_voice


@pytest.fixture
def speak(monkeypatch):
    """不真的合成:起合成任务、等它的那两步换成假的。"""
    from app.domain.voices import voices
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(voices, "start_synthesis", lambda db, **kwargs: SimpleNamespace(id="child"))
    monkeypatch.setattr(subjobs, "wait_for_job", lambda job_id, release=None: SimpleNamespace(result={"asset_id": "a1"}))

    def run(ws: str, engine: str, voice: str) -> dict:
        with unit_of_work() as db:
            workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
            db.add(workflow)
            db.flush()
            return get_executor("synthesize_speech")(db, workflow, {"text": "点下方链接", "engine": engine, "voice": voice})

    return run


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _clone_engine(monkeypatch, *, ready: bool) -> None:
    from app.ai.runtime import tts_models

    monkeypatch.setattr(tts_models, "runtime_status", lambda engine: (ready, True))
    monkeypatch.setattr(tts_models, "is_installed", lambda engine: True)


def test_用的是_Edge_配音库里没有克隆音色(speak, monkeypatch) -> None:
    _clone_engine(monkeypatch, ready=True)
    out = speak(_workspace(), "builtin:edge", "zh-CN-XiaoxiaoNeural")
    assert out["asset_id"] == "a1"
    note = out["voice_note"]
    assert "Edge" in note and "晓晓" in note and "没有能用的克隆音色" in note, note


def test_用的是_Edge_配音库里其实有能用的克隆音色(speak, monkeypatch) -> None:
    ws = _workspace()
    make_voice(ws, "我的嗓子")
    _clone_engine(monkeypatch, ready=True)
    note = speak(ws, "builtin:edge", "zh-CN-YunxiNeural")["voice_note"]
    assert "云希" in note and "配音库里有克隆音色" in note, note


def test_用的是克隆音色_说出它的名字(speak, monkeypatch) -> None:
    ws = _workspace()
    voice = make_voice(ws, "我的嗓子")
    _clone_engine(monkeypatch, ready=True)
    note = speak(ws, "builtin:clone", voice)["voice_note"]
    assert "克隆音色" in note and "我的嗓子" in note and "Edge" not in note, note
