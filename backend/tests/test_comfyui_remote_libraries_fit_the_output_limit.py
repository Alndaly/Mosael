"""模型库 / 工作流库也是**目录类回答**:和工具清单、模型清单同一条风险,同一份预算。

## 现场

维护者那台 `:8443`(116 个工具的大机)现在打开「工作流库」弹窗就报:

    插件「comfyui_generation · workflows」这一次的输出超过了 1.0 MB 的上限(实际已读到 1.0 MB),这一份没有收下……

`library`(模型库)与 `workflows`(工作流库)返回的是「这台机器上现在有什么」的一整份目录 —— 和 431935725 给
`tools` / `models` 放宽的是**同一类**回答,会随机器上的模型 / 工作流变多而线性变大。它们此前仍守
`runtime.MAX_OUTPUT_BYTES = 1_000_000`,于是同一台机器刷得出工具、却打不开工作流库。

## 钉的是什么

- 一百多张**很重**的工作流(每张 30 个节点、100 多个可调项)做出来的假 ComfyUI:`op: workflows` 的 stdout
  超过旧的 1MB,**改之前宿主整份不收**(接口 422,detail 是 `pluginErr_outputTooLarge`),**改之后读得出来**
  且每一张都在;
- 模型库同样:一个不自己削短的插件交回 > 1MB 的 `library` 回答,改之前 422、改之后整份收下(真实插件自己会
  把模型清单削到 900KB,那是插件侧的事;宿主这一侧的预算测试用一个不削的桩,量的就是宿主这道闸);
- 预算仍然**有界**:超过 `CATALOG_OUTPUT_BYTES` 照旧整份不收、不截断,文案说清工具名(含 op)、上限、实际
  读到多大、下一步;
- **普通工具一个字节都没放宽**:没有 `output_budget` 的调用照旧停在 1MB。
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
from app.db.models import PluginPackage
from app.domain.plugins import runtime
from app.domain.plugins.runtime import PluginRuntimeError, execute_tool
from tests import comfyui_big_catalog
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
PACKAGE = "dev.mosael.comfyui"
#: 116 个工具那台机器的工作流数量级(每张工作流一个工具)。这里用重的那些:30 个节点、117 个可调项。
WORKFLOWS = 120

STUB_PACKAGE = "test.catalog"
#: 一个不自己削短的模型库插件:3000 个文件、名字长一点,回答约 2 MB(旧上限收不下)。
STUB_PLUGIN = r'''
import json, sys

request = json.loads(sys.stdin.read())
payload = request["input"]
op = payload.get("op")
if op == "library":
    count = 3000
    models = [{"folder": "loras", "name": f"lora_{index:05d}_" + "x" * 600 + ".safetensors"}
              for index in range(count)]
    print(json.dumps({"ok": True, "output": {
        "folders": [{"name": "loras", "count": count}],
        "models": models,
        "missing": [],
        "download": {"route": "none", "note": ""},
        "preview_tools": {"lookup": "", "save": False, "save_note": ""},
    }}, ensure_ascii=False), flush=True)
else:
    print(json.dumps({"ok": False, "error": f"unknown op {op}"}), flush=True)
'''


def _plugin_stdout(url: str, request: dict[str, Any]) -> str:
    """直接问插件进程一句,拿它写在 stdout 上的那一份 —— 1MB / 8MB 那两条线量的就是这里。"""
    done = subprocess.run(
        [sys.executable, str(PLUGIN / ENTRY)], input=json.dumps(request), capture_output=True, text=True,
        cwd=str(PLUGIN), env={**os.environ, "SERVER_URL": url, "PYTHONUTF8": "1", "MOSAEL_PLUGIN": "1"},
        timeout=600, check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return done.stdout


@pytest.fixture
def comfy():
    """一台工作流很多、而且每张都很重的远端 ComfyUI(本机随机端口,不连外网)。"""
    with FakeComfyUI() as server:
        server.state.workflows = {f"重/{index:03d}.json": comfyui_big_catalog.big() for index in range(WORKFLOWS)}
        yield server


def _connect(client, url: str) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


@pytest.fixture
def stub_library(tmp_path: Path):
    """一个只认领 `model_library` 的小插件:它的 `library` 回答不自己削短(见 STUB_PLUGIN)。"""
    client = fresh_client()
    plugin = tmp_path / "catalog"
    plugin.mkdir()
    (plugin / "main.py").write_text(textwrap.dedent(STUB_PLUGIN), encoding="utf-8")
    manifest = {
        "id": STUB_PACKAGE,
        "name": "测试目录",
        "version": "1.0.0",
        "manifest_version": 1,
        "runtime": {"kind": "process", "entry": "main.py"},
        "provides": ["model_library"],
        "instance": {"multiple": False, "name_template": "测试目录"},
        "tools": {"declare": [{"name": "host", "provides": ["model_library"], "timeout_seconds": 120,
                               "input_schema": {"type": "object"}}]},
        "_path": str(plugin),
    }
    with SessionLocal() as db:
        db.add(PluginPackage(id=STUB_PACKAGE, name="测试目录", version="1.0.0", manifest=manifest))
        db.commit()
    created = client.post(f"/api/plugins/{STUB_PACKAGE}/instances", json={"config": {}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    yield client, instance_id


def test_工作流很多的远端_工作流库读得出来(comfy) -> None:
    """截图那条红字:改之前宿主整份不收,改之后每一张都列得出来。"""
    client = fresh_client()
    instance_id = _connect(client, comfy.url)
    asked = {"tool": "comfyui_generation", "input": {"op": "workflows"}, "locale": "zh", "accepts": ["shared_tables"]}
    sent = _plugin_stdout(comfy.url, asked)
    # 旧上限确实收不下:这就是「插件「comfyui_generation · workflows」这一次的输出超过了 1.0 MB 的上限」。
    assert len(sent) > runtime.MAX_OUTPUT_BYTES, "假 ComfyUI 的工作流不够多,这条什么都没量到"
    assert len(sent) <= runtime.CATALOG_OUTPUT_BYTES, "目录预算收不下这台机器,得看要不要把它提上去"
    print(f"op workflows: chars={len(sent):,} bytes={len(sent.encode()):,} "
          f"(1MB={runtime.MAX_OUTPUT_BYTES:,}, catalog={runtime.CATALOG_OUTPUT_BYTES:,})")

    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["workflows"]) == WORKFLOWS, "工作流没列全"
    assert {one["path"] for one in body["workflows"]} == set(comfy.state.workflows), "列出来的不是那台机器上的那些"


def test_工作流库真的超过预算时_整份不收_说得清(monkeypatch) -> None:
    """文案仍是「工具名(含 op)+ 上限 + 实际多大 + 下一步」,不是一句「超过大小限制」;而且不截断。"""
    from app.domain import server_workflows

    monkeypatch.setattr(server_workflows, "CATALOG_OUTPUT_BYTES", 1_000)
    with FakeComfyUI() as server:
        client = fresh_client()
        instance_id = _connect(client, server.url)
        response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library")
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "comfyui_generation · workflows" in detail, f"没说清是哪一问:{detail}"
    assert "1 KB" in detail, f"没说清上限:{detail}"
    assert "KB" in detail.split("实际已读到", 1)[1].split(")", 1)[0], f"没说清实际读到多大:{detail}"
    assert "刷新" in detail and "减少" in detail, f"没说下一步怎么办:{detail}"
    assert "超过大小限制 (1MB)" not in detail, "还是截图里那一句没用的话"


def test_模型库同样在目录预算里(stub_library) -> None:
    """宿主这一侧给 `library` 同一份预算:不自己削短的插件交回 > 1MB,改之前 422、改之后整份收下。"""
    client, instance_id = stub_library
    response = client.get(f"/api/plugins/instances/{instance_id}/model-library")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["models"]) == 3_000, "模型没列全"
    assert body["folders"] == [{"name": "loras", "count": 3_000}]


def test_普通工具照旧停在_1MB(tmp_path) -> None:
    """目录类那份预算只给目录类;没有 `output_budget` 的调用一个字节都没放宽。"""
    assert runtime.MAX_OUTPUT_BYTES == 1_000_000
    assert runtime.CATALOG_OUTPUT_BYTES > runtime.MAX_OUTPUT_BYTES
    plugin = tmp_path / "p"
    plugin.mkdir()
    (plugin / "main.py").write_text(textwrap.dedent("""
        import json, sys
        request = json.loads(sys.stdin.read())
        print(json.dumps({"ok": True, "output": {"text": "x" * 1_100_000}}), flush=True)
    """), encoding="utf-8")
    with pytest.raises(PluginRuntimeError) as caught:
        execute_tool(plugin, "main.py", "demo_tool", {"op": "something"}, timeout=30)
    assert caught.value.key == "pluginErr_outputTooLarge"
    assert caught.value.params["tool"] == "demo_tool · something"
    assert caught.value.params["limit"] == "1.0 MB"
