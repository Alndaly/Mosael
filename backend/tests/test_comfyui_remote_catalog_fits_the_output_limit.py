"""一台**模型很多**的远端 ComfyUI:连接要能刷出工具,而不是「出错了 · 已开启 0/7 个工具」。

## 现场

维护者截图:一台远端 ComfyUI 连接(`https://…:8443`)显示「出错了」+「已开启 0/7 个工具」,原因只有一句
「插件输出超过大小限制 (1MB)」。那句话是宿主的 `runtime.MAX_OUTPUT_BYTES = 1_000_000`(一问一答的路读到上限
就停下,报 `pluginErr_outputTooLarge`),不是插件坏了。

撞线的是 `{"tool": "comfyui_generation", "input": {"op": "tools"}}` —— **刷新工具清单**那一次(和同一批 schema 的
`{"op": "models"}` 一起)。不是 `/object_info`:那份东西只被插件读进来,再变成每张工作流的 `input_schema` /
`parameters` 发出去。重复的大表已经由 `shared_tables` 只搬一次(673bd0b7d);剩下的字节是**真正不同的内容** ——
一台模型很多的 ComfyUI 上,每张工作流的 schema 都带着几万项的下拉(LoRA、大模型、VAE……)。ADR 0044 修订
明确否掉了「在插件那一侧把长下拉删掉」:工作流节点、画板、插件页「试一下」的表单读的就是这份 schema。

## 钉的是什么

- 这台假 ComfyUI 的 `/object_info` 是 MB 级(1,283,529 字节;维护者那台 5.9MB),**共享之后**的 `tools` 回答
  仍然超过旧的 1MB(1,352,310 字节;逐格写全的那份是 35,346,071,共享已经砍掉重复的 34MB)——
  这就是截图那条红字;连接刷新完之后工具和模型都列得出来,`capability_status` 里没有错;
- 目录类回答有自己的一份预算(`runtime.CATALOG_OUTPUT_BYTES`),但**普通工具调用一个字节都没放宽**:
  1MB 那条线照旧(见下一条用例),别的工具的输出不受这个改动影响;
- 超限那条路还在,只是说法换了:说得清是哪个工具(含 op)、允许多大、实际读到多大、下一步怎么办。
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

from app.core.i18n import render_message
from app.domain.plugins import runtime
from app.domain.plugins.runtime import PluginRuntimeError, execute_tool
from tests import comfyui_big_catalog
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
PACKAGE = "dev.mosael.comfyui"
#: 5 张普通工作流 + 最大的那张 + 只有一个字的那张 + 内置文生图 = 8 个工具。
PLAIN_WORKFLOWS = 5
TOOLS = PLAIN_WORKFLOWS + 3
#: 一台「模型很多」的 ComfyUI 的量级:几万项下拉,`/object_info` 是 MB 级(见模块说明)。
LORAS = 30_000
CHECKPOINTS = 6_000


def _make_plugin(tmp_path: Path, entry_body: str) -> tuple[Path, str]:
    """一个只按协议说话的小插件(和 tests/test_plugin_runtime.py 同一个样板)。"""
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(entry_body), encoding="utf-8")
    return plugin_dir, "main.py"


def _plugin_stdout(url: str, request: dict[str, Any]) -> str:
    """直接问插件进程一句,拿它写在 stdout 上的那一份 —— 1MB 那条线量的就是这里。"""
    done = subprocess.run(
        [sys.executable, str(PLUGIN / ENTRY)], input=json.dumps(request), capture_output=True, text=True,
        cwd=str(PLUGIN), env={**os.environ, "SERVER_URL": url, "PYTHONUTF8": "1", "MOSAEL_PLUGIN": "1"},
        timeout=300, check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def comfy(monkeypatch):
    """一台像真的、然而模型很多的远端(本机随机端口;不连外网)。"""
    monkeypatch.setattr(comfyui_big_catalog, "LORAS",
                        [f"style/lora_{index:05d}_v{index % 7}.safetensors" for index in range(LORAS)])
    monkeypatch.setattr(comfyui_big_catalog, "CHECKPOINTS",
                        [f"checkpoint_{index:04d}_xl.safetensors" for index in range(CHECKPOINTS)])
    with FakeComfyUI() as server:
        comfyui_big_catalog.install(server.state, plain_workflows=PLAIN_WORKFLOWS)
        yield server


def _connect(client, url: str) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


def test_模型很多的远端_连接刷得出工具(comfy) -> None:
    """截图那条红字的来源,和这一版收得下的那一份。"""
    client = fresh_client()
    instance_id = _connect(client, comfy.url)
    refreshed = client.post(f"/api/plugins/instances/{instance_id}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    caps = refreshed.json()["capability_status"]
    # 修复前这里就是截图那一句:「插件输出超过大小限制 (1MB)」。
    assert caps["tools"]["error"] == "", f"工具清单没刷出来:{caps['tools']['error']}"
    assert caps["tools"]["tools"] == TOOLS, "工具没列全(截图里那句「已开启 0 / 7 个工具」就是这么来的)"
    assert caps["generation"]["error"] == "", f"模型清单没刷出来:{caps['generation']['error']}"
    assert caps["generation"]["models"] == TOOLS

    # 连接上的工具 = 清单声明的固定几个 + 每张工作流一个(运行时报出来的那些,名字以 `wf_` 开头)。
    listed = [one for one in client.get("/api/plugins/tools").json()
              if one["instance_id"] == instance_id and one["name"].startswith("wf_")]
    assert len(listed) == TOOLS

    asked = {"tool": "comfyui_generation", "input": {"op": "tools"}, "locale": "zh", "accepts": ["shared_tables"]}
    sent = _plugin_stdout(comfy.url, asked)
    # 旧上限确实收不下:这就是截图里那句「插件输出超过大小限制 (1MB)」——不是插件坏了,是目录真的比线大。
    assert len(sent.encode()) > runtime.MAX_OUTPUT_BYTES, "假 ComfyUI 太小了,这条什么都没量到"
    # 这一版给目录类回答的预算收得下;仍然是有界的,不是「调到无限」。
    assert len(sent.encode()) <= runtime.CATALOG_OUTPUT_BYTES


def test_真超过上限的时候_说清哪个工具_多大_怎么办(tmp_path) -> None:
    """错误路径还在(整份不收,不截断),但不再是一句没用的话。"""
    plugin = _make_plugin(tmp_path, """
        import json
        print(json.dumps({"ok": True, "output": {"text": "x" * 4000}}), flush=True)
    """)
    with pytest.raises(PluginRuntimeError) as caught:
        execute_tool(*plugin, "demo_tool", {"op": "tools"}, output_budget=1000, timeout=20)
    exc = caught.value
    assert exc.key == "pluginErr_outputTooLarge"
    zh = render_message(exc.key, "zh", exc.params)
    en = render_message(exc.key, "en", exc.params)
    # 哪个工具(带 op —— 一个插件几十个 op 时说得出是哪一问)
    assert "demo_tool · tools" in zh and "demo_tool · tools" in en
    # 多大:上限 1000、实际读到约 4 KB
    assert "1 KB" in zh and "4 KB" in zh
    assert "4 KB" in en
    # 怎么办
    assert "刷新" in zh and "减少" in zh
    assert "Refresh" in en and "reduce" in en
    # 不再是截图里那一句只有「超过大小限制」的话
    assert "超过大小限制" not in zh


def test_连接上记下的原因也说得清_不是只有一句超过大小限制(monkeypatch) -> None:
    """这条错误会落进 `capability_status["tools"].error`、在插件页那一行显示 —— 抽查的就是它。

    目录预算临时改小,让一台**小** ComfyUI 也撞线:走完整条宿主路径(刷新 → 记下原因 → 接口按语言渲染)。
    """
    from app.domain.plugins import dynamic_tools

    monkeypatch.setattr(dynamic_tools, "CATALOG_OUTPUT_BYTES", 1_000)
    with FakeComfyUI() as server:
        client = fresh_client()
        instance_id = _connect(client, server.url)
        refreshed = client.post(f"/api/plugins/instances/{instance_id}/refresh")
        assert refreshed.status_code == 200, refreshed.text
        status = refreshed.json()["capability_status"]["tools"]
        assert status["tools"] is None
        error = status["error"]
    assert "comfyui_generation · tools" in error, f"没说清是哪个工具:{error}"
    assert "1 KB" in error, f"没说清上限/实际多大:{error}"
    assert "刷新" in error and "减少" in error, f"没说下一步怎么办:{error}"
    assert "超过大小限制 (1MB)" not in error, "还是截图里那句没用的话"


def test_普通工具的上限一个字节都没放宽(tmp_path) -> None:
    """目录类回答那份预算只给目录类;别的工具照旧停在 1MB(截图那次修复不许把闸门整个抬掉)。"""
    assert runtime.MAX_OUTPUT_BYTES == 1_000_000
    assert runtime.CATALOG_OUTPUT_BYTES > runtime.MAX_OUTPUT_BYTES
    plugin = _make_plugin(tmp_path, """
        import sys, time
        chunk = "x" * 65536
        while True:
            sys.stdout.write(chunk)
            sys.stdout.flush()
            time.sleep(0.001)
    """)
    with pytest.raises(PluginRuntimeError) as caught:
        execute_tool(*plugin, "endless", {}, timeout=20)
    assert caught.value.key == "pluginErr_outputTooLarge"
    assert caught.value.params["tool"] == "endless"
    assert caught.value.params["limit"] == "1.0 MB"
    text = render_message(caught.value.key, "zh", caught.value.params)
    assert "endless" in text and "1.0 MB" in text


def test_小输出的工具照常(tmp_path) -> None:
    """回归:没撞线的调用一个字节都不受影响。"""
    plugin = _make_plugin(tmp_path, """
        import json, sys
        request = json.loads(sys.stdin.read())
        print(json.dumps({"ok": True, "output": {"echo": request["input"].get("text", "")}}), flush=True)
    """)
    assert execute_tool(*plugin, "echo", {"text": "你好"}).output["echo"] == "你好"
