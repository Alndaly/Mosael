"""本机服务(ADR 0041):宿主替这个插件起停一台本机 ComfyUI。怎么认一个装好的目录、怎么起、缺什么补什么,都在这里。

宿主经 `comfyui_generation` 这个工具按 op 问(见 main):

    {"op": "service_detect", "directory", "python"?}  → 认没认出来、摆给人看的事实、问题,以及能不能补装 pysssss
    {"op": "service_launch", "directory", "python"?, "port", "listen_lan", "extra_args", "shared_models", "config_dir"}
                                                      → argv / env / cwd / 健康检查的路径 / 第一次就绪最多等多久
    {"op": "service_add_nodes", "directory", "python"?} → 把钉死版本的 pysssss 解进 custom_nodes(用户点头之后)
    {"op": "service_discover"}                         → 本机 8188 / 8000(Desktop 的缺省端口)上有没有已经在跑的
    {"op": "service_readdress", "from", "to"}           → 端口改了:按旧地址存的本地数据搬到新地址名下
    {"op": "service_busy"}                             → 闲置自动停之前:它的任务队列里有没有在跑、在排的(问那台服务器)

「让 Mosael 装」的两个(`service_plan` / `service_install`)在 managed:装好的那一份就是一个普通的目录(源码旁边一个
`.venv`),认目录、怎么起都走这里。

**只描述、不起进程** —— 起、停、看健康、收日志是宿主的事。认目录时会试跑一次 `import torch`(30 秒上限),
那一步宿主先问过人。**不改用户的安装**:补装 pysssss 之外,不往那个目录里写任何东西 —— 共用的模型文件夹那份配置写在宿主给的
`config_dir`(数据目录里这个连接的那一格)里,见 shared_models。

**Windows 的路径**全在这里认(便携版 `python_embeded\\python.exe`、venv 的 `Scripts\\python.exe`);函数都带
`windows` 参数,测试在 mac 上用夹具目录把两边都走一遍。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pinned
import shared_models
from comfy_http import Comfy
from lines import ComfyError, say

#: 健康检查问这条:ComfyUI 起来以后它立刻回一份系统信息(显卡、版本),比首页轻。
HEALTH_PATH = "/system_stats"
#: 第一次启动最多等多久就绪:要解包前端、加载自定义节点,装得多的机器一两分钟很正常。
READY_TIMEOUT_SECONDS = 180
#: 试跑 `import torch` 最多等多久。第一次导入 torch 要把几百 MB 的库读进来。
TRIAL_TIMEOUT_SECONDS = 30
#: 问「装没装 Manager 的 pip 包」最多等多久(不导入 torch,只找包)。
PROBE_TIMEOUT_SECONDS = 10
#: 本机发现去问这几个端口:8188 是 ComfyUI 自己的缺省,8000 是官方 ComfyUI Desktop 的。
DISCOVER_PORTS = (8188, 8000)
DISCOVER_TIMEOUT_SECONDS = 1.5

#: pysssss(ComfyUI-Custom-Scripts):模型库的 Range 读、算哈希、存预览图靠它。**钉死一个提交**,按 sha256 校验 ——
#: 下载走代理、走镜像都换不了内容(见 pinned)。要升级就换提交和 sha256(和测试里的那一份)。那个包 140 KB、解开 500 多 KB;
#: 个数、大小的上限只防一个不对的下载。
PYSSSSS_COMMIT = "609f3afaa74b2f88ef9ce8d939626065e3247469"
PYSSSSS = pinned.Archive(
    name=f"pysssss({PYSSSSS_COMMIT[:7]})",
    url=f"https://codeload.github.com/pythongosssss/ComfyUI-Custom-Scripts/tar.gz/{PYSSSSS_COMMIT}",
    sha256="0146fa4f61e09281e82bee34098a9c1f6703442c163dcbf527cd396c4b941844",
    size=140_477,
    max_members=2000,
    max_unpacked=100 * 1024 * 1024,
)
PYSSSSS_DIR = "ComfyUI-Custom-Scripts"
#: 克隆进 custom_nodes 的老 ComfyUI-Manager(3.x)的目录(认的时候不分大小写)。Mosael 不支持它,认目录时提醒换 pip 版。
OLD_MANAGER_DIR = "comfyui-manager"

#: 端口和监听地址由宿主给(建连接时选定、局域网开关),写在附加参数里会和它打架。
_HOST_FLAGS = ("--port", "--listen")

#: 试跑的那几行:导入 torch,看能用哪种显卡,顺带看装没装 Manager 的 pip 包、`WANTED` 里的包缺哪几个(只认装没装,不比版本;
#: 包名的大小写和 `-` / `_` 由 importlib.metadata 自己归一,ComfyUI 要的 Python 3.10 起都这样)。
#: 只打印一行 JSON(带前缀,前面别的输出不管)。`WANTED` 由 `_trial_code` 写在最前面。
_TRIAL = r"""
import importlib.metadata, importlib.util, json, platform, subprocess, sys
out = {"python": platform.python_version()}
out["manager"] = importlib.util.find_spec("comfyui_manager") is not None
missing = []
for name in WANTED:
    try:
        importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        missing.append(name)
    except Exception:
        pass
out["missing"] = missing
try:
    import torch
except Exception as exc:
    out["torch_error"] = f"{type(exc).__name__}: {exc}"
else:
    out["torch"] = str(torch.__version__)
    try:
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            out.update(device="cuda", gpu=props.name, vram=int(props.total_memory), cuda=str(torch.version.cuda or ""))
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            out["device"] = "mps"
            try:
                out["gpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                            text=True, timeout=5).stdout.strip()
                out["vram"] = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                                 timeout=5).stdout.strip() or 0)
            except Exception:
                pass
        else:
            out["device"] = "cpu"
    except Exception as exc:
        out.update(device="cpu", device_error=str(exc))
print("MOSAEL_TRIAL " + json.dumps(out), flush=True)
"""
_MANAGER_PROBE = "import importlib.util; print('MOSAEL_TRIAL ' + str(importlib.util.find_spec('comfyui_manager') is not None))"
#: requirements.txt 里一行开头的包名(后面的版本、extras、环境标记不管)。
_REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
#: ComfyUI 的 requirements.txt 用这句注释隔开非必需的那几个(kornia、spandrel……):缺了照样起得来。
_NON_ESSENTIAL = "non essential"
#: 缺的包在问题里最多列几个。
MISSING_SHOWN = 8


def _is_windows() -> bool:
    return os.name == "nt"


# --- 认目录 -------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """认出来的 ComfyUI:`root` 是有 main.py 和 comfy/ 的那一层;便携版时 `portable` 是外层(有 python_embeded/)。"""

    root: Path
    portable: Path | None = None


def find_layout(directory: Path) -> Layout | None:
    """用户选的目录 → ComfyUI 在哪。Windows 便携版的两种选法都认:外层的 `ComfyUI_windows_portable`(里面是 `ComfyUI/`
    和 `python_embeded/`),或者里面那层 `ComfyUI/`。"""
    for candidate in (directory, directory / "ComfyUI"):
        if (candidate / "main.py").is_file() and (candidate / "comfy").is_dir():
            outer = candidate.parent if candidate == directory else directory
            return Layout(candidate, outer if (outer / "python_embeded").is_dir() else None)
    return None


def venv_python(venv: Path, *, windows: bool) -> Path | None:
    """一个 venv 里的解释器:Windows 上是 `Scripts\\python.exe`,别处是 `bin/python`(没有就 `bin/python3`)。"""
    names = (("Scripts", "python.exe"),) if windows else (("bin", "python"), ("bin", "python3"))
    for folder, name in names:
        found = venv / folder / name
        if found.is_file():
            return found
    return None


def find_python(layout: Layout, given: str, *, windows: bool) -> tuple[Path | None, str]:
    """用哪个 Python 起它,和它是怎么认出来的(`user` / `portable` / `venv` / `none`)。

    用户指定了就用他指的(他知道 conda、系统 Python 在哪,也可能 venv 是坏的);没指定按顺序:便携版自带的
    `python_embeded`、目录里或上一层的 `venv` / `.venv`。都没有就是 `none` —— 请用户指一个。"""
    if given:
        path = Path(given).expanduser()
        return (path, "user") if path.is_file() else (None, "user")
    if layout.portable is not None:
        embedded = layout.portable / "python_embeded" / ("python.exe" if windows else "python")
        if embedded.is_file():
            return embedded, "portable"
    for base in (layout.root, layout.root.parent):
        for name in ("venv", ".venv"):
            found = venv_python(base / name, windows=windows)
            if found is not None:
                return found, "venv"
    return None, "none"


def comfyui_version(root: Path) -> str:
    """ComfyUI 自己写在 `comfyui_version.py` 里的版本(只读文件,不运行它)。"""
    try:
        text = (root / "comfyui_version.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
    return found.group(1) if found else ""


def _custom_node(root: Path, name: str) -> Path | None:
    """custom_nodes 下叫这个名字(不分大小写:Manager 装的是小写的那种)的目录。"""
    folder = root / "custom_nodes"
    try:
        entries = list(folder.iterdir())
    except OSError:
        return None
    return next((one for one in entries if one.is_dir() and one.name.lower() == name.lower()), None)


def _old_manager_steps(layout: Layout, python: Path | None) -> tuple[str, str]:
    """只有老 Manager 时怎么换成 pip 版(中、英):装 manager_requirements.txt、启动加 --enable-manager。ComfyUI 老到还没有
    那个文件(0.4.0 起才有)就先升级。"""
    requirements = layout.root / "manager_requirements.txt"
    if not requirements.is_file():
        return ("这个 ComfyUI 还没有 manager_requirements.txt(0.4.0 起才有):先升级 ComfyUI,再装 pip 版、启动时加 --enable-manager",
                "This ComfyUI has no manager_requirements.txt yet (it comes with 0.4.0): update ComfyUI first, then install the "
                "pip version and start with --enable-manager")
    install = f"{python or 'python'} -m pip install -r {requirements}"
    return (f"在这个环境里装上 pip 版:{install};启动时加 --enable-manager(Mosael 起它时会自己加)",
            f"Install the pip version in this environment: {install}, then start with --enable-manager (Mosael adds it "
            f"when it starts ComfyUI)")


def required_packages(root: Path) -> list[str]:
    """ComfyUI 自己的 requirements.txt 里必需的那几个包名(「non essential」那句注释以下的不算)。读不到就是空的 —— 不报缺。

    只读这个文件,不运行它;缺不缺由试跑那几行在用户的解释器里查(torch 能导入不等于 ComfyUI 起得来:一个只装了 torch 的
    conda base 起 ComfyUI 0.38 会因为缺 alembic、comfy-aimdo 直接退出 —— 真机上撞到过)。"""
    try:
        text = (root / "requirements.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and _NON_ESSENTIAL in stripped.lower():
            break
        stripped = stripped.split("#", 1)[0].strip()
        if not stripped or stripped.startswith(("-", "git+", "http:", "https:")):
            continue
        found = _REQUIREMENT_NAME.match(stripped)
        if found:
            names.append(found.group(0))
    return names


def _trial_code(wanted: list[str]) -> str:
    """试跑的那几行,前面写上要查的包名(包名只有字母数字和 `._-`,repr 出来就是一个合法的列表)。"""
    return f"WANTED = {wanted!r}\n" + _TRIAL


def _run_python(python: Path, code: str, cwd: Path, timeout: float) -> str | None:
    """用那个 Python 跑几行,交回带前缀的那一行(去掉前缀);超时抛 TimeoutExpired,跑不起来回 None。"""
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if _is_windows() else {}  # type: ignore[attr-defined]
    result = subprocess.run([str(python), "-c", code], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, **flags)
    for line in reversed((result.stdout or "").splitlines()):
        if line.startswith("MOSAEL_TRIAL "):
            return line[len("MOSAEL_TRIAL "):]
    return None if result.returncode == 0 else (result.stderr or "").strip()[-400:] or None


def _gb(value: Any) -> str:
    return f"{round(float(value) / 1024 ** 3)} GB" if isinstance(value, (int, float)) and value > 0 else ""


def detect(payload: dict[str, Any], locale: str, *, windows: bool | None = None) -> dict[str, Any]:
    windows = _is_windows() if windows is None else windows
    raw = str(payload.get("directory") or "").strip()
    given = str(payload.get("python") or "").strip()
    facts: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []

    def fact(zh: str, en: str, value: str) -> None:
        facts.append({"label": {"zh": zh, "en": en}, "value": value})

    def problem(level: str, zh: str, en: str) -> None:
        problems.append({"level": level, "text": {"zh": zh, "en": en}})

    layout = find_layout(Path(raw).expanduser()) if raw else None
    if layout is None:
        problem("error", f"这个目录里认不出 ComfyUI:要选有 main.py 和 comfy/ 的那一层(Windows 便携版选外层的 "
                         f"ComfyUI_windows_portable 也行)\n{raw}",
                f"No ComfyUI found in this folder. Choose the one with main.py and comfy/ (for the Windows portable "
                f"build, the outer ComfyUI_windows_portable works too)\n{raw}")
        return {"ok": False, "facts": facts, "problems": problems, "add_nodes": None}

    version = comfyui_version(layout.root)
    fact("ComfyUI 版本", "ComfyUI version", version or "?")
    fact("位置", "Location", str(layout.root) + (say(locale, "(便携版)", " (portable)") if layout.portable else ""))
    python, source = find_python(layout, given, windows=windows)
    manager_pip = False
    torch_ok = False
    if python is None:
        if source == "user":
            problem("error", f"指定的 Python 不存在:{given}", f"The Python you chose doesn't exist: {given}")
        else:
            problem("error", "找不到 ComfyUI 用的 Python:目录里和上一层都没有 venv / .venv,也不是便携版。在下面指一个"
                             "(conda、系统里的 Python 都行)",
                    "Can't find the Python ComfyUI uses: there's no venv / .venv in this folder or the one above, and it "
                    "isn't the portable build. Choose one below (a conda or system Python works too)")
    else:
        try:
            said = _run_python(python, _trial_code(required_packages(layout.root)), layout.root, TRIAL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            said = None
            problem("error", f"试跑 import torch 超过 {TRIAL_TIMEOUT_SECONDS} 秒没回来:这个 Python 可能卡在初始化显卡上",
                    f"The trial import torch didn't finish within {TRIAL_TIMEOUT_SECONDS} seconds; this Python may be "
                    f"stuck initialising the GPU")
        except OSError as exc:
            said = None
            problem("error", f"这个 Python 跑不起来:{exc}", f"This Python won't run: {exc}")
        trial: dict[str, Any] = {}
        if said is not None:
            try:
                trial = json.loads(said)
            except ValueError:
                problem("error", f"这个 Python 跑不起来:{said}", f"This Python won't run: {said}")
        if trial:
            fact("Python", "Python", say(locale, f"{python}({trial.get('python', '?')})", f"{python} ({trial.get('python', '?')})"))
            manager_pip = trial.get("manager") is True
            if trial.get("torch_error"):
                problem("error", f"这个 Python 导入不了 torch,ComfyUI 起不来:{trial['torch_error']}。先在这个环境里装好 torch",
                        f"This Python can't import torch, so ComfyUI won't start: {trial['torch_error']}. Install torch "
                        f"in this environment first")
            elif trial.get("torch"):
                torch_ok = True
                fact("PyTorch", "PyTorch", str(trial["torch"]))
                device = trial.get("device")
                memory = _gb(trial.get("vram"))
                if device in ("cuda", "mps"):
                    if device == "cuda":
                        kind = f"CUDA {trial.get('cuda') or ''}".strip()
                        size = say(locale, f"显存 {memory}", f"{memory} VRAM") if memory else ""
                    else:
                        kind = "MPS"
                        size = say(locale, f"统一内存 {memory}", f"{memory} unified memory") if memory else ""
                    fact("显卡", "GPU", " · ".join(one for one in (kind, str(trial.get("gpu") or ""), size) if one))
                else:
                    fact("显卡", "GPU", say(locale, "只有 CPU", "CPU only"))
                    problem("warning", "torch 用不了显卡(MPS / CUDA),只能用 CPU 跑,会非常慢",
                            "torch can't use a GPU (MPS / CUDA), so it runs on the CPU only and will be very slow")
            # torch 缺不缺上面已经说过了
            missing = [str(name) for name in trial.get("missing") or [] if str(name).lower() != "torch"]
            if missing:
                more = len(missing) - MISSING_SHOWN
                shown_zh = "、".join(missing[:MISSING_SHOWN]) + (f" 等 {len(missing)} 个" if more > 0 else "")
                shown_en = ", ".join(missing[:MISSING_SHOWN]) + (f" and {more} more" if more > 0 else "")
                install = f"{python} -m pip install -r {layout.root / 'requirements.txt'}"
                problem("error", f"这个 Python 缺 ComfyUI 要的包,ComfyUI 起不来:{shown_zh}。在这个环境里装上({install}),"
                                 f"或者指另一个装好了的 Python",
                        f"This Python is missing packages ComfyUI needs, so ComfyUI won't start: {shown_en}. Install them "
                        f"in this environment ({install}) or choose another Python that has them")
    # Manager 只认 pip 包(V4,ComfyUI 0.4.0 起自带)。克隆进 custom_nodes 的老 Manager 不支持:提醒一句,不碰那个目录
    if manager_pip:
        fact("ComfyUI-Manager", "ComfyUI-Manager", say(locale, "pip 包(启动时加 --enable-manager)",
                                                      "pip package (started with --enable-manager)"))
    else:
        fact("ComfyUI-Manager", "ComfyUI-Manager", say(locale, "没装", "not installed"))
        old = _custom_node(layout.root, OLD_MANAGER_DIR)
        if old is not None:
            zh, en = _old_manager_steps(layout, python)
            problem("warning", f"custom_nodes/{old.name} 是老的 ComfyUI-Manager,Mosael 不支持:装缺的节点包、经它下模型要 pip 版"
                               f"(V4)。{zh}",
                    f"custom_nodes/{old.name} is the old ComfyUI-Manager, which Mosael doesn't support: installing missing node "
                    f"packs and downloading models through it need the pip version (V4). {en}")
        else:
            problem("warning", "没装 ComfyUI-Manager:工作流库里缺的节点包要自己装",
                    "ComfyUI-Manager isn't installed: you'll have to install missing node packs for the workflow library yourself")
    pysssss = _custom_node(layout.root, PYSSSSS_DIR)
    fact("ComfyUI-Custom-Scripts(pysssss)", "ComfyUI-Custom-Scripts (pysssss)",
         say(locale, "已装", "installed") if pysssss else say(locale, "没装", "not installed"))
    offer = None
    if pysssss is None:
        target = layout.root / "custom_nodes" / PYSSSSS_DIR
        problem("warning", "没装 ComfyUI-Custom-Scripts(pysssss):模型库的哈希、预览图要靠它",
                "ComfyUI-Custom-Scripts (pysssss) isn't installed: the model library needs it for hashes and preview images")
        offer = {
            "title": {"zh": "补装 pysssss", "en": "Add pysssss"},
            "description": {
                "zh": f"从 GitHub 下载 ComfyUI-Custom-Scripts 固定版本 {PYSSSSS_COMMIT[:7]}(按 sha256 校验),解到 {target}。"
                      f"不动这个目录里别的文件;下次启动 ComfyUI 时生效。",
                "en": f"Downloads ComfyUI-Custom-Scripts at the pinned version {PYSSSSS_COMMIT[:7]} from GitHub (checked by "
                      f"sha256) and unpacks it into {target}. Nothing else in this folder changes; it takes effect the next "
                      f"time ComfyUI starts.",
            },
        }
    blocked = any(one["level"] == "error" for one in problems)
    return {"ok": python is not None and torch_ok and not blocked, "facts": facts, "problems": problems, "add_nodes": offer}


# --- 怎么起 -------------------------------------------------------------------


def manager_pip(python: Path, root: Path) -> bool:
    """那个环境里装没装 Manager 的 pip 包(`comfyui_manager`)。装了就加 `--enable-manager`,没装不加 —— custom_nodes 里的
    老 Manager 不支持,起的时候不看它(照样能起,ComfyUI 自己决定加不加载它)。"""
    try:
        said = _run_python(python, _MANAGER_PROBE, root, PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return said == "True"


def launch(payload: dict[str, Any], locale: str, *, windows: bool | None = None,
           has_manager: Any = manager_pip) -> dict[str, Any]:
    windows = _is_windows() if windows is None else windows
    raw = str(payload.get("directory") or "").strip()
    layout = find_layout(Path(raw).expanduser()) if raw else None
    if layout is None:
        raise ComfyError(say(locale, f"这个目录里认不出 ComfyUI:{raw}", f"No ComfyUI found in this folder: {raw}"))
    given = str(payload.get("python") or "").strip()
    python, source = find_python(layout, given, windows=windows)
    if python is None:
        raise ComfyError(say(locale, f"指定的 Python 不存在:{given}", f"The Python you chose doesn't exist: {given}")
                         if source == "user" else
                         say(locale, "找不到 ComfyUI 用的 Python:在连接页上指一个", "Can't find the Python ComfyUI uses. Choose one on the connection page"))
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        port = 0
    if not 1024 <= port <= 65535:
        raise ComfyError(say(locale, f"端口不对:{payload.get('port')}", f"Invalid port: {payload.get('port')}"))
    extra = [str(one) for one in payload.get("extra_args") or [] if str(one)]
    clash = next((one for one in extra if one.split("=", 1)[0] in _HOST_FLAGS), None)
    if clash is not None:
        raise ComfyError(say(locale, f"端口和监听地址在连接页上改,别写进附加参数:{clash}",
                             f"Change the port and listen address on the connection page, not in the extra arguments: {clash}"))
    argv = [str(python)]
    if source == "portable":
        argv.append("-s")  # 便携版自己的启动脚本也这么起:不读用户目录里的 site-packages
    argv += [str(layout.root / "main.py"), "--listen", "0.0.0.0" if payload.get("listen_lan") is True else "127.0.0.1",
             "--port", str(port)]
    if has_manager(python, layout.root):
        argv.append("--enable-manager")
    # 共用的模型文件夹(ADR 0041 拍板 5):配置写在宿主给的目录里(不写进这个 ComfyUI 目录),交给 ComfyUI 自己的参数;
    # 一处能用的都没有就不加(上一份删掉)。认不出、已经不在了的那一处跳过,不挡着起
    shared = [shared_models.inspect(one, locale, own_models=layout.root / "models")
              for one in payload.get("shared_models") or [] if str(one).strip()]
    written = shared_models.write_config(str(payload.get("config_dir") or ""), shared)
    if written is not None:
        argv += ["--extra-model-paths-config", str(written)]
    argv += extra
    return {
        "argv": argv,
        # 日志写的是文件、不是终端:不带缓冲,宿主那边看日志才跟得上
        "env": {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        "cwd": str(layout.root),
        "health_path": HEALTH_PATH,
        "ready_timeout": READY_TIMEOUT_SECONDS,
    }


# --- 闲置自动停之前 ----------------------------------------------------------------


def busy(payload: dict[str, Any], locale: str, *, comfy: Any) -> dict[str, Any]:
    """`{"op": "service_busy"}`:宿主要因为闲置太久停掉它之前问一句 —— 它的任务队列(`/queue`)里有没有在跑、在排的。
    问不到(没在跑、不应答)就抛:宿主那边问不到就不停。"""
    queue = comfy.get("/queue")
    queue = queue if isinstance(queue, dict) else {}
    running = len(queue.get("queue_running") or [])
    pending = len(queue.get("queue_pending") or [])
    return {"busy": running + pending > 0, "running": running, "pending": pending}


# --- 补装 pysssss ---------------------------------------------------------------


def github_mirror(payload: dict[str, Any]) -> str:
    """宿主在「管理 → 下载源」里配的 GitHub 镜像前缀(经输入的 `sources` 交进来;没配是空串)。"""
    sources = payload.get("sources")
    return str(sources.get("github_mirror") or "").strip() if isinstance(sources, dict) else ""


def install_pysssss(root: Path, locale: str, *, mirror: str = "", is_cancelled=pinned.never,
                    on_bytes=None) -> Path:
    """把钉死版本的 pysssss 解进 `root/custom_nodes/ComfyUI-Custom-Scripts`:先下到 custom_nodes 旁边的临时文件,对上 sha256
    再解(半截的不留下)。补装和「让 Mosael 装」的最后一步都走这里。"""
    target = root / "custom_nodes" / PYSSSSS_DIR
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f".mosael-{uuid.uuid4().hex[:8]}.tar.gz"
    try:
        pinned.download(PYSSSSS, archive, locale, mirror=mirror, is_cancelled=is_cancelled, on_bytes=on_bytes)
        pinned.unpack(archive, target, PYSSSSS, locale, is_cancelled=is_cancelled)
    finally:
        archive.unlink(missing_ok=True)
    return target


def add_nodes(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    raw = str(payload.get("directory") or "").strip()
    layout = find_layout(Path(raw).expanduser()) if raw else None
    if layout is None:
        raise ComfyError(say(locale, f"这个目录里认不出 ComfyUI:{raw}", f"No ComfyUI found in this folder: {raw}"))
    existing = _custom_node(layout.root, PYSSSSS_DIR)
    if existing is not None:
        return {"installed": [], "path": str(existing),
                "message": {"zh": f"已经装着了:{existing}", "en": f"Already installed: {existing}"}}
    target = install_pysssss(layout.root, locale, mirror=github_mirror(payload))
    return {"installed": [PYSSSSS_DIR], "path": str(target),
            "message": {"zh": f"装好了:{target}。下次启动 ComfyUI 时生效", "en": f"Installed in {target}. It takes effect the next time ComfyUI starts"}}


# --- 本机发现、搬数据 -------------------------------------------------------------


def discover(payload: dict[str, Any], locale: str, ports: tuple[int, ...] = DISCOVER_PORTS) -> dict[str, Any]:
    servers = []
    for port in ports:
        url = f"http://127.0.0.1:{port}"
        try:
            # 和连 ComfyUI 的其余请求同一个传输层(comfy_http):不走代理(问的是本机),不发 `Connection: close`
            with Comfy(url, locale) as comfy:
                stats = comfy.get(HEALTH_PATH, timeout=DISCOVER_TIMEOUT_SECONDS)
        except ComfyError:
            continue
        system = stats.get("system") if isinstance(stats, dict) else None
        if not isinstance(system, dict):
            continue  # 回了 JSON 却不是 ComfyUI 的那份:别的程序
        version = str(system.get("comfyui_version") or "")
        servers.append({"url": url, "label": {
            "zh": f"本机的 ComfyUI {version}(端口 {port})".replace("  ", " "),
            "en": f"ComfyUI {version} on this computer (port {port})".replace("  ", " "),
        }})
    return {"servers": servers}


def _server_key(url: str) -> str:
    """按服务器分文件时用的那一截(和 model_files.data_file、tooling 的缓存是同一个算法:地址规整成 Comfy.base 再取 sha1)。"""
    base = (url or "").strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def readdress(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    root = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
    before, after = str(payload.get("from") or ""), str(payload.get("to") or "")
    if not root or not before or not after:
        return {"moved": 0}
    old, new = _server_key(before), _server_key(after)
    moved = 0
    for path in Path(root).glob(f"*-{old}.json"):
        try:
            path.replace(path.with_name(path.name[: -len(f"{old}.json")] + f"{new}.json"))
            moved += 1
        except OSError:
            continue
    return {"moved": moved}


#: op → 处理函数(main 按它分派)。
OPS = {
    "service_detect": detect,
    "service_launch": launch,
    "service_add_nodes": add_nodes,
    "service_discover": discover,
    "service_readdress": readdress,
}


def local_service() -> str:
    """宿主告诉插件:这个连接的服务器归宿主起停(值是服务的 key);空 = 连的是一台别人管的服务器。"""
    return os.environ.get("MOSAEL_LOCAL_SERVICE", "").strip()


__all__ = ["HEALTH_PATH", "Layout", "OPS", "PYSSSSS", "PYSSSSS_DIR", "add_nodes", "busy", "comfyui_version", "detect", "discover",
           "find_layout", "find_python", "github_mirror", "install_pysssss", "launch", "local_service", "readdress",
           "venv_python"]
