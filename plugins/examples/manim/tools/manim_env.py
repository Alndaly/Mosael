"""Manim 跑在哪个 Python 里、缺什么、怎么补。

## 两种来源

- **插件自己的虚拟环境(默认)**:用跑插件的那个 Python(随 Mosael 发的独立 CPython)在持久目录
  `MOSAEL_PLUGIN_DATA_DIR/venv` 里建一个 venv,pip 装**锁定版本**的 manim。插件更新不重装(持久目录
  跨更新),锁定的版本一变就重装。
- **你已有的 Python(配置 `PYTHON_EXECUTABLE`)**:已经用 conda / uv 装好了 Manim 的人不必再装一份。

## 系统依赖(这是 Manim 最容易卡住的地方)

- **ffmpeg 不需要**:Manim 0.19 起用 PyAV 编码,PyAV 的二进制包里自带 FFmpeg 的库。
- **cairo / pango**:Windows 上 pycairo、ManimPango 都有现成的二进制包,什么都不用装;macOS 上 ManimPango
  有二进制包,**pycairo 没有**,要从源码编译 —— 需要 Homebrew 的 `cairo`、`pkg-config` 和 Xcode 命令行工具;
  Linux 上两者都要编译,需要 cairo / pango 的开发包和编译器。装之前先查,缺了直接说装哪几个,而不是让
  用户对着一屏 pip 的编译报错。
- **LaTeX 可选**:公式(MathTex / Tex)要 `latex` 和 `dvisvgm`。没有的话讲解视频把公式写成一行 Unicode
  照样出片,并在结果里说明;自定义动画里用了 MathTex 会得到一句「没装 LaTeX」的报错和装法。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from plugin_kit import Emit, PluginError, TimedOut, blame_line, data_dir, exclusive, follow, line, progress

#: 锁定的 Manim 版本。插件的模板、报错整理、进度解析都是对着它测的。
MANIM_VERSION = "0.21.0"
MIN_PYTHON = (3, 11)
#: 装依赖的上限。清单里给 manim_setup 声明了 1200 秒,这里留出收尾的余量。
SETUP_TIMEOUT = 1100
STAMP = ".mosael-installed.json"


# ---------------------------------------------------------------- PATH

def _extra_path_dirs() -> list[str]:
    """PATH 里常常没有、但 Manim 要找的那几处:Homebrew、TeX 发行版的 bin 目录。

    宿主已经把用户登录 shell 的 PATH 带过来了(见 electron/login-shell-path),这里是再保险一层:
    MacTeX 装在 /Library/TeX/texbin,很多人的 shell 配置里并没有它。
    """
    home = Path.home()
    if sys.platform == "darwin":
        candidates = ["/opt/homebrew/bin", "/usr/local/bin", "/Library/TeX/texbin",
                      str(home / "Library" / "TinyTeX" / "bin" / "universal-darwin")]
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        program = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        candidates = [
            os.path.join(local, "Programs", "MiKTeX", "miktex", "bin", "x64"),
            os.path.join(program, "MiKTeX", "miktex", "bin", "x64"),
            os.path.join(roaming, "TinyTeX", "bin", "windows"),
            os.path.join(roaming, "TinyTeX", "bin", "win32"),
        ]
    else:
        candidates = ["/usr/local/bin", "/usr/bin", str(home / ".TinyTeX" / "bin" / "x86_64-linux"),
                      str(home / ".TinyTeX" / "bin" / "aarch64-linux")]
        candidates += [str(one) for one in sorted(Path("/usr/local/texlive").glob("*/bin/*"))[-1:]]
    return [one for one in candidates if one and Path(one).is_dir()]


def search_path() -> str:
    parts = [one for one in os.environ.get("PATH", "").split(os.pathsep) if one]
    for extra in _extra_path_dirs():
        if extra not in parts:
            parts.append(extra)
    return os.pathsep.join(parts)


def child_env() -> dict[str, str]:
    """给 pip / manim 子进程的环境:宿主给的最小环境 + 补全的 PATH + 让输出好读的几个开关。"""
    env = dict(os.environ)
    env["PATH"] = search_path()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # rich 按终端宽度折行;宽一点,报错里的路径和消息不被折成好几截
    env["COLUMNS"] = "160"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def which(name: str) -> str:
    return shutil.which(name, path=search_path()) or ""


# ---------------------------------------------------------------- Python

def venv_dir(locale: str) -> Path:
    return data_dir(locale) / "venv"


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def configured_python() -> str:
    return os.environ.get("PYTHON_EXECUTABLE", "").strip()


def _run(args: list[str], timeout: float, **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=child_env(), stdin=subprocess.DEVNULL, **kwargs)


PROBE = (
    "import json, sys\n"
    "info = {'python': sys.version.split()[0]}\n"
    "try:\n"
    "    import manim\n"
    "    info['manim'] = manim.__version__\n"
    "except Exception as exc:\n"
    "    info['error'] = type(exc).__name__ + ': ' + str(exc)\n"
    "print(json.dumps(info))\n"
)


def probe(python: str) -> dict[str, Any]:
    """问这个 Python:你是几版、manim 装了没有、是哪一版。跑不起来返回 {'error': …}。"""
    try:
        done = _run([python, "-c", PROBE], timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    for raw in reversed(done.stdout.strip().splitlines()):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {"error": (done.stderr or done.stdout).strip()[-500:] or f"exit {done.returncode}"}


def _stamp(venv: Path) -> dict[str, Any]:
    try:
        return json.loads((venv / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def installed_ready(locale: str) -> bool:
    venv = venv_dir(locale)
    return venv_python(venv).is_file() and _stamp(venv).get("manim") == MANIM_VERSION


def render_python(locale: str) -> str:
    """渲染用哪个 Python。没准备好就说去跑「准备 Manim 环境」—— 渲染不顺手装:

    装一次要一到几分钟(macOS / Linux 上还要编译 pycairo),而渲染工具的预算是按「智能体一次最多等
    180 秒」定的;在渲染里装,多半是装到一半被掐掉,留下一个半截的环境。
    """
    configured = configured_python()
    if configured:
        if not Path(configured).is_file():
            raise PluginError(line(locale, f"配置的 Python 不存在:{configured}",
                                   f"The configured Python does not exist: {configured}"))
        return configured
    venv = venv_dir(locale)
    if not installed_ready(locale):
        raise PluginError(line(
            locale,
            "Manim 还没装好。先在「插件 → Manim 教学动画」里运行一次「准备 Manim 环境」(第一次要一到几分钟)。",
            "Manim is not installed yet. Run \"Prepare Manim\" once from Plugins → Manim first (the first run takes a few minutes).",
        ))
    return str(venv_python(venv))


# ---------------------------------------------------------------- 系统依赖

def latex_status() -> dict[str, Any]:
    latex, dvisvgm = which("latex"), which("dvisvgm")
    return {"latex": latex, "dvisvgm": dvisvgm, "ok": bool(latex and dvisvgm)}


def latex_hint(locale: str) -> str:
    if sys.platform == "darwin":
        return line(locale,
                    "装 MacTeX(https://www.tug.org/mactex/,或 `brew install --cask mactex-no-gui`),装好后重启 Mosael。",
                    "Install MacTeX (https://www.tug.org/mactex/, or `brew install --cask mactex-no-gui`) and restart Mosael.")
    if sys.platform == "win32":
        return line(locale,
                    "装 MiKTeX(https://miktex.org/download),安装时选「缺的宏包自动安装」,装好后重启 Mosael。",
                    "Install MiKTeX (https://miktex.org/download), allow it to install missing packages on the fly, then restart Mosael.")
    return line(locale,
                "装 TeX Live:`sudo apt install texlive texlive-latex-extra dvisvgm`(其它发行版装同名包),装好后重启 Mosael。",
                "Install TeX Live: `sudo apt install texlive texlive-latex-extra dvisvgm` (same packages elsewhere), then restart Mosael.")


def _pkg_config_has(module: str) -> bool:
    pkg = which("pkg-config")
    if not pkg:
        return False
    try:
        return _run([pkg, "--exists", module], timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _has_compiler() -> bool:
    if sys.platform == "darwin":
        try:
            return _run(["xcrun", "--find", "clang"], timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return bool(which("clang") or which("cc"))
    return bool(which("cc") or which("gcc") or which("clang"))


def missing_build_tools(locale: str) -> list[str]:
    """装 manim 之前要先有的系统组件。**只在要编译的平台上查**(Windows 全是现成的二进制包)。"""
    if sys.platform == "win32":
        return []
    missing: list[str] = []
    if sys.platform == "darwin":
        if not which("pkg-config") or not _pkg_config_has("cairo"):
            missing.append(line(locale, "cairo 与 pkg-config:终端里运行 `brew install cairo pkg-config`(没有 Homebrew 先装 https://brew.sh)",
                                "cairo and pkg-config: run `brew install cairo pkg-config` (install Homebrew from https://brew.sh first)"))
        if not _has_compiler():
            missing.append(line(locale, "Xcode 命令行工具:终端里运行 `xcode-select --install`",
                                "Xcode command line tools: run `xcode-select --install`"))
        return missing
    if not which("pkg-config") or not _pkg_config_has("cairo") or not _pkg_config_has("pangocairo"):
        missing.append(line(
            locale,
            "cairo / pango 开发包:Debian/Ubuntu 运行 `sudo apt install build-essential pkg-config libcairo2-dev libpango1.0-dev`;"
            "Fedora 运行 `sudo dnf install gcc pkg-config cairo-devel pango-devel`",
            "cairo / pango development files: on Debian/Ubuntu run `sudo apt install build-essential pkg-config libcairo2-dev libpango1.0-dev`; "
            "on Fedora run `sudo dnf install gcc pkg-config cairo-devel pango-devel`",
        ))
    elif not _has_compiler():
        missing.append(line(locale, "C 编译器:`sudo apt install build-essential`", "A C compiler: `sudo apt install build-essential`"))
    return missing


# ---------------------------------------------------------------- 安装

#: pip 输出里的几个路标 → 大致进度。依赖大约四十个包。
_COLLECTING = re.compile(r"^Collecting (\S+)")
_BUILDING = re.compile(r"Building wheel for (\S+)")


def _pip(args: list[str], send: Emit, locale: str, *, timeout: float, start: float, span: float) -> tuple[int, list[str]]:
    """跑 pip,边读边报进度(看取消、看时限都在 plugin_kit.follow 里)。返回 (退出码, 输出)。"""
    collected = [0]

    def on_line(_stream: str, text: str) -> None:
        text = text.rstrip()
        if match := _COLLECTING.match(text):
            collected[0] += 1
            progress(send, start + span * min(0.7, collected[0] / 45),
                     line(locale, f"下载 {match.group(1)}", f"Downloading {match.group(1)}"))
        elif match := _BUILDING.search(text):
            progress(send, start + span * 0.75, line(locale, f"编译 {match.group(1)}(要一两分钟)",
                                                     f"Building {match.group(1)} (a minute or two)"))
        elif text.startswith("Installing collected packages"):
            progress(send, start + span * 0.85, line(locale, "安装依赖", "Installing packages"))

    try:
        done = follow(args, locale=locale, timeout=timeout, env=child_env(), on_line=on_line, tail=4000)
    except TimedOut as exc:
        raise PluginError(_install_timed_out(locale)) from exc
    return done.returncode, list(done.tail)


def _install_timed_out(locale: str) -> str:
    return line(
        locale,
        "安装超时。网络慢的话在插件配置里填一个 PyPI 镜像(如 https://pypi.tuna.tsinghua.edu.cn/simple)再试。",
        "Installation timed out. On a slow network, set a PyPI mirror in the plugin settings and try again.",
    )


def install(send: Emit, locale: str, *, reinstall: bool = False) -> bool:
    """建 venv、装锁定版本的 manim。已经是这一份就什么都不做;返回是否真的装了。

    **同一时刻只有一个在装**(`exclusive`):两次「准备 Manim 环境」同时跑,会一个删掉另一个装到一半的 venv。
    后到的那个等前一个装完,再看一眼 —— 多半已经是这一份了,什么都不用做。
    """
    deadline = time.monotonic() + SETUP_TIMEOUT
    venv = venv_dir(locale)
    try:
        with exclusive(data_dir(locale) / "venv.lock", locale=locale, timeout=SETUP_TIMEOUT):
            if installed_ready(locale) and not reinstall and "error" not in probe(str(venv_python(venv))):
                return False
            _build(send, locale, venv, deadline)
    except TimedOut as exc:
        raise PluginError(_install_timed_out(locale)) from exc
    return True


def _build(send: Emit, locale: str, venv: Path, deadline: float) -> None:
    if sys.version_info < MIN_PYTHON:
        raise PluginError(line(
            locale,
            f"跑插件的 Python 是 {sys.version.split()[0]},Manim 需要 3.11 或更新。可以在插件配置里填一个装好 Manim 的 Python。",
            f"The plugin's Python is {sys.version.split()[0]}; Manim needs 3.11+. Set a Python with Manim installed in the plugin settings.",
        ))
    missing = missing_build_tools(locale)
    if missing:
        raise PluginError(line(locale, "装 Manim 之前还缺:\n", "Manim needs these first:\n")
                          + "\n".join(f"- {one}" for one in missing)
                          + line(locale, "\n装好后重启 Mosael,再运行一次「准备 Manim 环境」。",
                                 "\nInstall them, restart Mosael and run \"Prepare Manim\" again."))
    progress(send, 0.02, line(locale, "建立 Python 虚拟环境", "Creating a Python virtual environment"))
    shutil.rmtree(venv, ignore_errors=True)
    created = _run([sys.executable, "-m", "venv", str(venv)], timeout=300)
    if created.returncode != 0 or not venv_python(venv).is_file():
        raise PluginError(line(locale, "建立虚拟环境失败:", "Creating the virtual environment failed: ")
                          + (created.stderr or created.stdout).strip()[-600:])
    args = [str(venv_python(venv)), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
            "--progress-bar", "off", f"manim=={MANIM_VERSION}"]
    index = os.environ.get("PIP_INDEX_URL", "").strip()
    if index:
        args += ["--index-url", index]
    progress(send, 0.05, line(locale, f"安装 Manim {MANIM_VERSION}", f"Installing Manim {MANIM_VERSION}"))
    code, output = _pip(args, send, locale, timeout=max(1.0, deadline - time.monotonic()), start=0.05, span=0.85)
    if code != 0:
        raise PluginError(line(locale, "安装 Manim 失败:", "Installing Manim failed: ") + explain_pip_failure(output, locale))
    (venv / STAMP).write_text(json.dumps({"manim": MANIM_VERSION, "python": sys.version.split()[0]}), encoding="utf-8")


def explain_pip_failure(output: list[str], locale: str) -> str:
    """pip 失败的输出很长;挑出能让人动手的那一句。编译 pycairo / manimpango 失败几乎总是缺系统依赖。"""
    text = "\n".join(output)
    if re.search(r"(pycairo|manimpango|ManimPango)", text) and re.search(
        r"(cairo|pango).*(not found|No package)|Dependency .* not found|pkg-config", text, re.I):
        hint = missing_build_tools(locale)
        base = line(locale, "编译 pycairo / ManimPango 时找不到 cairo 或 pango。", "Building pycairo / ManimPango could not find cairo or pango.")
        return base + ("\n" + "\n".join(f"- {one}" for one in hint) if hint else "")
    return blame_line(text, fallback=output[-1] if output else "")
