"""试听一把嗓子(资产的音色):念一小句,音频直接回来;走和真用时同一条合成路(synthesis_params + speak_to_file)。"""

from __future__ import annotations

from pathlib import Path

from app.domain.voices import voices
from tests.util import fresh_client


def test_引擎音色念一小句_直接回音频_不建任务(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    calls: list[dict] = []

    def fake_speak(db, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        out = Path(kwargs["out_dir"]) / "say.mp3"
        out.write_bytes(b"ID3fake")
        return out

    monkeypatch.setattr(voices, "speak_to_file", fake_speak)
    jobs_before = len(client.get("/api/jobs", params={"workspace_id": ws}).json())
    heard = client.post("/api/tts/preview", json={
        "workspace_id": ws, "engine": "edge", "voice": "zh-CN-XiaoxiaoNeural", "text": "你好,我是小美。",
    })
    assert heard.status_code == 200, heard.text
    assert heard.headers["content-type"] == "audio/mpeg" and heard.content == b"ID3fake"
    [call] = calls
    assert (call["engine"], call["engine_voice"], call["text"]) == ("edge", "zh-CN-XiaoxiaoNeural", "你好,我是小美。")
    assert call["source_type"] == "voice_preview", "念一句也记账"
    assert len(client.get("/api/jobs", params={"workspace_id": ws}).json()) == jobs_before, "试听不建任务"


def test_克隆音色听参考录音_不在这里合成() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    refused = client.post("/api/tts/preview", json={"workspace_id": ws, "engine": "clone", "voice": "v1", "text": "你好"})
    assert refused.status_code == 422
