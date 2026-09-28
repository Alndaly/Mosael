"""插件能注册翻译实现(ADR 0032 第三步):和 Google 免费翻译、对话模型并列,节点下拉、字幕翻译接口都能点名它;
协议是一批句子进、同样条数的译文出,条数对不上整批作废 —— 不把错位的译文写进字幕轨。"""

from __future__ import annotations

import textwrap

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginInstance, User

MT_PLUGIN = {
    "id": "dev.test.fakemt", "manifest_version": 1, "name": "假翻译", "version": "1",
    "provides": ["translation"], "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"declare": [{"name": "render", "provides": ["translation"], "timeout_seconds": 30}]},
}
MT_ENTRY = textwrap.dedent('''
    import json, sys
    payload = json.loads(sys.stdin.read())["input"]
    texts = payload["texts"]
    if texts == ["少一条", "吧"]:
        texts = texts[:1]
    print(json.dumps({"ok": True, "output": {"texts": [f"[{payload['target']}]{one}" for one in texts]}}))
''')


def _setup():
    from tests.test_plugins import install

    client = install(MT_PLUGIN, entry=MT_ENTRY)
    with SessionLocal() as db:
        for instance in db.query(PluginInstance).filter_by(package_id=MT_PLUGIN["id"]):
            instance.enabled = True
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        plugin = db.query(PluginInstance).filter_by(package_id=MT_PLUGIN["id"]).first().id
    ws = client.get("/api/workspaces").json()[0]["id"]
    return client, ws, me, plugin


def test_翻译插件和内置两家并列_节点下拉里都在() -> None:
    client, ws, _me, plugin = _setup()
    options = client.get("/api/workflows/field-options", params={"workspace_id": ws, "source": "providers.translation"}).json()
    assert {"builtin:google", "builtin:chat", plugin} <= {one["value"] for one in options}


def test_字幕翻译接口点名插件_空串占位_顺序对齐() -> None:
    client, ws, _me, plugin = _setup()
    res = client.post("/api/translate", json={"workspace_id": ws, "texts": ["你好", "", "世界"], "target_lang": "en",
                                              "engine": plugin})
    assert res.status_code == 200, res.text
    assert res.json()["translations"] == ["[en]你好", "", "[en]世界"]


def test_条数对不上_整批作废_说清是哪一家() -> None:
    from app.domain.translate import TranslateError, translate_many

    _client, _ws, me, plugin = _setup()
    with SessionLocal() as db, pytest.raises(TranslateError) as raised:
        translate_many(db, ["少一条", "吧"], "en", user_id=me, engine=plugin)
    assert "假翻译" in str(raised.value)


def test_点名一家不存在的_直说() -> None:
    client, ws, _me, _plugin = _setup()
    res = client.post("/api/translate", json={"workspace_id": ws, "texts": ["hi"], "target_lang": "en", "engine": "nope"})
    assert res.status_code >= 400 and "nope" in res.json()["detail"]
