"""「留空则自动识别」这句话,只有 F5 兑现。

用户的音色《我的》参考音频 7.5 秒(合格),但 `reference_text` 是空的 —— 因为上传表单写着
「参考文本(该段音频说的话,**留空则自动识别**)」。

而这句承诺按引擎分裂:

    F5-TTS       ref_text="" → 它自己转写参考音频(api 里就是这么写的)
    Fish Speech  我们用 mode="tts" 构造 ModelManager,**不带 ASR** —— 空文本就是空文本

我们自己的代码注释早就写着 `a wrong/empty one garbles output`。于是又是同一个形状:
**一句写下来但只在一半情况下成立的承诺**,而界面把它当成普遍真理讲给了用户。

判据:要么这个引擎真的能自动识别,要么就别承诺。Fish Speech 这条路上,参考文本是必需的 ——
在建任务之前说,而不是等一次十分钟的合成之后交一段听不懂的东西。
"""

from __future__ import annotations

import io
import wave

import pytest

from app.audio import tts_models, voices
from tests.util import fresh_client


def _wav(seconds: float = 8) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def _voice_without_text(client) -> str:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "我的", "reference_text": ""},
        files={"file": ("ref.wav", _wav(), "audio/wav")},
    ).json()["id"]


def test_fish_refuses_an_empty_reference_text(monkeypatch) -> None:
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    from app.core.db import SessionLocal
    from app.db.models import Job

    client = fresh_client()
    voice_id = _voice_without_text(client)

    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(voices.VoiceError) as caught:
            voices.start_synthesis(db, text="你好", project_id=None, created_by=None,
                                   voice_id=voice_id, clone_engine="fish-speech")
        assert db.query(Job).count() == before, "起了一个注定说不清话的十分钟任务"

    message = str(caught.value)
    assert "参考文本" in message, message


def test_f5_still_accepts_an_empty_reference_text(monkeypatch) -> None:
    """F5 真的会自己转写 —— 对它承诺是成立的,别一起挡掉。"""
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    from app.core.db import SessionLocal

    client = fresh_client()
    voice_id = _voice_without_text(client)

    with SessionLocal() as db:
        job = voices.start_synthesis(db, text="你好", project_id=None, created_by=None,
                                     voice_id=voice_id, clone_engine="f5-tts")
    assert job.kind == "tts"


def test_the_engines_that_need_it_are_declared_not_hardcoded_at_the_callsite() -> None:
    """哪个引擎需要参考文本,是引擎的属性 —— 写在目录里,而不是散在判断里。"""
    assert "fish-speech" in voices.ENGINES_NEEDING_REFERENCE_TEXT
    assert "f5-tts" not in voices.ENGINES_NEEDING_REFERENCE_TEXT
