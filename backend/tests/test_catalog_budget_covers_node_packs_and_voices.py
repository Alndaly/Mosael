"""`node_packs` / `voices` 也是**目录类回答**:和 `tools` / `models` / `library` / `workflows` 同一条风险。

## 现场(同一类缺口,前面几笔只覆盖了四处)

- `{"op": "node_packs"}`:这台机器装了**所有**节点包,每个最多 60 个节点类型 —— 随装包数线性变大。
  调用点在 `workbench_agent.node_packs`(智能体的 `comfy_node_packs`),此前走的是普通工具那 1MB。
- `{"op": "voices"}`:TTS 插件的音色清单 —— 随引擎 / 账号里的音色线性变大。调用点在
  `voices.engine_catalog._plugin_voices`,此前同样走 1MB;超了以后它把异常吞成空清单,音色下拉**静默变空**。

## 钉的是什么

- 假环境(本机随机端口,不连外网)量出真实字节数:两份都超过旧的 1MB;
- 改之前宿主整份不收(`node_packs` 工具回 `{"error": …}` / 音色清单变成空),改之后整份读出;
- 两处给的是**同一个** `runtime.CATALOG_OUTPUT_BYTES`,不另造常量(预算改小,两处一起跟着改);
- 别的 op 一个字节不放宽(见 test_comfyui_remote_catalog_fits_the_output_limit.py 的 1MB 回归)。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginPackage, User
from app.domain import browser
from app.domain.plugins import runtime
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
COMFY_PACKAGE = "dev.mosael.comfyui"

#: 一台「节点包很多」的机器:1600 个包、每个 60 个节点类型(插件侧的上限 MAX_TYPES),回答约 2.4 MB。
PACKS = 1_600
TYPES_PER_PACK = 60

#: 一个只认领 `speech` 的插件:20,000 个音色,`op: voices` 的回答约 1.4 MB。
SPEECH_PACKAGE = "test.speech-catalog"
VOICES = 20_000
SPEECH_PLUGIN = r'''
import json, sys

request = json.loads(sys.stdin.read())
op = request["input"].get("op")
if op == "voices":
    voices = [{"id": f"voice-{index:05d}", "name": f"Voice {index:05d} — catalogue entry"} for index in range(%d)]
    print(json.dumps({"ok": True, "output": {"voices": voices}}, ensure_ascii=False), flush=True)
else:
    print(json.dumps({"ok": False, "error": f"unknown op {op}"}), flush=True)
''' % VOICES


def _plugin_stdout(plugin_dir: Path, entry: str, request: dict[str, Any], server_url: str = "") -> str:
    """直接问插件进程一句,拿它写在 stdout 上的那一份 —— 1MB / 8MB 那两条线量的就是这里。"""
    done = subprocess.run(
        [sys.executable, str(plugin_dir / entry)], input=json.dumps(request), capture_output=True, text=True,
        cwd=str(plugin_dir),
        env={**os.environ, "SERVER_URL": server_url, "PYTHONUTF8": "1", "MOSAEL_PLUGIN": "1"},
        timeout=300, check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return done.stdout


@pytest.fixture
def many_packs():
    """一台装了 1600 个节点包的远端 ComfyUI(本机随机端口;不连外网)。"""
    with FakeComfyUI() as server:
        state = server.state
        state.manager = "V4.2.1"
        installed: dict[str, Any] = {}
        mappings: dict[str, Any] = {}
        for index in range(PACKS):
            name = f"comfyui-pack-{index:04d}"
            installed[name] = {
                "ver": f"1.{index % 20}.0", "cnr_id": name,
                "aux_id": f"author/ComfyUI-Pack-{index:04d}",
                "enabled": index % 7 != 0,
            }
            mappings[name] = [
                [f"CustomNodeType_{index:04d}_{number:02d}" for number in range(TYPES_PER_PACK)],
                {"title_aux": f"Node Pack {index:04d} — a title long enough to take real bytes"},
            ]
        state.manager_installed = installed
        state.manager_mappings = mappings
        yield server


def _connect_comfy(client, url: str) -> str:
    created = client.post(f"/api/plugins/{COMFY_PACKAGE}/instances", json={"config": {"server_url": url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


@pytest.fixture
def connected(many_packs, monkeypatch):
    """登录过的 client + 工作区 + 那个连接;画布按「工作台没开着」算(节点包这一问不碰画布)。"""
    monkeypatch.setattr(browser, "executor_online", lambda: False)
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    instance_id = _connect_comfy(client, many_packs.url)
    yield client, many_packs, instance_id, workspace


def _tool(client, tool: str, workspace: str, **arguments: Any) -> Any:
    answer = client.post(f"/api/agent/tools/{tool}?workspace_id={workspace}", json={"arguments": arguments})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_装了很多节点包的那台_节点包列得出来(connected) -> None:
    """`op: node_packs` 随装包数线性变大 —— 旧的 1MB 收不下,目录预算收得下,而且每个包都列全。"""
    client, comfy, instance_id, workspace = connected
    asked = {"tool": "comfyui_generation", "input": {"op": "node_packs"}, "locale": "zh", "accepts": ["shared_tables"]}
    sent = _plugin_stdout(PLUGIN, ENTRY, asked, comfy.url)
    characters, size = len(sent), len(sent.encode())
    print(f"op node_packs: chars={characters:,} bytes={size:,} "
          f"(1MB={runtime.MAX_OUTPUT_BYTES:,}, catalog={runtime.CATALOG_OUTPUT_BYTES:,})")
    # 旧上限确实收不下:改之前宿主这一问就是 pluginErr_outputTooLarge。
    assert size > runtime.MAX_OUTPUT_BYTES, "假 ComfyUI 的节点包不够多,这条什么都没量到"
    assert size <= runtime.CATALOG_OUTPUT_BYTES, "目录预算收不下这台机器,得看要不要把它提上去"

    answer = _tool(client, "comfy_node_packs", workspace, instance_id=instance_id)
    assert "result" in answer, f"节点包没列出来:{answer.get('error')}"
    packs = answer["result"]["packs"]
    assert len(packs) == PACKS, "装的包没列全"
    assert sum(one["node_count"] for one in packs) == PACKS * TYPES_PER_PACK, "节点类型没列全"
    assert all(len(one["node_types"]) == TYPES_PER_PACK for one in packs)
    assert answer["result"]["manager"] is True


def test_节点包那一问用的是同一份目录预算(connected, monkeypatch) -> None:
    """预算就是 `runtime.CATALOG_OUTPUT_BYTES`:把它改小,这一问立刻按新的上限说「收不下」,不是另一条线。"""
    client, _comfy, instance_id, workspace = connected
    monkeypatch.setattr(runtime, "CATALOG_OUTPUT_BYTES", 1_000)
    answer = _tool(client, "comfy_node_packs", workspace, instance_id=instance_id)
    assert "result" not in answer
    assert "comfyui_generation · node_packs" in answer["error"], answer["error"]
    assert "1 KB" in answer["error"], f"没说清上限用的是目录预算:{answer['error']}"


@pytest.fixture
def speech_catalog(tmp_path: Path):
    """一个只认领 `speech` 的插件:它的 `voices` 回答不自己削(20,000 个音色)。"""
    client = fresh_client()
    plugin = tmp_path / "speech"
    plugin.mkdir()
    (plugin / "main.py").write_text(textwrap.dedent(SPEECH_PLUGIN), encoding="utf-8")
    manifest = {
        "id": SPEECH_PACKAGE,
        "name": "测试配音",
        "version": "1.0.0",
        "manifest_version": 1,
        "runtime": {"kind": "process", "entry": "main.py"},
        "provides": ["speech"],
        "instance": {"multiple": False, "name_template": "测试配音"},
        "tools": {"declare": [{"name": "voices", "provides": ["speech"], "timeout_seconds": 60,
                               "input_schema": {"type": "object", "properties": {"op": {"type": "string"}}}}]},
        "_path": str(plugin),
    }
    with SessionLocal() as db:
        db.add(PluginPackage(id=SPEECH_PACKAGE, name="测试配音", version="1.0.0", manifest=manifest))
        db.commit()
    created = client.post(f"/api/plugins/{SPEECH_PACKAGE}/instances", json={"config": {}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    yield client, plugin, instance_id


def test_装了很多音色的那个配音插件_音色列得出来(speech_catalog) -> None:
    """`op: voices` 随音色数线性变大 —— 旧 1MB 下 `_plugin_voices` 把异常吞成空清单(音色下拉静默空);
    目录预算下整份交回。"""
    client, plugin, instance_id = speech_catalog
    sent = _plugin_stdout(plugin, "main.py", {"tool": "voices", "input": {"op": "voices"}, "locale": "zh"})
    size = len(sent.encode())
    print(f"op voices: chars={len(sent):,} bytes={size:,} "
          f"(1MB={runtime.MAX_OUTPUT_BYTES:,}, catalog={runtime.CATALOG_OUTPUT_BYTES:,})")
    assert size > runtime.MAX_OUTPUT_BYTES, "假配音插件的音色不够多,这条什么都没量到"
    assert size <= runtime.CATALOG_OUTPUT_BYTES

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        from app.domain.voices import engine_catalog

        listed = engine_catalog.list_engine_voices(db, instance_id, user_id=user.id)
    assert len(listed) == VOICES, "音色没列全(空清单 = 旧 1MB 下被吞掉的那一次)"
    assert listed[0] == {"value": "voice-00000", "label": "Voice 00000 — catalogue entry"}
    assert listed[-1]["value"] == f"voice-{VOICES - 1:05d}"


def test_音色那一问用的是同一份目录预算(speech_catalog, monkeypatch) -> None:
    """预算就是 `runtime.CATALOG_OUTPUT_BYTES`:把它改小,音色问不到(和以前一样回空),而不是另一条线。"""
    client, _plugin, instance_id = speech_catalog
    from app.domain.voices import engine_catalog

    monkeypatch.setattr(runtime, "CATALOG_OUTPUT_BYTES", 1_000)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        assert engine_catalog.list_engine_voices(db, instance_id, user_id=user.id) == []
