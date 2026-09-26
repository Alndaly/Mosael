"""Remotion 插件:不起 Node 也能验的那一半。

真渲染(装依赖、下浏览器、出 mp4)要联网装两百多 MB,不适合每次 CI 都跑;那一半在本机按
应用的真实路径跑过(安装 → 授权 → 经 tools.invoke 调三个工具 → 产出进素材库),记在提交里。
这里钉的是:输入怎么校验、报错说不说得清、清单和依赖版本守不守约定。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "remotion"


@pytest.fixture(scope="module")
def plugin():
    sys.path.insert(0, str(PLUGIN / "tools"))  # 入口旁边的 plugin_kit
    try:
        spec = importlib.util.spec_from_file_location("remotion_plugin_main", PLUGIN / "tools" / "main.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(PLUGIN / "tools"))
    return module


def _run_entry(payload: dict, env: dict[str, str]) -> dict:
    """跑一次入口,返回最后那一行结果(前面是进度行)。"""
    done = subprocess.run([sys.executable, str(PLUGIN / "tools" / "main.py")], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60, env=env)
    return json.loads(done.stdout.strip().splitlines()[-1])


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

    def test_强调色写错当场说_不悄悄换成默认的蓝(self, plugin) -> None:
        assert plugin.explainer_props({"title": "t", "sections": [{"heading": "a"}], "accent": "e4572e"}, "zh")["accent"] == "#E4572E"
        with pytest.raises(plugin.PluginError, match="#RRGGBB"):
            plugin.explainer_props({"title": "t", "sections": [{"heading": "a"}], "accent": "red"}, "zh")

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
    cleaned = plugin._clean_error(raw, project, "zh")
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

    def test_三个工具都流式_能报进度能取消(self) -> None:
        """此前是一问一答:取消或超时时宿主只杀得掉 Python,npm / Node / Chrome 成了孤儿接着跑。"""
        assert all(tool.get("stream") is True for tool in self.manifest()["tools"]["declare"])


# ---------------------------------------------------------------- 假的 Node / npm 跑通入口

FAKE_NODE = r'''#!{python}
"""冒充 Node:认 `-p <表达式>`(问版本和架构)、`browser.mjs`、`render.mjs`。"""
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
if args[:1] == ["-p"]:
    print(json.dumps(["v20.11.0", "darwin", os.environ.get("FAKE_NODE_ARCH", "arm64")]))
    sys.exit(0)
if args[:1] == ["browser.mjs"]:
    sys.stderr.write("browser 50%\n")
    print(json.dumps({{"ok": True, "status": "downloaded"}}))
    sys.exit(0)
if args[:1] == ["render.mjs"]:
    request = json.loads(sys.stdin.read())
    props = request["inputProps"]
    for stage in ("bundle 50%", "render 0%", "render 40%"):
        sys.stderr.write(stage + "\r"); sys.stderr.flush()
    if "SLOW" in json.dumps(props):
        # 冒充渲染用的 Chrome:一个孙进程
        chrome = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(request["projectDir"], "pids").write_text(f"{{os.getpid()}} {{chrome.pid}}")
        time.sleep(60)
    if "BROKEN" in json.dumps(props):
        print(json.dumps({{"ok": False, "error": f"Error: {{request['projectDir']}}/src/Custom.tsx:3:1: ERROR: Unexpected\n    at x (/y.js:1:1)"}}))
        sys.exit(1)
    Path(request["output"]).write_bytes(b"fake-mp4")
    sys.stderr.write("render 100%\n")
    print(json.dumps({{"ok": True, "output": request["output"], "width": props["width"], "height": props["height"], "seconds": 7.5}}))
    sys.exit(0)
sys.exit(2)
'''

FAKE_NPM = r'''#!{python}
"""冒充 npm install:建出 node_modules 里渲染要的那几处,记一笔被调过。"""
import sys
from pathlib import Path

with open(Path.cwd().parent / "npm-calls.log", "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
(Path.cwd() / "node_modules" / "@remotion" / "renderer").mkdir(parents=True, exist_ok=True)
(Path.cwd() / "node_modules" / ".remotion").mkdir(parents=True, exist_ok=True)
'''

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="假 Node 靠 shebang 起")


@pytest.fixture()
def fake_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("node", FAKE_NODE), ("npm", FAKE_NPM)):
        (bin_dir / name).write_text(body.format(python=sys.executable), encoding="utf-8")
        (bin_dir / name).chmod((bin_dir / name).stat().st_mode | stat.S_IEXEC)
    for name in ("data", "out"):
        (tmp_path / name).mkdir()
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "MOSAEL_PLUGIN_DATA_DIR": str(tmp_path / "data"),
        "MOSAEL_PLUGIN_OUTPUT_DIR": str(tmp_path / "out"),
        "MOSAEL_PLUGIN_CANCEL_FILE": str(tmp_path / "cancel"),
    }


def _call(tool: str, payload: dict, env: dict[str, str], locale: str = "zh") -> tuple[dict, list[dict]]:
    done = subprocess.run([sys.executable, str(PLUGIN / "tools" / "main.py")],
                          input=json.dumps({"tool": tool, "input": payload, "locale": locale}),
                          capture_output=True, text=True, timeout=60, env=env)
    lines = [json.loads(one) for one in done.stdout.splitlines() if one.strip()]
    return lines[-1], [one for one in lines if one.get("event") == "progress"]


def _npm_calls(env: dict[str, str]) -> list[str]:
    log = Path(env["MOSAEL_PLUGIN_DATA_DIR"]) / "npm-calls.log"
    return log.read_text().splitlines() if log.is_file() else []


EXPLAINER = {"title": "勾股定理", "sections": [{"heading": "定理", "points": ["a² + b² = c²"]}], "filename": "lesson"}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@posix_only
class Test入口:
    def test_渲染工具不装东西_没准备好就说去准备(self, fake_env) -> None:
        """此前渲染里顺手 npm install(最多 840 秒),而渲染的预算是 170 秒:装到一半被掐,下次再从头装。"""
        final, _ = _call("remotion_explainer", EXPLAINER, fake_env)
        assert final["ok"] is False and "准备渲染环境" in final["error"]
        assert _npm_calls(fake_env) == []

    def test_准备一次_之后渲染边报进度边出片(self, fake_env) -> None:
        final, progress = _call("remotion_setup", {}, fake_env)
        assert final["ok"] is True and "依赖刚装好" in final["output"]["summary"], final
        assert final["output"]["browser"] == "remotion" and progress
        again, _ = _call("remotion_setup", {}, fake_env)
        assert "依赖刚装好" not in again["output"]["summary"] and len(_npm_calls(fake_env)) == 1

        final, progress = _call("remotion_explainer", EXPLAINER, fake_env)
        assert final["ok"] is True, final
        assert final["output"]["artifact"] == {"path": "lesson.mp4"} and final["output"]["seconds"] == 7.5
        assert (Path(fake_env["MOSAEL_PLUGIN_OUTPUT_DIR"]) / "lesson.mp4").read_bytes() == b"fake-mp4"
        assert any(one["message"] == "渲染 40%" for one in progress), progress

    def test_工程按内容放好就不再动_自定义动画各用各的(self, fake_env) -> None:
        """此前每次调用都把共用工程的 src 删掉重拷 —— 同时在打包的另一次就读到半截的目录。"""
        _call("remotion_setup", {}, fake_env)
        workspace = Path(fake_env["MOSAEL_PLUGIN_DATA_DIR"]) / "workspace"
        projects = sorted(workspace.glob("project-*"))
        assert len(projects) == 1
        marker = projects[0] / "src" / "index.ts"
        before = marker.stat().st_mtime_ns
        code = "import React from 'react';\nexport default () => null;\n"
        final, _ = _call("remotion_animation", {"code": code, "seconds": 2}, fake_env)
        assert final["ok"] is True, final
        assert sorted(workspace.glob("project-*")) == projects and marker.stat().st_mtime_ns == before, "共用工程被重拷了"
        assert not list((workspace / "jobs").iterdir()), "自定义动画的那份工程用完即删"

    def test_报错指回用户代码_路径换成相对的(self, fake_env) -> None:
        _call("remotion_setup", {}, fake_env)
        final, _ = _call("remotion_animation", {"code": "export default () => null;\n", "seconds": 1, "data": {"x": "BROKEN"}}, fake_env)
        assert final["ok"] is False and "src/Custom.tsx:3:1: ERROR: Unexpected" in final["error"]
        assert fake_env["MOSAEL_PLUGIN_DATA_DIR"] not in final["error"] and " at x" not in final["error"]

    def test_Node换了架构_渲染说清楚_准备环境重装(self, fake_env) -> None:
        _call("remotion_setup", {}, fake_env)
        moved = {**fake_env, "FAKE_NODE_ARCH": "x64"}
        final, _ = _call("remotion_explainer", EXPLAINER, moved)
        assert final["ok"] is False and "darwin-arm64 → darwin-x64" in final["error"]
        final, _ = _call("remotion_setup", {}, moved)
        assert final["ok"] is True and len(_npm_calls(fake_env)) == 2

    def test_取消连Node和它起的浏览器一起停(self, fake_env) -> None:
        _call("remotion_setup", {}, fake_env)
        process = subprocess.Popen([sys.executable, str(PLUGIN / "tools" / "main.py")], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=fake_env)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"tool": "remotion_explainer", "input": {**EXPLAINER, "subtitle": "SLOW"}, "locale": "zh"}))
        process.stdin.close()
        workspace = Path(fake_env["MOSAEL_PLUGIN_DATA_DIR"]) / "workspace"
        pids: list[int] = []
        for _ in range(100):
            found = next(workspace.glob("project-*/pids"), None)
            if found and found.read_text().strip():
                pids = [int(one) for one in found.read_text().split()]
                break
            time.sleep(0.1)
        assert len(pids) == 2
        Path(fake_env["MOSAEL_PLUGIN_CANCEL_FILE"]).touch()
        rest = process.stdout.read()
        assert process.wait(timeout=20) == 0
        assert json.loads(rest.strip().splitlines()[-1]) == {"ok": False, "error": "已取消。"}
        for pid in pids:
            for _ in range(50):
                if not _alive(pid):
                    break
                time.sleep(0.1)
            assert not _alive(pid), f"进程 {pid} 还活着"

    def test_宿主的流式协议收得到进度和产出(self, fake_env, monkeypatch) -> None:
        from app.domain.plugins.runtime import StreamHooks, stream_tool

        _call("remotion_setup", {}, fake_env)
        seen: list[tuple[float, str]] = []
        hooks = StreamHooks(on_progress=lambda f, m: seen.append((f, m)), on_task=lambda _t: None, is_cancelled=lambda: False)
        scratch = Path(fake_env["MOSAEL_PLUGIN_OUTPUT_DIR"])
        monkeypatch.setenv("PATH", fake_env["PATH"])  # 宿主把自己的 PATH 交给插件
        result = stream_tool(PLUGIN, "tools/main.py", "remotion_explainer", EXPLAINER, {}, hooks=hooks,
                             scratch_dir=scratch, data_dir=Path(fake_env["MOSAEL_PLUGIN_DATA_DIR"]), timeout=60)
        assert result.output["artifact"]["path"] == "lesson.mp4" and (scratch / "lesson.mp4").is_file()
        assert any("渲染" in message for _, message in seen)
