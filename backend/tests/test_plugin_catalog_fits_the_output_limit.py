"""一份工具清单要能**完整地**从插件走到宿主:重复的大表不重复搬,但一格下拉都不能少。

## 现场

维护者的插件页上,ComfyUI 那一行是「出错了」+「已开启 42 / 42 个工具」+ 红字「插件输出超过大小限制 (1MB)」。
那条线是宿主的:`runtime.MAX_OUTPUT_BYTES = 1_000_000` —— 一问一答那条路读到上限就停下
(`run_logged(max_stdout=…)`),报 `pluginErr_outputTooLarge`(`core/messages/plugins.py`)。撞线的是**工具清单**
那一份回答(`{"tool": "comfyui_generation", "input": {"op": "tools"}}`,`dynamic_tools.refresh` 挨的那一次),
不是某一次生成:对着真机量,36 个工具 1,055,758 字节。工具清单于是刷不出来(清单留着上一份),模型清单 89 万也贴着线。

大在哪里:ComfyUI 每个节点的输入里都有一类几百项的下拉(LoRA、大模型、VAE、文本编码器),一张图里几个节点共用
同一张、每张工作流又是一个工具、每个工具的**每一格**都带着自己那张表。那 1.06MB 里 58 万字节是重复的同一批表:
403 份、只有 77 张不同的表 —— 真正不同的内容只有 53 万。

## 钉的是什么

- 重复出现的表在回答里只搬一次(`shared_tables` + `x-shared-table`),宿主收的时候展平回每一格:和逐格写全
  **一模一样**(工作流节点、画板、插件页「试一下」读的就是这份 `input_schema`,下拉要整张 —— ADR 0044 修订
  否掉过「在插件那一侧把长下拉删掉」);
- 宿主在请求里说了它收得下(`accepts`)才算数:没说的宿主收到的还是逐格写全的那一份,照旧撞线、照旧响亮地报错 ——
  而不是收到一堆指不到的表、悄悄少几张下拉;
- 维护者那个规模(42 个工具)的清单不再撞线,而且经宿主刷新出来的每一格都带着整张下拉。

假 ComfyUI 是 `tests/comfyui_big_catalog` 那台「像真的」,多加几张工作流凑到 42 个工具(17 个时是 93 万字节,还差
一点才撞上线)。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from app.domain.plugins import shared_tables
from tests import comfyui_big_catalog
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
PACKAGE = "dev.mosael.comfyui"
#: 维护者那台上开着的工具数(截图里那句「已开启 42 / 42 个工具」)。
MAINTAINER_TOOLS = 42
#: 那 42 个工具 = 内置文生图 + 最大的那张 + 只有一个字的那张 + 每张普通工作流一个。
PLAIN_WORKFLOWS = MAINTAINER_TOOLS - 3


def _request(op: str, *, accepted: bool) -> dict[str, Any]:
    """宿主发出去的那一行请求。`accepted` 是宿主的版本:说了收得下,插件才会共享重复的大表(见 runtime)。"""
    asked: dict[str, Any] = {"tool": "comfyui_generation", "input": {"op": op}, "locale": "zh"}
    if accepted:
        asked["accepts"] = ["shared_tables"]
    return asked


def _plugin_stdout(url: str, request: dict[str, Any]) -> str:
    """直接问插件进程一句,拿它**写在 stdout 上的那一份**。这一层就是那道 1MB 的线量的地方。"""
    done = subprocess.run([sys.executable, str(PLUGIN / ENTRY)], input=json.dumps(request), capture_output=True,
                          text=True, cwd=str(PLUGIN), env={**os.environ, "SERVER_URL": url, "PYTHONUTF8": "1",
                                                            "MOSAEL_PLUGIN": "1"},
                          timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        comfyui_big_catalog.install(server.state, plain_workflows=PLAIN_WORKFLOWS)
        yield server


def test_四十二个工具的清单_逐格写全会撞线_共享之后不会(comfy) -> None:
    """维护者截图里那条报错的来源,和这一版交出去的那一份。"""
    inline = _plugin_stdout(comfy.url, _request("tools", accepted=False))
    shared = _plugin_stdout(comfy.url, _request("tools", accepted=True))
    full = json.loads(inline)["output"]
    assert len(full["tools"]) == MAINTAINER_TOOLS, "假 ComfyUI 要报到维护者那个数,不然这条什么都没量"
    # 旧宿主(不说收得下)收到的就是截图里那一份:超过 1MB,整份不收 —— 插件的清单保留上一份
    assert len(inline.encode()) > runtime.MAX_OUTPUT_BYTES
    assert "shared_tables" not in full
    # 这一版:同一份清单,重复的表只搬一次
    sent = json.loads(shared)["output"]
    assert len(shared.encode()) <= runtime.MAX_OUTPUT_BYTES
    assert len(shared.encode()) < len(inline.encode()) * 0.4, "共享的是重复的那几十万字节,不该只省下一点"
    assert sent["shared_tables"], "一张重复的表都没有共享,那这条量的是假 ComfyUI 太小"
    # 一格下拉都不能少:宿主展平回来和逐格写全一模一样
    assert shared_tables.expand(sent) == full
    assert full == json.loads(inline)["output"]


def test_模型清单也一样_同一个机制(comfy) -> None:
    """模型清单(生成那一路的 `parameters`)里是同一批大表,贴着同一条线。"""
    inline = json.loads(_plugin_stdout(comfy.url, _request("models", accepted=False)))["output"]
    shared = json.loads(_plugin_stdout(comfy.url, _request("models", accepted=True)))["output"]
    assert len(inline["models"]) == MAINTAINER_TOOLS
    assert shared_tables.expand(shared) == inline


def test_指着一张没交上来的表_照实说_不收这一份() -> None:
    """共享说错了是**插件交回的东西不对**:报出来,而不是收下一份少几张下拉的清单。"""
    from app.core.i18n import LocalizedError
    from app.domain.plugins.errors import PluginDomainError

    broken = {"tools": [{"input_schema": {"properties": {"lora_name_1": {"type": "string", "x-shared-table": "t9"}}}}],
              "shared_tables": {"t1": ["a.safetensors"]}}
    with pytest.raises(PluginDomainError) as caught:
        shared_tables.expand(broken)
    assert caught.value.key == "pluginErr_sharedTableMissing"
    assert isinstance(caught.value, LocalizedError)
    # 交上来的根本不是一张「id → 值」的表:同样不收
    with pytest.raises(PluginDomainError) as caught:
        shared_tables.expand({"tools": [], "shared_tables": 5})
    assert caught.value.key == "pluginErr_sharedTablesBadShape"


def test_刷新工具清单不再报超过大小限制_每一格下拉还是整张(comfy) -> None:
    """宿主那条路:接上这台假 ComfyUI、刷新 —— 工具清单刷得出来,而且每一格都带着整张下拉。"""
    client = fresh_client()
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    refreshed = client.post(f"/api/plugins/instances/{instance_id}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    caps = refreshed.json()["capability_status"]
    status = caps["tools"]
    assert status["tools"] == MAINTAINER_TOOLS, "工具清单没刷出来(截图里那行红字就是这么来的)"
    assert status["error"] == "", f"工具清单刷新报了错:{status['error']}"
    # 模型清单是同一批大表、贴着同一条线(维护者那台 89 万字节):一次刷新两份都得刷得出来
    assert caps["generation"]["models"] == MAINTAINER_TOOLS
    assert caps["generation"]["error"] == "", f"模型清单刷新报了错:{caps['generation']['error']}"

    listed = [one for one in client.get("/api/plugins/tools").json()
              if one["instance_id"] == instance_id and one["name"].startswith("wf_")]
    assert len(listed) == MAINTAINER_TOOLS
    # 每一格下拉还是整张:插件存的那份就是工作流节点、画板、插件页「试一下」读的那份
    biggest = max((value for tool in listed for value in (tool["input_schema"].get("properties") or {}).values()
                   if isinstance(value, dict) and isinstance(value.get("enum"), list)),
                  key=lambda spec: len(spec["enum"]))
    assert len(biggest["enum"]) == len(comfyui_big_catalog.LORAS)
    assert biggest["enum"][0] == comfyui_big_catalog.LORAS[0]
