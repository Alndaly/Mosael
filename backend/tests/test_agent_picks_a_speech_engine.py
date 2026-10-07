"""智能体念字配音:引擎和音色成对,开卡时就定下来 —— 认不出就把能用的 id 摆给它。

用户反馈的那一轮:智能体先写 `engine: "edge-tts"`,被一句「没有这个配音引擎」打发;再只给音色
`zh-CN-XiaoxiaoNeural`,卡开出来了、批准之后才失败,报「没有配置可用于语音生成的真实供应商」—— 它去查了
一个按设计不存在的「语音合成默认模型」。于是它告诉用户「去设置里把 edge-tts 配为语音生成引擎」,而 Edge 是
内置的 `builtin:edge`,免费、什么都不用配。

这里全走真路径:智能体经工具通道开卡(`/api/agent/tools/...`,sidecar 发的就是这个请求),引擎解析、校验不打桩;
只有 Edge 真去联网的那一下(edge_tts.Communicate)换成写一段本地音频。
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import Asset, Job, User
from app.domain.jobs import wait_for_idle_jobs
from tests.util import fresh_client


class Chat:
    def __init__(self) -> None:
        self.client = fresh_client()
        self.workspace_id = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        session_id = self.client.post(
            "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": self.workspace_id, "title": "T"}
        ).json()["id"]
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            self.token = mint_service_session(db, user.id, agent_session_id=session_id)

    def call(self, tool: str, **arguments) -> dict:
        response = self.client.post(
            f"/api/agent/tools/{tool}",
            json={"arguments": {"workspace_id": self.workspace_id, **arguments}, "requested_by": "pi"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def speak(self, **arguments) -> dict:
        return self.call("generate_audio", text="测试", **arguments)


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    return buf.getvalue()


@pytest.fixture()
def edge_offline(monkeypatch):
    """Edge 真去联网的只有 edge_tts.Communicate 这一处;换成写一秒本地音频,记下它被要求念什么。"""
    import edge_tts

    spoken: list[dict] = []

    class Communicate:
        def __init__(self, text: str, voice: str = "", rate: str = "") -> None:
            spoken.append({"text": text, "voice": voice})

        async def save(self, path: str) -> None:
            Path(path).write_bytes(_wav())

    monkeypatch.setattr(edge_tts, "Communicate", Communicate)
    return spoken


def test_只给音色_认出是Edge的_开卡就写上引擎_批准后真的念出来(edge_offline) -> None:
    chat = Chat()

    card = chat.speak(voice="zh-CN-XiaoxiaoNeural")["result"]

    row = chat.client.get(f"/api/confirmations/{card['confirmation_id']}").json()
    assert row["payload"]["engine"] == "builtin:edge", "卡上要写明用哪个引擎 —— 用户批的就是这一对"
    approved = chat.client.post(f"/api/confirmations/{card['confirmation_id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert wait_for_idle_jobs(timeout=30)
    with SessionLocal() as db:
        job = db.get(Job, approved["result"]["job_id"])
        assert job.status == "succeeded", job.error
        assert db.query(Asset).filter(Asset.workspace_id == chat.workspace_id, Asset.kind == "audio").count() == 1
    assert edge_offline == [{"text": "测试", "voice": "zh-CN-XiaoxiaoNeural"}]


def test_引擎写成别名_开卡时就拒_并给出正确的id() -> None:
    chat = Chat()

    refused = chat.speak(engine="edge-tts", voice="zh-CN-XiaoxiaoNeural")

    assert "result" not in refused
    assert "edge-tts" in refused["error"]
    assert "builtin:edge" in refused["error"], "认不出时要把能用的 id 摆出来,下一次它才写得对"


def test_什么都没给_不替人挑_说清能用哪些_免费的是哪个() -> None:
    """配音没有默认 —— 替他挑一个要钥匙的就是替他花钱。说清楚有什么,让它(或用户)点名。"""
    chat = Chat()

    refused = chat.speak()

    assert "result" not in refused
    assert "builtin:edge" in refused["error"]
    assert "免费" in refused["error"]
    assert "真实供应商" not in refused["error"]


def test_点名一个没配好的云端引擎_开卡时就说_不等批准之后() -> None:
    chat = Chat()

    refused = chat.speak(engine="builtin:openai", voice="nova")

    assert "result" not in refused, "没配连接的引擎开出卡来,批准之后必然失败"
    assert "还用不了" in refused["error"]


def test_认不出的音色_说出来并列出引擎() -> None:
    chat = Chat()

    refused = chat.speak(voice="no-such-voice")

    assert "no-such-voice" in refused["error"]
    assert "builtin:edge" in refused["error"]


def test_智能体查得到有哪些配音引擎_各自的id和音色() -> None:
    chat = Chat()
    manifest = {tool["name"]: tool for tool in chat.client.get(
        "/api/agent/tools", headers={"Authorization": f"Bearer {chat.token}"}
    ).json()}
    assert manifest["list_speech_engines"]["confirmation"] is False
    assert manifest["list_speech_engines"]["read_only"] is True

    engines = {one["id"]: one for one in chat.call("list_speech_engines")["result"]}

    edge = engines["builtin:edge"]
    assert edge["ready"] is True and edge["free"] is True
    assert {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓(女·温暖)"} in edge["voices"]
    assert engines["builtin:openai"]["ready"] is False, "没配连接的要说出来,别让它挑中之后才失败"
    assert "builtin:volcano-podcast" not in engines, "播客不念一句话"
