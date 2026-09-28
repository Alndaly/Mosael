"""插件能注册转写实现(ADR 0032 第三步):能力表里和本机 FunASR / WhisperX 并列,节点下拉里出现,点名它就走宿主协议
(一份 16k wav 进、带时间的分段出)。素材转写、听写走同一个 transcriber;交回的分段形状不对当场说清。"""

from __future__ import annotations

import subprocess
import textwrap

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import PluginInstance, User

ASR_PLUGIN = {
    "id": "dev.test.fakeasr", "manifest_version": 1, "name": "假转写", "version": "1",
    "provides": ["transcription"], "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"declare": [{"name": "hear", "provides": ["transcription"], "stream": True, "timeout_seconds": 60}]},
}
ASR_ENTRY = textwrap.dedent('''
    import json, os, sys
    request = json.loads(sys.stdin.read())
    payload = request["input"]
    assert os.path.isfile(payload["file"]) and payload["file"].endswith(".wav")
    if payload["language"] == "bad":
        print(json.dumps({"ok": True, "output": {"segments": "不是列表"}}))
    else:
        print(json.dumps({"ok": True, "output": {"language": payload["language"] or "zh", "segments": [
            {"start": 0.0, "end": 0.4, "text": "你好", "speaker": "A",
             "words": [{"start": 0.0, "end": 0.2, "word": "你"}, {"start": 0.2, "end": 0.4, "word": "好"}]},
            {"start": 0.4, "end": 0.9, "text": "世界"},
        ]}}))
''')


def _setup(tmp_path):
    from tests.test_plugins import install

    client = install(ASR_PLUGIN, entry=ASR_ENTRY)
    with SessionLocal() as db:
        for instance in db.query(PluginInstance).filter_by(package_id=ASR_PLUGIN["id"]):
            instance.enabled = True
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        plugin = db.query(PluginInstance).filter_by(package_id=ASR_PLUGIN["id"]).first().id
    ws = client.get("/api/workspaces").json()[0]["id"]
    wav = tmp_path / "talk.wav"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(wav)],
                   check=True, capture_output=True)
    return client, ws, me, plugin, wav


def test_转写插件和本机引擎并列出现在节点下拉和设置里(tmp_path) -> None:
    client, ws, _me, plugin, _wav = _setup(tmp_path)
    options = client.get("/api/workflows/field-options", params={"workspace_id": ws, "source": "providers.transcription"}).json()
    #: 下拉只列此刻跑得起来的:测试机没装本机引擎的运行环境,所以只有插件。
    assert plugin in {one["value"] for one in options}
    listed = next(one for one in client.get("/api/settings/capabilities").json() if one["capability"] == "transcription")
    #: 设置页全列,各自说缺什么。
    assert {"builtin:funasr", "builtin:whisperx", plugin} <= {one["id"] for one in listed["options"]}
    assert {use["kind"] for use in listed["used_by"]} >= {"app", "workflow"}


def test_点名插件_走宿主协议交回分段_词级时间和说话人都在(tmp_path) -> None:
    from app.domain.voices import transcription

    _client, _ws, me, plugin, wav = _setup(tmp_path)
    with SessionLocal() as db:
        chosen = transcription.transcriber(db, me, plugin)
    heard = chosen.transcribe(wav, "zh")
    segments = transcription.parse_transcript_segments(heard["segments"])
    assert heard["language"] == "zh" and [one.text for one in segments] == ["你好", "世界"]
    assert segments[0].speaker == "A" and [token.text for token in segments[0].tokens] == ["你", "好"]


def test_听写也能用插件_拼成一句话(tmp_path) -> None:
    from app.domain.voices import transcription

    _client, _ws, me, plugin, wav = _setup(tmp_path)
    assert transcription.transcribe_clip(wav, owner_user_id=me, engine=plugin) == "你好世界"


def test_交回的形状不对_当场说清是哪一家(tmp_path) -> None:
    from app.domain.voices import transcription

    _client, _ws, me, plugin, wav = _setup(tmp_path)
    with SessionLocal() as db:
        chosen = transcription.transcriber(db, me, plugin)
    with pytest.raises(transcription.ASRError) as raised:
        chosen.transcribe(wav, "bad")
    assert raised.value.key in {"asrErr_pluginBadOutput", "asrErr_pluginFailed"}
    assert "假转写" in str(raised.value)
