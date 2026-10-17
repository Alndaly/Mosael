"""说话输入(ASR)的引擎可以单独选,默认跟随转写。

此前听写没有自己的开关:前端 ``dictate()`` 不传 engine → 路由收到空串 → 按「转写」的默认挑
(第一个装好了运行环境的本机引擎)。这一版在「设置 → 智能体 → 语音对话」里多一格,存的是能力表的
提供方 id;解析顺序是 **显式传的 > 这一格 > 转写默认**(空串 = 交给 capabilities.pick 按默认挑,
与今天完全一致)。

这一格指向一个**没就绪**的引擎时不许悄悄退回跟随转写:那等于把用户做的选择吞掉,界面还显示着它。
按既有规矩交给 capabilities.pick —— 它会带着缺什么(运行环境 / 密钥 / 插件权限)拒绝。
"""

from __future__ import annotations

from app.api.routes import asr as asr_routes
from app.core.db import SessionLocal
from app.db.models import User
from app.domain.voices import transcription
from tests.util import fresh_client

READY_ENGINE = "builtin:whisperx"
OTHER_ENGINE = "builtin:funasr"


def _me() -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == "tester").one().id


def _client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _choose_engine(client, engine: str) -> None:
    """走设置页那条保存路径(PUT /api/settings/agent-voice)存下这一格。"""
    reply = client.put(
        "/api/settings/agent-voice",
        json={
            "engine": "edge",
            "engine_voice": "zh-CN-XiaoxiaoNeural",
            "speed": 1,
            "enabled": False,
            "asr_engine": engine,
        },
    )
    assert reply.status_code == 200, reply.text


def _capture_engine(monkeypatch) -> dict:
    """把路由交给 transcribe_clip 的 engine 参数记下来(验收点名的就是它)。"""
    seen: dict = {}

    def _fake(*_args, **kwargs):
        seen.update(kwargs)
        return "把这句话填进输入框"

    monkeypatch.setattr(transcription, "transcribe_clip", _fake)
    return seen


def _post_clip(client, data: dict | None = None):
    return client.post(
        "/api/asr/dictate",
        files={"clip": ("say.webm", b"not really audio, the engine is stubbed", "audio/webm")},
        data=data or {},
    )


def test_没设过这一格时解析为空_交给转写的默认() -> None:
    """空 = 没有自己的偏好,transcriber 按转写的默认挑 —— 和今天完全一致。"""
    _client()

    assert asr_routes.resolve_dictation_engine(_me(), "") == ""


def test_听写没传引擎且没设过时交给转写的默认(monkeypatch) -> None:
    client = _client()
    seen = _capture_engine(monkeypatch)

    reply = _post_clip(client)

    assert reply.status_code == 200, reply.text
    assert seen["engine"] == "", "没设过时路由交给 transcribe_clip 的应是空串(转写默认)"
    assert reply.json()["text"] == "把这句话填进输入框"


def test_设为某个引擎之后听写用它(monkeypatch) -> None:
    client = _client()
    _choose_engine(client, READY_ENGINE)
    seen = _capture_engine(monkeypatch)

    reply = _post_clip(client)

    assert reply.status_code == 200, reply.text
    assert seen["engine"] == READY_ENGINE, "这一格设了谁,落到 transcribe_clip 的就该是谁"


def test_显式传的引擎压过这一格(monkeypatch) -> None:
    """显式 engine(工作流节点、脚本调用)仍然优先 —— 这一格只补上"没说"的那一半。"""
    client = _client()
    _choose_engine(client, READY_ENGINE)
    seen = _capture_engine(monkeypatch)

    reply = _post_clip(client, {"engine": OTHER_ENGINE})

    assert reply.status_code == 200, reply.text
    assert seen["engine"] == OTHER_ENGINE


def test_这一格指向没就绪的引擎时说清原因而不是悄悄跟随转写(monkeypatch) -> None:
    """缺运行环境的引擎不静默退回默认:用户屏幕上还写着它,失败却来自另一家,没人查得清。"""
    client = _client()
    _choose_engine(client, READY_ENGINE)

    #: whisperx(这一格选的)没有运行环境;funasr(转写默认)有 —— 悄悄退回默认的话这次会**成功**。
    monkeypatch.setattr(
        transcription.asr_models, "resolve_engine_python",
        lambda engine: "python" if engine == "funasr" else None,
    )
    monkeypatch.setattr(transcription, "probe_media", lambda _path: {"duration": 1.0})
    monkeypatch.setattr(transcription, "_extract_audio", lambda _src, _dst: None)
    monkeypatch.setattr(
        transcription, "transcribe_with_engine",
        lambda *_args, **_kwargs: {"segments": [{"text": "偷偷换了一家"}]},
    )

    reply = _post_clip(client)

    assert reply.status_code == 422, reply.text
    detail = reply.json()["detail"]
    assert "运行环境" in detail, detail
    assert "WhisperX" in detail, f"要说清是哪一家用不了:{detail}"
    assert "偷偷换了一家" not in detail


def test_设置接口存得下也读得回这一格() -> None:
    client = _client()

    assert client.get("/api/settings/agent-voice").json()["asr_engine"] == ""
    _choose_engine(client, READY_ENGINE)
    assert client.get("/api/settings/agent-voice").json()["asr_engine"] == READY_ENGINE


def test_选回跟随转写就把这一格清掉(monkeypatch) -> None:
    client = _client()
    _choose_engine(client, READY_ENGINE)
    _choose_engine(client, "")
    seen = _capture_engine(monkeypatch)

    reply = _post_clip(client)

    assert reply.status_code == 200, reply.text
    assert seen["engine"] == "", "清掉之后应当回到跟随转写"
