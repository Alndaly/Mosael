"""Remotion —— 用代码做动画:知识点讲解、公式推导、代码演示、数据图。

## 它是为什么存在的

讲一个知识点、推一条公式、演示一段代码,要的是**准确**:字不能错、公式不能糊、步骤要一条
一条出来。视频生成模型擅长的是画面,不是这个 —— 它会把公式画成像公式的纹理,还要花钱。
Remotion 用 React 写画面、逐帧渲染成 mp4:字就是字,公式由 KaTeX 排版,零生成费用。

## 三个工具(都是流式的:边跑边报进度,取消时连 Node 和它起的 Chrome 一起停)

- `remotion_setup`:准备渲染环境(装依赖、备浏览器)。第一次要几十秒到几分钟,之后是空转。
- `remotion_explainer`:给内容(标题、每节要点 / 公式 / 代码 / 提示),套内置模板出片。
- `remotion_animation`:给一段 Remotion 组件代码,想画什么画什么。

**渲染工具不装东西。** 装依赖、下浏览器要几十秒到几分钟,而渲染工具的预算是按「智能体一次最多等 180 秒」
定的:在渲染里装,多半是装到一半被掐掉,留下半截的 node_modules,下一次再从头装、再被掐掉。环境不齐时
渲染工具说清楚缺什么、去跑「准备渲染环境」(和 Manim 插件同一个规矩)。

## 放在哪儿

依赖(约 200 MB)和浏览器装在 MOSAEL_PLUGIN_DATA_DIR/workspace —— 插件更新时插件目录会整个换掉,那里不会。
`.installed` 记着装的是哪一份:package.json 的指纹 + Node 的平台与架构(Remotion 的合成器是按平台发的
二进制包,换一台机器、从 Rosetta 的 x64 Node 换成 arm64 的,装着的那份就不能用了)。

工程源码(tools/project)按内容指纹放进 `workspace/project-<指纹>/`,**放好就不再改**:同一时刻可以有几次
渲染(宿主给插件的并发名额不止一个),此前每次调用都把共用的那份 src 删掉重拷,正在打包的另一次就读到
半截的目录。插件更新了,指纹变了,就是另一个目录。

## 协议

stdin 读一个 JSON 请求 {"tool", "input", "locale"};stdout 一行一个 JSON(NDJSON):进度
`{"event": "progress", …}`,最后一行是结果 `{"ok": …}`。**npm、node 的输出一律截获**,不漏到 stdout 上。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugin_kit import (
    Emit, PluginError, TimedOut, data_dir, emit, exclusive, follow, fresh_dir, line, output_dir, progress, safe_stem,
)

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "project"
#: 渲染工具从开始到交出结果的上限。清单里给它们声明了 170 秒(压在智能体单次调用 180 秒以内),
#: 这里留出收尾的余量:超时时自己说一句人话,而不是被宿主直接掐掉。
RENDER_TIMEOUT = 150
#: 准备环境**整个**的上限(装依赖 + 下浏览器共用这一个数)。清单里声明了 900 秒。
SETUP_TIMEOUT = 840
MIN_NODE = 18

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
FPS_CHOICES = (24, 25, 30, 60)
#: 自定义动画里能 import 的包 —— 工作区里装了的就这些。别的包写了也打包不出来,不如先说清楚。
ALLOWED_IMPORTS = {"react", "remotion", "katex", "katex/dist/katex.min.css"}


# ---------------------------------------------------------------- 环境

def workspace(locale: str) -> Path:
    return data_dir(locale) / "workspace"


def _run(args: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    """一问一答的小命令(问 Node 的版本)。长活走 plugin_kit.follow。"""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)


@dataclass(frozen=True)
class Node:
    path: str
    version: str
    #: `darwin-arm64` 这样的平台与架构 —— 装着的依赖里有按它挑的二进制包。
    target: str


def node_info(locale: str) -> Node:
    node = shutil.which("node")
    if not node:
        raise PluginError(line(
            locale,
            f"找不到 Node.js。Remotion 需要 Node.js {MIN_NODE} 或更新版本:到 https://nodejs.org 装好后重启 Mosael。",
            f"Node.js not found. Remotion needs Node.js {MIN_NODE} or newer: install it from https://nodejs.org and restart Mosael.",
        ))
    try:
        said = _run([node, "-p", "JSON.stringify([process.version, process.platform, process.arch])"], cwd=HERE, timeout=20)
        version, platform, arch = json.loads(said.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        version, platform, arch = "", "", ""
    version = str(version).lstrip("v")
    major = version.split(".")[0]
    if not major.isdigit() or int(major) < MIN_NODE:
        raise PluginError(line(
            locale,
            f"Node.js 版本是 {version or '未知'},Remotion 需要 {MIN_NODE} 或更新。",
            f"Node.js is {version or 'unknown'}; Remotion needs {MIN_NODE} or newer.",
        ))
    return Node(path=node, version=version, target=f"{platform}-{arch}")


def npm_binary(node: Node, locale: str) -> str:
    # 优先用和 node 同目录的 npm:PATH 里可能还有另一套旧的。
    for candidate in (Path(node.path).with_name("npm.cmd"), Path(node.path).with_name("npm")):
        if candidate.is_file():
            return str(candidate)
    npm = shutil.which("npm")
    if not npm:
        raise PluginError(line(locale, "找不到 npm(它随 Node.js 一起装)。", "npm not found (it ships with Node.js)."))
    return npm


def fingerprint(node: Node) -> dict[str, str]:
    """装着的依赖是为哪一份准备的:package.json 一变(插件升级换了版本)、Node 的平台架构一变,都要重装。"""
    return {"deps": hashlib.sha256((SOURCE / "package.json").read_bytes()).hexdigest()[:16], "node": node.target}


def _installed(ws: Path) -> dict[str, Any]:
    try:
        value = json.loads((ws / ".installed").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def dependencies_ready(ws: Path, node: Node) -> bool:
    return _installed(ws) == fingerprint(node) and (ws / "node_modules" / "@remotion" / "renderer").is_dir()


def _not_ready(ws: Path, node: Node, locale: str) -> PluginError:
    """依赖不是这一份:说清楚为什么,去跑「准备渲染环境」。"""
    setup = line(locale, "在「插件 → Remotion 动画」里运行一次「准备渲染环境」", "Run \"Prepare the renderer\" once from Plugins → Remotion")
    had, want = _installed(ws), fingerprint(node)
    if had.get("node") and had.get("node") != want["node"]:
        return PluginError(line(locale, f"Node.js 换了平台或架构({had['node']} → {want['node']}),渲染依赖要按它重装:{setup}。",
                                f"Node.js changed platform or architecture ({had['node']} → {want['node']}), so the dependencies must be reinstalled: {setup}."))
    if had.get("deps") and had.get("deps") != want["deps"]:
        return PluginError(line(locale, f"插件升级换了 Remotion 的版本,依赖要重装一次:{setup}。",
                                f"The plugin update changed the Remotion version; reinstall the dependencies: {setup}."))
    return PluginError(line(locale, f"渲染环境还没准备好:{setup}(第一次要几十秒到几分钟)。",
                            f"The renderer is not set up yet: {setup} (the first run takes up to a few minutes)."))


def _remaining(deadline: float) -> float:
    return max(1.0, deadline - time.monotonic())


def install_dependencies(node: Node, locale: str, send: Emit, deadline: float) -> bool:
    """装依赖。已经是这一份就什么都不做,返回是否真的装了。调用方拿着 setup 锁。"""
    ws = workspace(locale)
    ws.mkdir(parents=True, exist_ok=True)
    if dependencies_ready(ws, node):
        return False
    progress(send, 0.05, line(locale, "安装 Remotion(第一次要一两分钟)", "Installing Remotion (a minute or two the first time)"))
    shutil.copy2(SOURCE / "package.json", ws / "package.json")
    (ws / ".installed").unlink(missing_ok=True)
    args = [npm_binary(node, locale), "install", "--no-audit", "--no-fund", "--loglevel=error",
            "--cache", str(data_dir(locale) / "npm-cache")]
    registry = os.environ.get("NPM_REGISTRY", "").strip()
    if registry:
        args.append(f"--registry={registry}")
    try:
        done = follow(args, locale=locale, timeout=_remaining(deadline), cwd=ws)
    except TimedOut as exc:
        raise PluginError(line(
            locale,
            "安装依赖超时。国内网络可以在插件配置里把 npm 镜像设成 https://registry.npmmirror.com 再试。",
            "Installing dependencies timed out. Try setting the npm registry in the plugin settings.",
        )) from exc
    if done.returncode != 0:
        raise PluginError(line(locale, "安装依赖失败:", "Installing dependencies failed: ") + _tail("\n".join(done.tail)))
    (ws / ".installed").write_text(json.dumps(fingerprint(node)), encoding="utf-8")
    return True


def _source_digest() -> str:
    """工程源码(不含 package.json —— 那一份归依赖管)的内容指纹。"""
    digest = hashlib.sha256()
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file() and path.name != "package.json" and "node_modules" not in path.parts:
            digest.update(path.relative_to(SOURCE).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def project_dir(locale: str) -> Path:
    """这一版工程源码在工作区里的那一份。按内容指纹命名,**放好就不再改**。

    先拷到一个临时目录、再改名成正式的名字:改名是原子的,别人要么看不到它,要么看到完整的一份。
    放在工作区里面:node_modules 往上一层就找得到。
    """
    ws = workspace(locale)
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / f"project-{_source_digest()}"
    if not (target / "src" / "index.ts").is_file():
        staging = ws / f".project-{uuid.uuid4().hex[:8]}"
        shutil.copytree(SOURCE, staging, ignore=shutil.ignore_patterns("package.json", "node_modules"))
        try:
            os.replace(staging, target)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)  # 另一次调用刚放好了同一份
    _forget_old_projects(ws, keep=target)
    return target


def _forget_old_projects(ws: Path, keep: Path) -> None:
    """插件更新前的那几版工程(和更早的、每次重拷的 `project/`):一天没人用了就删。"""
    cutoff = time.time() - 86400
    for old in [*ws.glob("project-*"), *ws.glob(".project-*"), ws / "project"]:
        try:
            if old != keep and old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


#: 下不下来 Remotion 自己的浏览器时(它从 storage.googleapis.com 下,国内常常不通)退到本机的。
SYSTEM_BROWSERS = {
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "linux": ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge"],
}


def _configured_browser(locale: str) -> dict[str, Any] | None:
    configured = os.environ.get("BROWSER_EXECUTABLE", "").strip()
    if not configured:
        return None
    if not Path(configured).is_file():
        raise PluginError(line(locale, f"配置的浏览器不存在:{configured}", f"The configured browser does not exist: {configured}"))
    return {"browserExecutable": configured, "chromeMode": "chrome-for-testing", "source": "configured"}


def prepare_browser(node: Node, project: Path, locale: str, send: Emit, deadline: float) -> dict[str, Any]:
    """定下渲染用哪个浏览器,记进 browser.json。顺序:用户指定的 → Remotion 自己的 → 本机的。"""
    chosen = _configured_browser(locale)
    if chosen is None:
        said: list[str] = []

        def on_line(stream: str, text: str) -> None:
            if stream == "out":
                said.append(text)
            elif match := re.match(r"browser (\d+)%", text):
                progress(send, 0.65 + 0.3 * int(match.group(1)) / 100,
                         line(locale, f"下载渲染用的浏览器 {match.group(1)}%", f"Downloading the rendering browser {match.group(1)}%"))

        try:
            follow([node.path, "browser.mjs"], locale=locale, timeout=_remaining(deadline), cwd=project, on_line=on_line)
            result = _last_json(said)
        except TimedOut:
            result = {"ok": False, "error": "timeout"}
        if result.get("ok"):
            chosen = {"browserExecutable": None, "chromeMode": "headless-shell", "source": "remotion"}
        else:
            platform = sys.platform if sys.platform in ("darwin", "win32") else "linux"
            local = next((one for one in SYSTEM_BROWSERS[platform] if Path(one).is_file()), None)
            if not local:
                raise PluginError(line(
                    locale,
                    "下载渲染用的浏览器失败,本机也没找到 Chrome / Edge。装一个 Chrome,或在插件配置里填浏览器路径。原因:",
                    "Could not download the rendering browser and found no local Chrome / Edge. Install Chrome or set the browser path. Reason: ",
                ) + str(result.get("error") or "")[:300])
            chosen = {"browserExecutable": local, "chromeMode": "chrome-for-testing", "source": "system"}
    (workspace(locale) / "browser.json").write_text(json.dumps(chosen), encoding="utf-8")
    return chosen


def browser_choice(locale: str) -> dict[str, Any]:
    """渲染用哪个浏览器。配置里填了就用它;否则用「准备渲染环境」定下的那个,那个不在了就说去重新准备。"""
    configured = _configured_browser(locale)
    if configured is not None:
        return configured
    ws = workspace(locale)
    try:
        chosen = json.loads((ws / "browser.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        chosen = {}
    usable = (
        (chosen.get("source") == "system" and Path(str(chosen.get("browserExecutable") or "")).is_file())
        or (chosen.get("source") == "remotion" and (ws / "node_modules" / ".remotion").is_dir())
    )
    if not usable:
        # 记下的浏览器不在了(卸了 Chrome、Remotion 的被清掉),或者配置里的路径刚被清空
        raise PluginError(line(
            locale,
            "渲染用的浏览器不在了(或者刚改过浏览器设置):在「插件 → Remotion 动画」里再运行一次「准备渲染环境」。",
            "The rendering browser is gone (or the browser setting just changed): run \"Prepare the renderer\" again from Plugins → Remotion.",
        ))
    return chosen


def ensure_ready(locale: str) -> tuple[Node, Path, dict[str, Any]]:
    """渲染前:依赖、工程、浏览器都在。**只看不装**(见文件开头)。"""
    node = node_info(locale)
    ws = workspace(locale)
    if not dependencies_ready(ws, node):
        raise _not_ready(ws, node, locale)
    return node, project_dir(locale), browser_choice(locale)


# ---------------------------------------------------------------- 渲染

def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def _last_json(lines: list[str]) -> dict[str, Any]:
    for raw in reversed(lines):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _output_path(payload: dict[str, Any], fallback: str, locale: str) -> tuple[Path, str]:
    name = f"{safe_stem(payload.get('filename'), fallback, ('mp4',))}.mp4"
    return output_dir(locale) / name, name


_STAGE = re.compile(r"^(bundle|render) (\d+)%$")


def render(node: Node, project: Path, browser: dict[str, Any], composition: str, input_props: dict[str, Any],
           output: Path, locale: str, send: Emit, deadline: float) -> dict[str, Any]:
    request = {
        "projectDir": str(project), "composition": composition, "inputProps": input_props, "output": str(output),
        "browserExecutable": browser.get("browserExecutable"), "chromeMode": browser.get("chromeMode"),
        "licenseKey": os.environ.get("REMOTION_LICENSE_KEY", "").strip() or None,
    }
    said: list[str] = []
    complained: list[str] = []

    def on_line(stream: str, text: str) -> None:
        if stream == "out":
            said.append(text)
            return
        match = _STAGE.match(text.strip())
        if not match:
            complained.append(text)
        elif match.group(1) == "bundle":
            progress(send, 0.05 + 0.15 * int(match.group(2)) / 100, line(locale, "打包画面", "Bundling"))
        else:
            progress(send, 0.2 + 0.75 * int(match.group(2)) / 100,
                     line(locale, f"渲染 {match.group(2)}%", f"Rendering {match.group(2)}%"))

    try:
        follow([node.path, "render.mjs"], locale=locale, timeout=_remaining(deadline), cwd=project,
               on_line=on_line, stdin_text=json.dumps(request, ensure_ascii=False))
    except TimedOut as exc:
        raise PluginError(line(
            locale,
            f"渲染超过 {RENDER_TIMEOUT} 秒还没完成。把视频缩短(少几节、少几条要点),或拆成几段分别渲染。",
            f"Rendering did not finish within {RENDER_TIMEOUT}s. Shorten the video or split it into parts.",
        )) from exc
    result = _last_json(said)
    if not result.get("ok"):
        raise PluginError(line(locale, "渲染失败:", "Rendering failed: ")
                          + _clean_error(result.get("error") or "\n".join(complained), project, locale))
    if not output.is_file():
        raise PluginError(line(locale, "渲染说成功了,但没有产出文件。", "Rendering reported success but produced no file."))
    return result


def _clean_error(text: str, project: Path, locale: str) -> str:
    """把打包 / 渲染的报错整理成**改得动**的样子,交还给写代码的那一方。

    - 有用的是开头那几行(「Custom.tsx:1:49: ERROR: …」),后面是一长串调用栈 —— 取头不取尾,
      栈帧整行去掉。取尾的话,截下来的恰好全是栈。
    - 绝对路径换成相对的:读得懂,也不把用户目录抖出去。两种写法都换 —— macOS 上 /tmp 是
      /private/tmp 的链接,报错里出现的是真实路径。
    """
    text = str(text or "")
    ws = workspace(locale)
    for base in sorted({str(project), os.path.realpath(project), str(ws), os.path.realpath(ws)},
                       key=len, reverse=True):
        text = text.replace(base + os.sep, "")
    text = re.sub(r"\s*\(from [^)]*\)", "", text)  # webpack 加载器的路径:对改代码没有用
    kept = [one for one in text.splitlines() if not one.lstrip().startswith("at ")]
    text = "\n".join(kept).strip()
    return text if len(text) <= 1500 else text[:1500] + "…"


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _aspect(payload: dict[str, Any], locale: str) -> tuple[int, int]:
    aspect = str(payload.get("aspect") or "16:9")
    if aspect not in ASPECTS:
        raise PluginError(line(locale, f"画幅只能是 {'、'.join(ASPECTS)}。", f"Aspect must be one of {', '.join(ASPECTS)}."))
    return ASPECTS[aspect]


def explainer_props(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    title = _text(payload.get("title"), 80)
    if not title:
        raise PluginError(line(locale, "缺标题(title)。", "A title is required."))
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise PluginError(line(locale, "至少要有一节(sections)。", "At least one section is required."))
    if len(raw_sections) > 12:
        raise PluginError(line(locale, "最多 12 节 —— 再多请拆成几段视频。", "At most 12 sections; split longer lessons."))
    sections = []
    for index, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, dict) or not _text(raw.get("heading"), 80):
            raise PluginError(line(locale, f"第 {index} 节缺小标题(heading)。", f"Section {index} needs a heading."))
        points = [_text(p, 140) for p in (raw.get("points") or []) if _text(p, 140)][:6]
        section = {"heading": _text(raw.get("heading"), 80), "points": points}
        for key, limit in (("formula", 400), ("code", 2400), ("note", 200)):
            if _text(raw.get(key), limit):
                section[key] = str(raw.get(key)).strip("\n")[:limit] if key == "code" else _text(raw.get(key), limit)
        sections.append(section)
    width, height = _aspect(payload, locale)
    summary = [_text(s, 120) for s in (payload.get("summary") or []) if _text(s, 120)][:6]
    return {
        "title": title, "subtitle": _text(payload.get("subtitle"), 120), "label": _text(payload.get("label"), 40),
        "sections": sections, "summary": summary,
        "summaryTitle": line(locale, "要点回顾", "Key takeaways"),
        "theme": "light" if payload.get("theme") == "light" else "dark",
        "accent": _accent(payload.get("accent"), locale), "width": width, "height": height, "fps": 30,
    }


def _accent(raw: Any, locale: str) -> str:
    """强调色 #RRGGBB(`#` 可以不写)。写错了当场说 —— 模板认不出的颜色会悄悄换成默认的蓝。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", text):
        raise PluginError(line(locale, f"强调色要写成 #RRGGBB:{text}", f"The accent colour must be #RRGGBB: {text}"))
    return "#" + text.lstrip("#").upper()


def check_animation_code(code: str, locale: str) -> None:
    if "export default" not in code:
        raise PluginError(line(
            locale,
            "代码里要有 `export default` 一个 React 组件(它就是整个画面)。",
            "The code must `export default` a React component (the whole frame).",
        ))
    imported = set(re.findall(r"""^\s*import\s[^'"]*?['"]([^'"]+)['"]""", code, flags=re.M))
    imported |= set(re.findall(r"""^\s*import\s+['"]([^'"]+)['"]""", code, flags=re.M))
    unknown = sorted(name for name in imported if name not in ALLOWED_IMPORTS)
    if unknown:
        raise PluginError(line(
            locale,
            f"只能 import {'、'.join(sorted(ALLOWED_IMPORTS))};这些没有装:{'、'.join(unknown)}",
            f"Only {', '.join(sorted(ALLOWED_IMPORTS))} can be imported; not installed: {', '.join(unknown)}",
        ))


# ---------------------------------------------------------------- 工具

def remotion_setup(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    deadline = time.monotonic() + SETUP_TIMEOUT
    data_dir(locale)  # 宿主的问题先说:它不给持久目录的话,装好 Node 也没用
    progress(send, 0.02, line(locale, "检查 Node.js", "Checking Node.js"))
    node = node_info(locale)
    # 同一时刻只有一个在装:两次准备同时跑,会在同一个 node_modules 里各装各的
    try:
        with exclusive(workspace(locale) / "setup.lock", locale=locale, timeout=SETUP_TIMEOUT):
            installed = install_dependencies(node, locale, send, deadline)
            progress(send, 0.62, line(locale, "同步工程", "Syncing the project"))
            project = project_dir(locale)
            browser = prepare_browser(node, project, locale, send, deadline)
    except TimedOut as exc:
        raise PluginError(line(locale, "另一次「准备渲染环境」还没结束,等它跑完再试。",
                               "Another \"Prepare the renderer\" run is still going; try again when it finishes.")) from exc
    source = {"configured": line(locale, "你配置的浏览器", "your configured browser"),
              "remotion": line(locale, "Remotion 自带的浏览器", "Remotion's own browser"),
              "system": line(locale, "本机的 Chrome / Edge", "the local Chrome / Edge")}[browser["source"]]
    return {
        "node": f"v{node.version}",
        "browser": browser["source"],
        "summary": line(
            locale,
            f"渲染环境就绪{'(依赖刚装好)' if installed else ''},渲染用{source}。",
            f"Ready to render{' (dependencies just installed)' if installed else ''}, using {source}.",
        ),
    }


def remotion_explainer(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    deadline = time.monotonic() + RENDER_TIMEOUT
    props = explainer_props(payload, locale)
    node, project, browser = ensure_ready(locale)
    output, name = _output_path(payload, "explainer", locale)
    progress(send, 0.02, line(locale, "准备画面", "Preparing"))
    result = render(node, project, browser, "Explainer", props, output, locale, send, deadline)
    return {
        "artifact": {"path": name},
        "seconds": result.get("seconds"), "width": result.get("width"), "height": result.get("height"),
        "summary": line(locale, f"讲解视频已生成,{result.get('seconds')} 秒", f"Explainer rendered, {result.get('seconds')}s"),
    }


def remotion_animation(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    deadline = time.monotonic() + RENDER_TIMEOUT
    code = str(payload.get("code") or "")
    check_animation_code(code, locale)
    try:
        seconds = float(payload.get("seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if not 0.5 <= seconds <= 120:
        raise PluginError(line(locale, "时长(seconds)要在 0.5 到 120 秒之间。", "seconds must be between 0.5 and 120."))
    width, height = _aspect(payload, locale)
    try:
        fps = int(payload.get("fps") or 30)
    except (TypeError, ValueError):
        fps = 0
    if fps not in FPS_CHOICES:
        raise PluginError(line(locale, f"帧率只能是 {'、'.join(map(str, FPS_CHOICES))}。",
                               f"fps must be one of {', '.join(map(str, FPS_CHOICES))}."))
    node, project, browser = ensure_ready(locale)
    # 独立一份工程:同时渲两段自定义动画时,谁也不覆盖谁的 Custom.tsx。
    # 放在工作区里面,node_modules 往上两层就找得到。
    job = fresh_dir(workspace(locale) / "jobs")
    try:
        shutil.copytree(project, job, dirs_exist_ok=True)
        (job / "src" / "Custom.tsx").write_text(code, encoding="utf-8")
        output, name = _output_path(payload, "animation", locale)
        progress(send, 0.02, line(locale, "准备画面", "Preparing"))
        props = {"width": width, "height": height, "fps": fps, "seconds": seconds, "data": payload.get("data")}
        result = render(node, job, browser, "Custom", props, output, locale, send, deadline)
    finally:
        shutil.rmtree(job, ignore_errors=True)
    return {
        "artifact": {"path": name},
        "seconds": result.get("seconds"), "width": width, "height": height,
        "summary": line(locale, f"动画已生成,{result.get('seconds')} 秒", f"Animation rendered, {result.get('seconds')}s"),
    }


TOOLS = {"remotion_setup": remotion_setup, "remotion_explainer": remotion_explainer, "remotion_animation": remotion_animation}


def main() -> None:
    locale = "zh"
    try:
        request = json.loads(sys.stdin.read() or "{}")
        locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
        name = str(request.get("tool"))
        tool = TOOLS.get(name)
        if tool is None:
            raise PluginError(line(locale, f"不认识的工具:{name}", f"Unknown tool: {name}"))
        payload = request.get("input") or {}
        if not isinstance(payload, dict):
            raise PluginError(line(locale, "input 要是一个 JSON 对象。", "input must be a JSON object."))
        emit({"ok": True, "output": tool(payload, locale, emit)})
    except PluginError as exc:
        emit({"ok": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 —— 插件的异常要变成一句话,不能只剩一个栈
        import traceback

        traceback.print_exc(file=sys.stderr)
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
