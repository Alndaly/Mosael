"""插件能在降噪、分离人声上注册实现(ADR 0032 第二步):能力表里和本机引擎并列,节点下拉里出现,点名它就走
宿主协议(一段音频进、处理好的文件出),产出照样登记成新素材、记着出处。"""

from __future__ import annotations

import subprocess
import textwrap

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, PluginInstance, User

AUDIO_PLUGIN = {
    "id": "dev.test.fakeaudio", "manifest_version": 1, "name": "假音频", "version": "1",
    "provides": ["audio_denoise", "audio_separation"], "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"declare": [
        {"name": "clean", "provides": ["audio_denoise"], "stream": True, "timeout_seconds": 60},
        {"name": "split", "provides": ["audio_separation"], "stream": True, "timeout_seconds": 60},
    ]},
}
AUDIO_ENTRY = textwrap.dedent('''
    import json, os, shutil, sys
    request = json.loads(sys.stdin.read())
    payload = request["input"]
    out = os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]
    assert os.path.isfile(payload["file"])
    if request["tool"] == "clean":
        assert payload["strength"] in ("light", "medium", "strong")
        shutil.copyfile(payload["file"], os.path.join(out, "clean.wav"))
        print(json.dumps({"ok": True, "output": {"audio": "clean.wav"}}))
    else:
        shutil.copyfile(payload["file"], os.path.join(out, "v.wav"))
        shutil.copyfile(payload["file"], os.path.join(out, "b.wav"))
        print(json.dumps({"ok": True, "output": {"vocals": "v.wav", "background": "b.wav"}}))
''')


def _setup(tmp_path):
    from tests.test_plugins import install

    client = install(AUDIO_PLUGIN, entry=AUDIO_ENTRY)
    with SessionLocal() as db:
        for instance in db.query(PluginInstance).filter_by(package_id=AUDIO_PLUGIN["id"]):
            instance.enabled = True
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        plugin = db.query(PluginInstance).filter_by(package_id=AUDIO_PLUGIN["id"]).first().id
    ws = client.get("/api/workspaces").json()[0]["id"]
    wav = tmp_path / "talk.wav"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(wav)],
                   check=True, capture_output=True)
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("talk.wav", wav.read_bytes(), "audio/wav")}).json()
    return client, ws, me, plugin, made["id"]


def test_降噪插件和本机引擎并列_点名它就走插件_产出记着是谁降的(tmp_path) -> None:
    from app.domain.denoise import denoise_asset

    client, ws, me, plugin, asset_id = _setup(tmp_path)
    options = client.get("/api/workflows/field-options", params={"workspace_id": ws, "source": "providers.audio_denoise"}).json()
    assert "builtin:ffmpeg" in {one["value"] for one in options} and plugin in {one["value"] for one in options}
    engines = {row["engine"]: row for row in client.get("/api/denoise/engines").json()}
    assert engines[plugin]["label"] == "假音频" and engines[plugin]["ready"] is True

    with SessionLocal() as db:
        made, used = denoise_asset(db, db.get(Asset, asset_id), engine=plugin, strength="light", owner_user_id=me)
        assert used == plugin and made.media_info["denoise_engine"] == plugin
        assert made.media_info["derived_from_asset_id"] == asset_id


def test_分离插件_点名它拆出两份新素材(tmp_path) -> None:
    from app.domain.separation import separate_asset

    _client, _ws, me, plugin, asset_id = _setup(tmp_path)
    with SessionLocal() as db:
        result = separate_asset(db, db.get(Asset, asset_id), engine=plugin, owner_user_id=me)
        assert result.engine == plugin
        assert {result.vocals.media_info["stem"], result.background.media_info["stem"]} == {"vocals", "background"}


def test_别人的插件连接点不到_不借用别人的密钥(tmp_path) -> None:
    import pytest

    from app.domain.audio_capabilities import DenoiseProviderUnavailable
    from app.domain.denoise import ready_adapter

    _client, _ws, _me, plugin, _asset = _setup(tmp_path)
    with SessionLocal() as db, pytest.raises(DenoiseProviderUnavailable):
        ready_adapter(db, "someone-else", plugin)
