"""Remotion 插件:不起 Node 也能验的那一半。

真渲染(装依赖、下浏览器、出 mp4)要联网装两百多 MB,不适合每次 CI 都跑;那一半在本机按
应用的真实路径跑过(安装 → 授权 → 经 tools.invoke 调三个工具 → 产出进素材库),记在提交里。
这里钉的是:输入怎么校验、报错说不说得清、清单和依赖版本守不守约定。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "remotion"


@pytest.fixture(scope="module")
def plugin():
    spec = importlib.util.spec_from_file_location("remotion_plugin_main", PLUGIN / "tools" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_entry(payload: dict, env: dict[str, str]) -> dict:
    import subprocess

    done = subprocess.run([sys.executable, str(PLUGIN / "tools" / "main.py")], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=env)
    return json.loads(done.stdout)


class Test讲解视频的输入:
    def test_标题和至少一节是必须的(self, plugin) -> None:
        with pytest.raises(plugin.PluginError, match="标题"):
            plugin.explainer_props({"sections": [{"heading": "x"}]}, "zh")
        with pytest.raises(plugin.PluginError, match="至少要有一节"):
            plugin.explainer_props({"title": "t", "sections": []}, "zh")
        with pytest.raises(plugin.PluginError, match="第 2 节缺小标题"):
            plugin.explainer_props({"title": "t", "sections": [{"heading": "a"}, {"points": ["x"]}]}, "zh")

    def test_画幅决定尺寸_主题默认深色_总结标题跟语言走(self, plugin) -> None:
        props = plugin.explainer_props({"title": "t", "sections": [{"heading": "a"}], "aspect": "9:16"}, "en")
        assert (props["width"], props["height"], props["theme"]) == (1080, 1920, "dark")
        assert props["summaryTitle"] == "Key takeaways"
        with pytest.raises(plugin.PluginError, match="画幅"):
            plugin.explainer_props({"title": "t", "sections": [{"heading": "a"}], "aspect": "4:3"}, "zh")

    def test_超长的内容被截到画得下(self, plugin) -> None:
        """要点再多也画不下 —— 截断并不报错,而是按上限收;节数超了才拒(那是该拆成几段)。"""
        section = {"heading": "a", "points": [f"要点{i}" for i in range(10)], "code": "x\n" * 5}
        props = plugin.explainer_props({"title": "t" * 200, "sections": [section]}, "zh")
        assert len(props["title"]) == 80 and len(props["sections"][0]["points"]) == 6
        with pytest.raises(plugin.PluginError, match="最多 12 节"):
            plugin.explainer_props({"title": "t", "sections": [{"heading": "a"}] * 13}, "zh")

    def test_空字段不进画面(self, plugin) -> None:
        props = plugin.explainer_props({"title": "t", "sections": [{"heading": "a", "formula": "  ", "note": ""}]}, "zh")
        assert "formula" not in props["sections"][0] and "note" not in props["sections"][0]


class Test自定义动画的代码:
    def test_要有默认导出(self, plugin) -> None:
        with pytest.raises(plugin.PluginError, match="export default"):
            plugin.check_animation_code("const Scene = () => null;", "zh")

    def test_没装的包在渲染前就说清楚(self, plugin) -> None:
        """否则要等打包失败才知道,报的还是 webpack 的 Module not found。"""
        with pytest.raises(plugin.PluginError, match="lodash"):
            plugin.check_animation_code("import _ from 'lodash';\nexport default () => null;", "zh")
        with pytest.raises(plugin.PluginError, match="three"):
            plugin.check_animation_code("import 'three';\nexport default () => null;", "zh")

    def test_react_remotion_katex_可以用(self, plugin) -> None:
        plugin.check_animation_code(
            "import React from 'react';\nimport { AbsoluteFill } from \"remotion\";\n"
            "import katex from 'katex';\nimport 'katex/dist/katex.min.css';\nexport default () => null;",
            "zh",
        )


def test_报错只留改得动的那几行(plugin, tmp_path, monkeypatch) -> None:
    """打包报错开头那几行有用(文件:行:列),后面是一长串栈;路径两种写法都换掉。"""
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path))
    project = tmp_path / "workspace" / "jobs" / "abc"
    raw = (
        f"Error: Module build failed (from {tmp_path}/workspace/node_modules/@remotion/bundler/dist/esbuild-loader/index.js):\n"
        f"Error: Transform failed with 1 error:\n{project}/src/Custom.tsx:1:48: ERROR: Unexpected end of file\n"
        + "\n".join(f"    at frame{i} ({tmp_path}/workspace/node_modules/x.js:{i}:1)" for i in range(40))
    )
    cleaned = plugin._clean_error(raw, project)
    assert "src/Custom.tsx:1:48: ERROR: Unexpected end of file" in cleaned
    assert " at frame" not in cleaned and str(tmp_path) not in cleaned and "(from " not in cleaned


class Test协议:
    def test_找不到Node时说怎么办(self, tmp_path) -> None:
        out = _run_entry({"tool": "remotion_setup", "input": {}, "locale": "zh"},
                         {"PATH": str(tmp_path), "MOSAEL_PLUGIN_DATA_DIR": str(tmp_path)})
        assert out["ok"] is False and "Node.js" in out["error"] and "nodejs.org" in out["error"]

    def test_宿主没给持久目录时说清楚(self, tmp_path) -> None:
        out = _run_entry({"tool": "remotion_setup", "input": {}, "locale": "zh"}, {"PATH": "/usr/bin:/bin"})
        assert out["ok"] is False and "MOSAEL_PLUGIN_DATA_DIR" in out["error"]

    def test_不认识的工具(self, tmp_path) -> None:
        out = _run_entry({"tool": "nope", "input": {}}, {"PATH": "/usr/bin:/bin"})
        assert out["ok"] is False and "nope" in out["error"]


class Test清单与依赖:
    def manifest(self) -> dict:
        return json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))

    def test_渲染工具的预算压在智能体的上限以内(self) -> None:
        """智能体单次工具调用最多等 180 秒(agent-sidecar/src/tools.ts)。渲染工具要给智能体用,
        预算超过它的话,智能体那边先断,后端还在白跑。"""
        tools = {t["name"]: t for t in self.manifest()["tools"]["declare"]}
        sidecar = (PLUGIN.parents[2] / "agent-sidecar" / "src" / "tools.ts").read_text(encoding="utf-8")
        agent_limit = int(re.search(r"TOOL_CALL_TIMEOUT_MS = ([\d_]+)", sidecar).group(1).replace("_", "")) / 1000
        for name in ("remotion_explainer", "remotion_animation"):
            assert tools[name]["timeout_seconds"] < agent_limit, name

    def test_插件内部的渲染超时短于声明的预算(self, plugin) -> None:
        """自己先停、说一句人话,而不是被宿主直接掐掉。"""
        tools = {t["name"]: t for t in self.manifest()["tools"]["declare"]}
        assert plugin.RENDER_TIMEOUT < tools["remotion_explainer"]["timeout_seconds"]
        assert plugin.SETUP_TIMEOUT < tools["remotion_setup"]["timeout_seconds"]

    def test_依赖锁定精确版本(self) -> None:
        """插件的工具是对着这几个版本测的;写成 ^ 的话,下一次安装拿到的是另一套。"""
        deps = json.loads((PLUGIN / "tools" / "project" / "package.json").read_text())["dependencies"]
        assert deps and all(re.fullmatch(r"\d+\.\d+\.\d+", version) for version in deps.values()), deps
        remotion = {deps[name] for name in ("remotion", "@remotion/bundler", "@remotion/renderer")}
        assert len(remotion) == 1, "Remotion 的几个包版本必须一致"

    def test_README里写的版本和锁定的一致(self) -> None:
        deps = json.loads((PLUGIN / "tools" / "project" / "package.json").read_text())["dependencies"]
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        for name, label in (("remotion", "Remotion"), ("react", "React"), ("katex", "KaTeX")):
            assert f"{label} {deps[name]}" in readme, f"README 里的 {label} 版本和 package.json 不一致"
