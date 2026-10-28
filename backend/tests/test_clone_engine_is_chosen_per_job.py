"""合成时用哪个本地引擎,是**这一次**的选择;权重没下好就不许开工。

用户两句话:

  「设置页面只是默认的克隆引擎,这里应该支持手动选择引擎覆盖」
  「模型没下载的时候也应该不能生成,而不是自动开启下载」

前一句:`tts_config.engine` 是部署上的**默认**,而配音面板每次生成都可能想换一个(F5 快、
Fish 支持情感标签)。此前那里没有任何入口,想换只能跑去设置页改全局。

后一句更要紧。此前只挡"有没有解释器能 import 引擎",不挡"权重在不在盘上" —— 于是权重缺席时
任务照建,worker 在首次合成里**顺手下 2GB**:界面上是一个看不出在干嘛的任务,卡在那儿几十分钟,
网络不好时还会失败。下载是用户在设置页按「下载」时明确要做的事,不该由一次"生成配音"顺带触发。

判据:**能不能出声**由两件事共同决定 —— 解释器 + 权重。两者缺一,就在建任务之前说清缺的是哪一个。
"""

from __future__ import annotations

import io
import wave

import pytest

from app.ai.runtime import tts_models
from app.domain.voices import voices
from app.domain.voices import errors
from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.voices.voice_ref import VoiceRef
from tests.util import fresh_client, synthesize_cloned


#: 8 秒:够得着参考音频的下限(见 voices.REFERENCE_MIN_SECONDS)。此前这里是 1 秒,
#: 而那正是用户那条 2.6 秒音色的同类 —— 测试用的夹具比真实要求还宽,下限就测不出来。
def _tiny_wav(seconds: int = 8) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * seconds)
    return buf.getvalue()


def _a_voice(client) -> str:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "小明", "reference_text": "你好", "consent_kind": "self"},
        files={"file": ("ref.wav", _tiny_wav(), "audio/wav")},
    ).json()["id"]


def _runtime_ok(monkeypatch) -> None:
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")


def test_missing_weights_refuse_instead_of_starting_a_download(monkeypatch) -> None:
    """解释器在、权重不在 —— 不建任务,并且说清缺的是权重。"""
    _runtime_ok(monkeypatch)
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: False)
    client = fresh_client()
    voice_id = _a_voice(client)

    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(errors.VoiceError) as caught:
            voices.start_synthesis(db, text="念一句", project_id=None, created_by=None, voice=VoiceRef("builtin:clone", cloned_voice=voice_id))
        assert db.query(Job).count() == before, "起了一个会顺手下 2GB 的任务"

    message = str(caught.value)
    assert "权重" in message or "模型" in message, message
    assert "运行环境" not in message, f"缺的是权重却说成缺运行环境:{message}"


def test_both_present_goes_through(monkeypatch) -> None:
    _runtime_ok(monkeypatch)
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    client = fresh_client()
    voice_id = _a_voice(client)

    with SessionLocal() as db:
        job = voices.start_synthesis(db, text="念一句", project_id=None, created_by=None, voice=VoiceRef("builtin:clone", cloned_voice=voice_id))
        assert job.kind == "tts"


def test_the_request_can_override_the_configured_engine(monkeypatch) -> None:
    """设置页是默认,这一次用哪个由这一次说了算。"""
    asked: list[str] = []
    _runtime_ok(monkeypatch)
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: asked.append(engine_id) or True)
    client = fresh_client()
    voice_id = _a_voice(client)

    with SessionLocal() as db:
        job = voices.start_synthesis(
            db, text="念一句", project_id=None, created_by=None, voice=VoiceRef("builtin:clone", cloned_voice=voice_id, model="fish-speech")
        )

    assert "fish-speech" in asked, f"挡的还是设置页那个引擎:{asked}"
    assert job.payload["voice"].get("model") == "fish-speech", "选的引擎没跟着任务走"


def test_an_unknown_engine_is_refused(monkeypatch) -> None:
    """覆盖来自请求体 —— 不认识的名字当场拒绝,别带着它一路跑到 worker。"""
    _runtime_ok(monkeypatch)
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    client = fresh_client()
    voice_id = _a_voice(client)

    with SessionLocal() as db:
        with pytest.raises(errors.VoiceError):
            voices.start_synthesis(
                db, text="念一句", project_id=None, created_by=None, voice=VoiceRef("builtin:clone", cloned_voice=voice_id, model="不存在的引擎")
            )


def test_the_api_passes_the_choice_through(monkeypatch) -> None:
    _runtime_ok(monkeypatch)
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    client = fresh_client()
    voice_id = _a_voice(client)

    resp = synthesize_cloned(client, voice_id, "念一句", model="fish-speech")

    assert resp.status_code == 200, resp.text
    with SessionLocal() as db:
        job = db.get(Job, resp.json()["id"])
        assert job.payload["voice"].get("model") == "fish-speech"


def test_qwen_is_not_a_cloning_engine(monkeypatch) -> None:
    """Qwen3-TTS 在本机引擎清单里,但它只念预置音色,是另一个念字引擎(`builtin:qwentts`)。克隆那条路的 `model`
    写成 `qwen-tts`(界面的克隆引擎下拉曾经把它也列了出来)要当场说清,不能拿配音库的嗓子去喂它。"""
    _runtime_ok(monkeypatch)
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    client = fresh_client()
    voice_id = _a_voice(client)

    assert [engine.id for engine in tts_models.CATALOG if engine.clones_voices] == ["f5-tts", "fish-speech"]
    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(errors.VoiceError, match="qwen-tts"):
            voices.start_synthesis(db, text="念一句", project_id=None, created_by=None,
                                   voice=VoiceRef("builtin:clone", cloned_voice=voice_id, model="qwen-tts"))
        assert db.query(Job).count() == before
    status = {row["id"]: row["clones_voices"] for row in client.get("/api/tts/models").json()}
    assert status == {"f5-tts": True, "fish-speech": True, "qwen-tts": False}, "界面靠这一格决定克隆引擎下拉里列谁"
