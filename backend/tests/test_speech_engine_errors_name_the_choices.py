"""配音引擎名不靠猜:点错了,回给模型的那句话里就有能用的引擎 id,和不用配置、不花钱的那一个。

用户会话(Kimi · k3):generate_audio 先后传 engine=edge、edge-tts,两次都只拿到「没有这个配音引擎」;再往后又撞上
「没有配置可用于语音生成的真实供应商」,于是转头请用户去设置里配 Edge —— 而 Edge 是内置的、免费的、什么都不用配。

两条入口都要说清楚:开卡时(pick_speech,generate_audio / dub_subtitles)和真去合成时(require_engine,
工作流节点、画板、字幕配音、卡批准之后)。走真实入口:智能体经 /api/agent/tools 调 generate_audio。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import User
from app.domain.voices.speech import SpeechProviderUnavailable, require_engine
from tests.util import fresh_client


def _turn():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = client.post("/api/agent/sessions", json={"workspace_id": ws, "title": "T"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, me.id, agent_session_id=sid)
    return client, ws, token, me.id


def test_认得出的名字照认_卡上记的是引擎id() -> None:
    """「edge」是 Edge 引擎的名字:认得出就认,卡上写回 builtin:edge —— 用户批的是那一对。"""
    from app.db.models import ToolConfirmation

    client, ws, token, _me = _turn()
    response = client.post(
        "/api/agent/tools/generate_audio",
        json={"arguments": {"text": "你好", "engine": "edge", "voice": "zh-CN-XiaoxiaoNeural", "workspace_id": ws}},
        headers={"Authorization": f"Bearer {token}"},
    )
    card_id = response.json()["result"]["confirmation_id"]
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).payload["engine"] == "builtin:edge"


def test_认不出的引擎_回话里有能用的id_并点出不用配置不花钱的那一个() -> None:
    client, ws, token, _me = _turn()
    response = client.post(
        "/api/agent/tools/generate_audio",
        json={"arguments": {"text": "你好", "engine": "edge-tts", "voice": "zh-CN-XiaoxiaoNeural", "workspace_id": ws}},
        headers={"Authorization": f"Bearer {token}"},
    )
    said = str(response.json()["error"])
    assert "builtin:edge" in said, f"没告诉模型该写什么:{said}"
    assert "不用配置、不花钱" in said, f"没点出哪一个不用配:{said}"


def test_合成那一步认不出引擎_也列出能用的id(monkeypatch) -> None:
    """工作流节点、画板、卡批准之后走的是 require_engine:此前只有一句「没有这个配音引擎:edge」。"""
    _client, ws, _token, me = _turn()
    with SessionLocal() as db, pytest.raises(SpeechProviderUnavailable) as caught:
        require_engine(db, "edge", user_id=me)
    assert "builtin:edge" in str(caught.value), f"只说了一句认不出:{caught.value}"
    assert "不用配置、不花钱" in str(caught.value)
