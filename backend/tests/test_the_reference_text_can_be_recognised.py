"""参考文本让应用自己听出来 —— 它本来就有转写能力。

现在的处境:Fish Speech 要求参考文本,而用户手里是一段自己录的 7.5 秒音频。让他打一遍
自己说过的话,是把一件应用能做的事推给了人;而 F5 的"自动识别"要先下 1.6 GB 的 Whisper,
更是绕远 —— **这个应用里已经装着转写引擎**,它就是干这个的。

判据:
- 能转就转,填进去;
- 转不了就**明说转不了**(转写引擎没装),而不是留个空文本让合成出去丢人;
- 参考音频不在了就别装作能转。
"""

from __future__ import annotations

import io
import wave

import pytest

from app.domain.voices import service, voices
from tests.util import fresh_client


def _wav(seconds: float = 8) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def _a_voice(client) -> str:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "我的", "reference_text": ""},
        files={"file": ("ref.wav", _wav(), "audio/wav")},
    ).json()["id"]


def test_it_fills_in_what_the_reference_says(monkeypatch) -> None:
    monkeypatch.setattr(service, "resolve_asr_runtime", lambda: ("/usr/bin/python3", "funasr"))
    monkeypatch.setattr(
        service, "run_asr",
        lambda wav, python, provider: {"segments": [{"start": 0, "end": 3, "text": "今天是个"},
                                                    {"start": 3, "end": 7, "text": "好天气"}]},
    )
    client = fresh_client()
    voice_id = _a_voice(client)

    resp = client.post(f"/api/voices/{voice_id}/recognize-reference")

    assert resp.status_code == 200, resp.text
    assert resp.json()["reference_text"] == "今天是个好天气"


def test_it_says_so_when_transcription_is_not_installed(monkeypatch) -> None:
    """转不了就明说 —— 别留个空文本让合成出去丢人。"""
    def no_runtime():
        raise service.AsrError("缺的是运行环境,不是模型")

    monkeypatch.setattr(service, "resolve_asr_runtime", no_runtime)
    client = fresh_client()
    voice_id = _a_voice(client)

    resp = client.post(f"/api/voices/{voice_id}/recognize-reference")

    assert resp.status_code == 422, resp.text
    assert "运行环境" in resp.json()["detail"]


def test_an_empty_result_is_not_written(monkeypatch) -> None:
    """识别出一片空白时别把空文本写回去 —— 那和没识别一样,却看起来像成功了。"""
    monkeypatch.setattr(service, "resolve_asr_runtime", lambda: ("/usr/bin/python3", "funasr"))
    monkeypatch.setattr(service, "run_asr", lambda wav, python, provider: {"segments": []})
    client = fresh_client()
    voice_id = _a_voice(client)

    resp = client.post(f"/api/voices/{voice_id}/recognize-reference")

    assert resp.status_code == 422, resp.text
    assert "没听出" in resp.json()["detail"] or "空" in resp.json()["detail"]


def test_a_missing_reference_is_refused() -> None:
    from app.core.db import SessionLocal
    from app.db.models import Voice

    client = fresh_client()
    voice_id = _a_voice(client)
    with SessionLocal() as db:
        db.get(Voice, voice_id).reference_key = "nope/missing.wav"
        db.commit()

    resp = client.post(f"/api/voices/{voice_id}/recognize-reference")

    assert resp.status_code == 422, resp.text


def test_the_recognised_text_actually_unblocks_fish(monkeypatch) -> None:
    """识别完就该能合成了 —— 这条把功能和它存在的理由连起来。"""
    from app.ai.runtime import tts_models
    from app.core.db import SessionLocal

    monkeypatch.setattr(service, "resolve_asr_runtime", lambda: ("/usr/bin/python3", "funasr"))
    monkeypatch.setattr(service, "run_asr", lambda wav, python, provider: {"segments": [{"text": "今天是个好天气"}]})
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)

    client = fresh_client()
    voice_id = _a_voice(client)
    client.post(f"/api/voices/{voice_id}/recognize-reference")

    with SessionLocal() as db:
        job = voices.start_synthesis(db, text="你好", project_id=None, created_by=None,
                                     voice_id=voice_id, clone_engine="fish-speech")
    assert job.kind == "tts"
