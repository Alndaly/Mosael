"""插件能注册配音实现(ADR 0032 第四步):和本机克隆、Edge、各家云端并列出现在引擎清单里,音色问插件要(`op: voices`),
点名它就走宿主协议念一句(`op: speak`),产出照样是一段音频。配音没有默认:设置页只列候选,不给默认选择器。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginInstance, User

TTS_PLUGIN = {
    "id": "dev.test.faketts", "manifest_version": 1, "name": "假配音", "version": "1",
    "provides": ["speech"], "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"declare": [{"name": "voice", "provides": ["speech"], "timeout_seconds": 30,
                           "input_schema": {"type": "object", "properties": {"op": {"type": "string"}}}}]},
}
TTS_ENTRY = textwrap.dedent('''
    import json, os, sys, wave
    payload = json.loads(sys.stdin.read())["input"]
    if payload["op"] == "voices":
        print(json.dumps({"ok": True, "output": {"voices": [{"id": "anna", "name": "安娜"}, {"id": "bo", "name": "波"}]}}))
    else:
        assert payload["voice"] == "anna" and payload["text"]
        out = os.path.join(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"], "said.wav")
        with wave.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\\0\\0" * 1600)
        print(json.dumps({"ok": True, "output": {"artifact": {"path": "said.wav"}}}))
''')


def _setup():
    from tests.test_plugins import install

    client = install(TTS_PLUGIN, entry=TTS_ENTRY)
    with SessionLocal() as db:
        for instance in db.query(PluginInstance).filter_by(package_id=TTS_PLUGIN["id"]):
            instance.enabled = True
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        plugin = db.query(PluginInstance).filter_by(package_id=TTS_PLUGIN["id"]).first().id
    ws = client.get("/api/workspaces").json()[0]["id"]
    return client, ws, me, plugin


def test_插件引擎和内置引擎并列_音色问插件要() -> None:
    client, ws, _me, plugin = _setup()
    engines = {row["id"]: row for row in client.get("/api/tts/engines").json()}
    assert "builtin:clone" in engines and "builtin:edge" in engines
    assert engines[plugin]["ready"] is True and engines[plugin]["voices"] == ["anna", "bo"]
    voices = client.get("/api/tts/voices", params={"engine": plugin}).json()
    assert [(one["value"], one["label"]) for one in voices] == [("anna", "安娜"), ("bo", "波")]
    options = client.get("/api/workflows/field-options", params={"workspace_id": ws, "source": "speech_engines"}).json()
    assert plugin in {one["value"] for one in options}


def test_点名插件念一句_走宿主协议交回音频(tmp_path: Path) -> None:
    from app.domain.voices import voices

    _client, ws, me, plugin = _setup()
    with SessionLocal() as db:
        out = voices.speak_to_file(db, text="你好", engine=plugin, engine_voice="anna", speed=1.0, workspace_id=ws,
                                   user_id=me, out_dir=tmp_path, source_type="test", source_id="t")
    assert out.is_file() and out.suffix == ".wav" and out.stat().st_size > 1000


def test_配音任务的产出含AI_导出时认得出是合成人声() -> None:
    """合成的配音不走生成任务,登记时就标上含 AI(《深度合成管理规定》第十七条点名了合成人声)。"""
    from tests.util import wait_status

    client, ws, _me, plugin = _setup()
    job = client.post("/api/tts/synthesize", json={"workspace_id": ws, "text": "你好", "engine": plugin,
                                                   "engine_voice": "anna"}).json()
    assert wait_status(client, job["id"], timeout=30) == "succeeded"
    made = client.get(f"/api/jobs/{job['id']}").json()["result"]["asset_id"]
    asset = client.get(f"/api/assets/{made}").json()
    assert asset["source"] == "tts" and asset["ai_generated"] is True


def test_配音没有默认_设置页只列候选() -> None:
    client, _ws, _me, plugin = _setup()
    speech = next(one for one in client.get("/api/settings/capabilities").json() if one["capability"] == "speech")
    assert speech["defaultable"] is False
    assert {"builtin:clone", "builtin:edge", plugin} <= {one["id"] for one in speech["options"]}
    refused = client.put("/api/settings/capabilities/speech", json={"provider_id": plugin})
    assert refused.status_code == 400 and "没有默认" in refused.json()["detail"]


def test_点名一个不存在的引擎_建任务之前就拒() -> None:
    from app.domain.voices import voices
    from app.domain.voices.speech import SpeechProviderUnavailable

    _client, ws, me, _plugin = _setup()
    with SessionLocal() as db, pytest.raises(SpeechProviderUnavailable):
        voices.start_synthesis(db, text="hi", project_id=None, created_by=me, workspace_id=ws,
                               engine="nope", engine_voice="x")
