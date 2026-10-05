"""连接的出错原因**按看的人的语言说**,不按刷新那一刻的语言存死。

插件页连接卡片上的出错原因(`capability_status` 里各项能力上一次没做成的原因)是刷新时记下的:刷新可能是中文界面
点的,也可能是后台(启动时、目录变了)刷的 —— 后台没有请求,用的是缺省语言。此前插件自己说的那句(ComfyUI 的
「连不上这台 ComfyUI……」)按刷新时的语言说好、原样存进 `pluginErr_upstream` 的 `detail`,于是中文界面刷新过的
连接切到英文界面仍是中文,反过来也一样。

现在插件把失败原因按语言分着交(`{"zh": …, "en": …}`,和清单里给人看的文字同一种写法),宿主原样存着、给人看时
再挑;库里已经存成死文字的,迁移能认回文案 key 的认回,认不回的清掉,等下次刷新重新生成。
"""

from __future__ import annotations

import json
import socket

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.core.i18n import render_message
from app.db.migrations import _migrate_plugin_connection_errors_follow_the_reader
from app.domain.jobs import blame
from app.domain.plugins.runtime import PluginRuntimeError, _final_response
from tests.fake_comfyui import comfyui_grants
from tests.util import fresh_client

PACKAGE = "dev.mosael.comfyui"
ZH = {"Accept-Language": "zh-CN"}
EN = {"Accept-Language": "en-US"}


def _closed_port_url() -> str:
    """一个此刻没人听的本机端口:连上去必然被拒。"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _status(client, headers) -> dict:
    package = next(one for one in client.get("/api/plugins", headers=headers).json() if one["id"] == PACKAGE)
    return package["instances"][0]["capability_status"]


def test_同一个出错状态_中英文各读一次_各是各的语言() -> None:
    client = fresh_client()
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": _closed_port_url()}}, headers=ZH)
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()}, headers=ZH)
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}, headers=ZH)
    #: 中文界面下点了一次「刷新」:模型目录、工具清单都没拉到。
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh", headers=ZH).status_code == 200

    zh, en = _status(client, ZH), _status(client, EN)
    for capability in ("generation", "tools"):
        assert zh[capability]["error"].startswith("连不上这台 ComfyUI"), zh[capability]
        assert en[capability]["error"].startswith("Can't reach this ComfyUI"), en[capability]
        #: 第二行是原文(地址、errno):两种语言下都在,界面收进悬停说明。
        assert "127.0.0.1" in zh[capability]["error"].splitlines()[1]
        assert "127.0.0.1" in en[capability]["error"].splitlines()[1]


def test_插件按语言分着交的失败原因_落库后按读的人挑() -> None:
    with pytest.raises(PluginRuntimeError) as caught:
        _final_response({"ok": False, "error": {"zh": "连不上\n原文", "en": "Can't reach\nraw"}})
    #: 落库走 JSON 列:来回一趟之后还认得出是按语言分的那句。
    stored = json.loads(json.dumps(blame(caught.value)))
    assert render_message(stored["error_key"], "zh", stored["error_params"]) == "连不上\n原文"
    assert render_message(stored["error_key"], "en", stored["error_params"]) == "Can't reach\nraw"


def test_只给一个字符串的插件_照旧原样显示() -> None:
    with pytest.raises(PluginRuntimeError) as caught:
        _final_response({"ok": False, "error": "quota exceeded"})
    stored = json.loads(json.dumps(blame(caught.value)))
    assert render_message(stored["error_key"], "en", stored["error_params"]) == "quota exceeded"
    with pytest.raises(PluginRuntimeError) as empty:
        _final_response({"ok": False, "error": {"zh": "  ", "en": ""}})
    assert empty.value.key == "pluginErr_failedNoReason", "按语言分的对象里一句话都没有 = 没说原因"


# --- 迁移 -----------------------------------------------------------------

def _instance_with(status: dict) -> str:
    client = fresh_client()
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": _closed_port_url()}})
    instance_id = created.json()["id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE plugin_instances SET capability_status = :status WHERE id = :id"),
                     {"status": json.dumps(status, ensure_ascii=False), "id": instance_id})
    return instance_id


def _stored(instance_id: str) -> dict:
    with engine.begin() as conn:
        raw = conn.execute(text("SELECT capability_status FROM plugin_instances WHERE id = :id"), {"id": instance_id}).scalar_one()
    return json.loads(raw) if isinstance(raw, str) else raw


def test_迁移_插件说的死文字认不回_清掉_别的不动() -> None:
    frozen = "连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://127.0.0.1:8188:[Errno 61] Connection refused"
    instance_id = _instance_with({
        "generation": {"models": 3, "refreshed_at": "2026-10-01T00:00:00+00:00", "fingerprint": "abc",
                       "error": frozen, "error_key": "pluginErr_upstream", "error_params": {"detail": frozen},
                       "attempted_at": "2026-10-05T00:00:00+00:00"},
    })

    _migrate_plugin_connection_errors_follow_the_reader()

    generation = _stored(instance_id)["generation"]
    assert (generation["error"], generation["error_key"], generation["error_params"]) == ("", "", {})
    assert (generation["models"], generation["refreshed_at"], generation["fingerprint"]) == (3, "2026-10-01T00:00:00+00:00", "abc"), \
        "上一次成功的记录留着:模型清单本身也还是那一份"


def test_迁移_只存了一句话的旧记录_认得回文案的改成文案_认不回的清掉() -> None:
    said = render_message("pluginErr_toolsBadShape", "zh", {"name": "ComfyUI · 本机", "shape": '{"tools": [...]}'})
    instance_id = _instance_with({
        "tools": {"tools": 0, "error": said, "error_key": "", "error_params": {}},
        "generation": {"error": "boom: something odd", "error_key": "", "error_params": {}},
    })

    _migrate_plugin_connection_errors_follow_the_reader()

    stored = _stored(instance_id)
    tools = stored["tools"]
    assert tools["error_key"] == "pluginErr_toolsBadShape"
    assert render_message(tools["error_key"], "en", tools["error_params"]) == \
        "“ComfyUI · 本机” returned a tool list in the wrong shape; it should be {\"tools\": [...]}."
    assert (stored["generation"]["error"], stored["generation"]["error_key"]) == ("", "")


def test_迁移_已经是文案_key_加参数的不动_再跑一次什么都不做() -> None:
    structured = {"tools": {"tools": 2, "error": "x", "error_key": "pluginErr_timeout", "error_params": {"seconds": "60"}}}
    instance_id = _instance_with(structured)

    _migrate_plugin_connection_errors_follow_the_reader()
    assert _stored(instance_id) == structured

    bilingual = {"generation": {"error": "x", "error_key": "pluginErr_upstream",
                                "error_params": {"detail": {"__text": {"zh": "连不上", "en": "Can't reach"}}}}}
    instance_id = _instance_with(bilingual)
    _migrate_plugin_connection_errors_follow_the_reader()
    _migrate_plugin_connection_errors_follow_the_reader()
    assert _stored(instance_id) == bilingual, "按语言分着存的就是新形状"
