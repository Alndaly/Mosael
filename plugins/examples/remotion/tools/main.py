"""Remotion —— 用代码做动画:知识点讲解、公式推导、代码演示、数据图。

## 它是为什么存在的

讲一个知识点、推一条公式、演示一段代码,要的是**准确**:字不能错、公式不能糊、步骤要一条
一条出来。视频生成模型擅长的是画面,不是这个 —— 它会把公式画成像公式的纹理,还要花钱。
Remotion 用 React 写画面、逐帧渲染成 mp4:字就是字,公式由 KaTeX 排版,零生成费用。

## 三个工具

- `remotion_setup`:准备渲染环境(装依赖、备浏览器)。第一次要几十秒到几分钟,之后是空转。
- `remotion_explainer`:给内容(标题、每节要点 / 公式 / 代码 / 提示),套内置模板出片。
- `remotion_animation`:给一段 Remotion 组件代码,想画什么画什么。

## 放在哪儿

依赖(约 200 MB)和浏览器装在 MOSAEL_PLUGIN_DATA_DIR —— 插件更新时插件目录会整个换掉,那里不会。
工程源码(tools/project)每次调用前同步一份过去,所以插件更新后模板立刻是新的。

## 协议

stdin 读一个 JSON 请求 {"tool", "input", "locale"},stdout 写一个 JSON 响应。**stdout 只能有这一行**
—— npm、node 的输出一律截获,不能漏到 stdout 上。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "project"
#: 渲染子进程的上限。插件在清单里给渲染工具声明了 170 秒,这里留出收尾的余量,
#: 超时时自己说一句人话,而不是被宿主直接掐掉。
RENDER_TIMEOUT = 150
SETUP_TIMEOUT = 840
MIN_NODE = 18

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
#: 自定义动画里能 import 的包 —— 工作区里装了的就这些。别的包写了也打包不出来,不如先说清楚。
ALLOWED_IMPORTS = {"react", "remotion", "katex", "katex/dist/katex.min.css"}


class PluginError(RuntimeError):
    """说得出口的失败,原样进工具结果。"""


def line(locale: str, zh: str, en: str) -> str:
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


# ---------------------------------------------------------------- 环境

def data_dir() -> Path:
    raw = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "").strip()
    if not raw:
        raise PluginError("宿主没有给插件持久目录(MOSAEL_PLUGIN_DATA_DIR)—— 请把 Mosael 升级到最新版。")
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace() -> Path:
    return data_dir() / "workspace"


def _run(args: list[str], *, cwd: Path, timeout: float, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def node_binary(locale: str) -> str:
    node = shutil.which("node")
    if not node:
        raise PluginError(line(
            locale,
            f"找不到 Node.js。Remotion 需要 Node.js {MIN_NODE} 或更新版本:到 https://nodejs.org 装好后重启 Mosael。",
            f"Node.js not found. Remotion needs Node.js {MIN_NODE} or newer: install it from https://nodejs.org and restart Mosael.",
        ))
    version = _run([node, "--version"], cwd=HERE, timeout=20).stdout.strip().lstrip("v")
    major = int(version.split(".")[0]) if version.split(".")[0].isdigit() else 0
    if major < MIN_NODE:
        raise PluginError(line(
            locale,
            f"Node.js 版本是 {version or '未知'},Remotion 需要 {MIN_NODE} 或更新。",
            f"Node.js is {version or 'unknown'}; Remotion needs {MIN_NODE} or newer.",
        ))
    return node


def npm_binary(node: str, locale: str) -> str:
    # 优先用和 node 同目录的 npm:PATH 里可能还有另一套旧的。
    for candidate in (Path(node).with_name("npm.cmd"), Path(node).with_name("npm")):
        if candidate.is_file():
            return str(candidate)
    npm = shutil.which("npm")
    if not npm:
        raise PluginError(line(locale, "找不到 npm(它随 Node.js 一起装)。", "npm not found (it ships with Node.js)."))
    return npm


def _stamp() -> str:
    """装好的是哪一份依赖。package.json 一变(插件升级换了版本)就重装。"""
    return hashlib.sha256((SOURCE / "package.json").read_bytes()).hexdigest()[:16]


def dependencies_ready() -> bool:
    ws = workspace()
    return (ws / ".installed").is_file() and (ws / ".installed").read_text().strip() == _stamp() \
        and (ws / "node_modules" / "@remotion" / "renderer").is_dir()


def install_dependencies(node: str, locale: str) -> bool:
    """装依赖。已经是这一份就什么都不做,返回是否真的装了。"""
    ws = workspace()
    ws.mkdir(parents=True, exist_ok=True)
    if dependencies_ready():
        return False
    shutil.copy2(SOURCE / "package.json", ws / "package.json")
    args = [npm_binary(node, locale), "install", "--no-audit", "--no-fund", "--loglevel=error",
            "--cache", str(data_dir() / "npm-cache")]
    registry = os.environ.get("NPM_REGISTRY", "").strip()
    if registry:
        args.append(f"--registry={registry}")
    try:
        done = _run(args, cwd=ws, timeout=SETUP_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise PluginError(line(
            locale,
            "安装依赖超时。国内网络可以在插件配置里把 npm 镜像设成 https://registry.npmmirror.com 再试。",
            "Installing dependencies timed out. Try setting the npm registry in the plugin settings.",
        )) from exc
    if done.returncode != 0:
        raise PluginError(line(locale, "安装依赖失败:", "Installing dependencies failed: ") + _tail(done.stderr or done.stdout))
    (ws / ".installed").write_text(_stamp())
    return True


def sync_project() -> Path:
    """把插件里的工程源码同步到工作区。插件更新后模板立刻生效,node_modules 不动。"""
    target = workspace() / "project"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("render.mjs", "browser.mjs"):
        shutil.copy2(SOURCE / name, target / name)
    shutil.rmtree(target / "src", ignore_errors=True)
    shutil.copytree(SOURCE / "src", target / "src")
    return target


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


def browser_config() -> dict:
    path = workspace() / "browser.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prepare_browser(node: str, project: Path, locale: str) -> dict:
    """定下渲染用哪个浏览器,记进 browser.json。顺序:用户指定的 → Remotion 自己的 → 本机的。"""
    configured = os.environ.get("BROWSER_EXECUTABLE", "").strip()
    if configured:
        if not Path(configured).is_file():
            raise PluginError(line(locale, f"配置的浏览器不存在:{configured}", f"The configured browser does not exist: {configured}"))
        chosen = {"browserExecutable": configured, "chromeMode": "chrome-for-testing", "source": "configured"}
    else:
        try:
            done = _run([node, "browser.mjs"], cwd=project, timeout=SETUP_TIMEOUT, stdin="{}")
            result = _last_json(done.stdout)
        except subprocess.TimeoutExpired:
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
    (workspace() / "browser.json").write_text(json.dumps(chosen), encoding="utf-8")
    return chosen


def ensure_ready(locale: str) -> tuple[str, Path, dict]:
    """渲染前:依赖、工程、浏览器都在。**依赖和浏览器只在缺的时候装。**"""
    data_dir()
    node = node_binary(locale)
    install_dependencies(node, locale)
    project = sync_project()
    browser = browser_config()
    configured = os.environ.get("BROWSER_EXECUTABLE", "").strip()
    stale = (
        not browser
        # 记下的那个浏览器已经不在了(卸了 Chrome、Remotion 的被清掉)
        or (browser.get("browserExecutable") and not Path(browser["browserExecutable"]).is_file())
        # 配置改过了:新填了路径、换了路径,或者清空了 —— 记录要跟着配置走
        or (configured and browser.get("browserExecutable") != configured)
        or (not configured and browser.get("source") == "configured")
    )
    if stale:
        browser = prepare_browser(node, project, locale)
    return node, project, browser


# ---------------------------------------------------------------- 渲染

def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def _last_json(stdout: str) -> dict:
    for raw in reversed((stdout or "").strip().splitlines()):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _output_path(payload: dict, fallback: str) -> tuple[Path, str]:
    out = os.environ.get("MOSAEL_PLUGIN_OUTPUT_DIR", "").strip()
    if not out:
        raise PluginError("宿主没有给产出目录(MOSAEL_PLUGIN_OUTPUT_DIR)。")
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(payload.get("filename") or fallback)).strip("._")[:80] or fallback
    name = stem if stem.lower().endswith(".mp4") else f"{stem}.mp4"
    return Path(out) / name, name


def render(node: str, project: Path, browser: dict, composition: str, input_props: dict, output: Path, locale: str) -> dict:
    request = {
        "projectDir": str(project), "composition": composition, "inputProps": input_props, "output": str(output),
        "browserExecutable": browser.get("browserExecutable"), "chromeMode": browser.get("chromeMode"),
        "licenseKey": os.environ.get("REMOTION_LICENSE_KEY", "").strip() or None,
    }
    try:
        done = _run([node, "render.mjs"], cwd=project, timeout=RENDER_TIMEOUT, stdin=json.dumps(request, ensure_ascii=False))
    except subprocess.TimeoutExpired as exc:
        raise PluginError(line(
            locale,
            f"渲染超过 {RENDER_TIMEOUT} 秒还没完成。把视频缩短(少几节、少几条要点),或拆成几段分别渲染。",
            f"Rendering did not finish within {RENDER_TIMEOUT}s. Shorten the video or split it into parts.",
        )) from exc
    result = _last_json(done.stdout)
    if not result.get("ok"):
        raise PluginError(line(locale, "渲染失败:", "Rendering failed: ") + _clean_error(result.get("error") or done.stderr, project))
    if not output.is_file():
        raise PluginError(line(locale, "渲染说成功了,但没有产出文件。", "Rendering reported success but produced no file."))
    return result


def _clean_error(text: str, project: Path) -> str:
    """把打包 / 渲染的报错整理成**改得动**的样子,交还给写代码的那一方。

    - 有用的是开头那几行(「Custom.tsx:1:49: ERROR: …」),后面是一长串调用栈 —— 取头不取尾,
      栈帧整行去掉。取尾的话,截下来的恰好全是栈。
    - 绝对路径换成相对的:读得懂,也不把用户目录抖出去。两种写法都换 —— macOS 上 /tmp 是
      /private/tmp 的链接,报错里出现的是真实路径。
    """
    text = str(text or "")
    for base in sorted({str(project), os.path.realpath(project), str(workspace()), os.path.realpath(workspace())},
                       key=len, reverse=True):
        text = text.replace(base + os.sep, "")
    text = re.sub(r"\s*\(from [^)]*\)", "", text)  # webpack 加载器的路径:对改代码没有用
    kept = [one for one in text.splitlines() if not one.lstrip().startswith("at ")]
    text = "\n".join(kept).strip()
    return text if len(text) <= 1500 else text[:1500] + "…"


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def explainer_props(payload: dict, locale: str) -> dict:
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
    aspect = str(payload.get("aspect") or "16:9")
    if aspect not in ASPECTS:
        raise PluginError(line(locale, f"画幅只能是 {'、'.join(ASPECTS)}。", f"Aspect must be one of {', '.join(ASPECTS)}."))
    width, height = ASPECTS[aspect]
    summary = [_text(s, 120) for s in (payload.get("summary") or []) if _text(s, 120)][:6]
    return {
        "title": title, "subtitle": _text(payload.get("subtitle"), 120), "label": _text(payload.get("label"), 40),
        "sections": sections, "summary": summary,
        "summaryTitle": line(locale, "要点回顾", "Key takeaways"),
        "theme": "light" if payload.get("theme") == "light" else "dark",
        "accent": str(payload.get("accent") or ""), "width": width, "height": height, "fps": 30,
    }


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

def remotion_setup(payload: dict, locale: str) -> dict:
    data_dir()  # 宿主的问题先说:它不给持久目录的话,装好 Node 也没用
    node = node_binary(locale)
    installed = install_dependencies(node, locale)
    project = sync_project()
    browser = prepare_browser(node, project, locale)
    source = {"configured": line(locale, "你配置的浏览器", "your configured browser"),
              "remotion": line(locale, "Remotion 自带的浏览器", "Remotion's own browser"),
              "system": line(locale, "本机的 Chrome / Edge", "the local Chrome / Edge")}[browser["source"]]
    return {
        "node": _run([node, "--version"], cwd=HERE, timeout=20).stdout.strip(),
        "browser": browser["source"],
        "summary": line(
            locale,
            f"渲染环境就绪{'(依赖刚装好)' if installed else ''},渲染用{source}。",
            f"Ready to render{' (dependencies just installed)' if installed else ''}, using {source}.",
        ),
    }


def remotion_explainer(payload: dict, locale: str) -> dict:
    props = explainer_props(payload, locale)
    node, project, browser = ensure_ready(locale)
    output, name = _output_path(payload, "explainer")
    result = render(node, project, browser, "Explainer", props, output, locale)
    return {
        "artifact": {"path": name},
        "seconds": result.get("seconds"), "width": result.get("width"), "height": result.get("height"),
        "summary": line(locale, f"讲解视频已生成,{result.get('seconds')} 秒", f"Explainer rendered, {result.get('seconds')}s"),
    }


def remotion_animation(payload: dict, locale: str) -> dict:
    code = str(payload.get("code") or "")
    check_animation_code(code, locale)
    try:
        seconds = float(payload.get("seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if not 0.5 <= seconds <= 120:
        raise PluginError(line(locale, "时长(seconds)要在 0.5 到 120 秒之间。", "seconds must be between 0.5 and 120."))
    aspect = str(payload.get("aspect") or "16:9")
    if aspect not in ASPECTS:
        raise PluginError(line(locale, f"画幅只能是 {'、'.join(ASPECTS)}。", f"Aspect must be one of {', '.join(ASPECTS)}."))
    fps = int(payload.get("fps") or 30)
    if fps not in (24, 25, 30, 60):
        fps = 30
    width, height = ASPECTS[aspect]
    node, project, browser = ensure_ready(locale)
    # 独立一份工程:同时渲两段自定义动画时,谁也不覆盖谁的 Custom.tsx。
    # 放在工作区里面,node_modules 往上一层就找得到。
    job = workspace() / "jobs" / uuid.uuid4().hex[:12]
    try:
        shutil.copytree(project, job, ignore=shutil.ignore_patterns("node_modules"))
        (job / "src" / "Custom.tsx").write_text(code, encoding="utf-8")
        output, name = _output_path(payload, "animation")
        props = {"width": width, "height": height, "fps": fps, "seconds": seconds, "data": payload.get("data")}
        result = render(node, job, browser, "Custom", props, output, locale)
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
        tool = TOOLS.get(str(request.get("tool")))
        if tool is None:
            raise PluginError(f"unknown tool: {request.get('tool')}")
        output = tool(dict(request.get("input") or {}), locale)
        json.dump({"ok": True, "output": output}, sys.stdout, ensure_ascii=False)
    except PluginError as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 —— 插件的异常要变成一句话,不能只剩一个栈
        json.dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
