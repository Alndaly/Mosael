"""让 Mosael 装(ADR 0041 §4):在宿主分的目录里装一份钉死版本的 ComfyUI —— 源码、venv、PyTorch、依赖、pysssss。

宿主经 `comfyui_generation` 按 op 问(只在部署管理员点了「让 Mosael 装」并确认之后):

    {"op": "service_plan", "directory", "python", "sources"}
        → 这台机器能不能装、装哪种 PyTorch、要多少空间、分几步(哪几步已经做完)、要从哪几处下载
    {"op": "service_install", "directory", "python", "flavour", "sources", "log", "pip_cache"}
        → 流式:先一行 `{"event": "step", "outline": [...]}` 说有哪几步,之后每一步一行或几行
          `{"event": "step", "key", "state", "done_bytes", "total_bytes", "item"}`;最后交回装好的目录

`directory` 是宿主分的 `<数据目录>/local-services/<连接>/`(不是插件的持久目录:那个卸载插件时一起删,模型也会跟着没),
`python` 是宿主建 venv 用的那个(随包的 CPython),`sources` 是「管理 → 下载源」里的 pip 源、PyTorch 源、GitHub 镜像前缀。
装在里面的样子:

    ComfyUI/              源码(钉死的版本,按 sha256 校验过的压缩包解出来)
    .venv/                用 `python` 建的 venv —— 不叫 `venv-*`:宿主按 Python 小版本清旧 venv 的那条对账不管它
    downloads/            下着的压缩包(解完删掉)
    mosael-install.json   安装记录:做完了哪几步、建 venv 用的 Python 小版本、哪种 PyTorch、源码是哪个版本
    install.lock          装的时候攥着它:同一个目录不会有两次安装(或换版本)一起写
    ComfyUI.previous/     换了版本之后留着的上一版源码,和它的包清单 `pip-freeze-<版本>.txt`(「回到上一版」用;见 versions)

**每一步做完记一笔**,断了(取消、断网、关机)再装一次就从没做完的那一步接着来。Python 小版本变了(Mosael 升级换了随包的
Python),venv 和装进去的包作废、重装,源码、pysssss 和模型不动;PyTorch 的种类变了(换了驱动)只重装 PyTorch。
「试起一次、健康检查通过才算装好」那一步是宿主的(它管进程):这里做完 7 步交回,宿主起一次。

**PyTorch 装哪种全在这里**(最容易出错的一步):

- Apple 芯片 Mac:PyPI 上的就带 MPS(测试场实测),走 pip 源;
- Windows / Linux(x86_64)+ NVIDIA:Windows 上 PyPI 只有 CPU 版,两边都走 PyTorch 自己的 CUDA 源(Linux 上 CUDA 版另要的
  nvidia-cudnn / nccl / cusparselt / nvshmem 和 triton 那个源里也有)。`nvidia-smi` 读驱动版本、显卡、显存和算力,按
  `CUDA_CHANNELS` 挑这块显卡能用、这个驱动撑得住的最高那个(驱动下限两个系统不一样);Linux 还要 glibc 2.28 以上(PyTorch 的包
  是 manylinux_2_28);
- 别的(Intel Mac、AMD、只有 CPU、ARM 的 Windows / Linux)这一版不装,说清楚,建议「用我自己装的」或者连一台服务器。

依赖都**钉死版本**:ComfyUI 的源码包(sha256)、PyTorch 三件(版本号,CUDA 的连同 `+cu130` 这类后缀)、pysssss(sha256)。
要升级就一起换:`COMFYUI_PINNED`、`TORCH`、`CUDA_CHANNELS`(和测试里的那一份)。

pip 那几步和宿主装引擎依赖(core/pip_install)是同一套规矩:`--prefer-binary`、`--timeout 60`、`--retries 10`,完整输出落盘
(宿主给的日志文件),失败时挑结论行、不取尾巴,常见病因说人话 —— 插件进程只有标准库,碰不到宿主的代码,所以照抄了一份,
双语,并按这一步说下一步该换哪个源。
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pinned
import service
from lines import ComfyError, say

Emit = Callable[[dict[str, Any]], None]

# --- 钉死的版本 ------------------------------------------------------------------

def _comfyui(version: str, sha256: str, size: int) -> pinned.Archive:
    """ComfyUI 一个版本的源码包(codeload 现打包、不给 Content-Length;12 MB 上下,解开一千四五百个文件、近 50 MB)。"""
    return pinned.Archive(name=f"ComfyUI {version}",
                          url=f"https://codeload.github.com/comfyanonymous/ComfyUI/tar.gz/refs/tags/v{version}",
                          sha256=sha256, size=size, max_members=10_000, max_unpacked=400 * 1024 * 1024)


#: **钉死的 ComfyUI 版本**,从旧到新;sha256 都在测试场下过两次一致。最后那个是新装时装的、「更新 ComfyUI」更新到的;前一个留着:
#: 装着它的能更新上来(「回到上一版」用的是更新前留在旁边的那一份源码和依赖清单,不重下)。要升级就往后加一个、去掉最旧的。
COMFYUI_PINNED = {
    "0.38.0": _comfyui("0.38.0", "185a3e55b9d7e06a89064a3b0cc9644295ee033e81fbcec8d0d475ae5590a136", 12_576_846),
    "0.39.0": _comfyui("0.39.0", "095d95805bdf36e73bbd15d6d2ee15fa627708679a2e67b5f467db4c57e7ff0a", 12_627_617),
}
COMFYUI_VERSION = list(COMFYUI_PINNED)[-1]
#: PyTorch 三件的版本(ComfyUI 0.39.0 的测试场装出来的就是这一组;torchaudio 从 2.11 起不再跟着 torch 发版)。
TORCH = (("torch", "2.14.1"), ("torchvision", "0.29.1"), ("torchaudio", "2.11.0"))


@dataclass(frozen=True)
class CudaChannel:
    """PyTorch 的一个 CUDA 源(`<PyTorch 源>/cu130`)。`windows` / `linux` 是那个系统上 NVIDIA 驱动的最低版本(NVIDIA 的 CUDA
    发行说明:13.x 要 R580 及以上 —— Linux 上那一支的第一版是 580.65.06,CUDA 13.0 的发行说明里就是这一行;12.6 GA 要 Windows
    560.76、Linux 560.28.03);`lowest` / `highest` 是这个源的包支持的显卡算力(含两端)。"""

    key: str
    cuda: str
    windows: tuple[int, ...]
    linux: tuple[int, ...]
    lowest: tuple[int, int]
    highest: tuple[int, int] | None = None

    def driver(self, system: str) -> tuple[int, ...]:
        """这个系统上要的最低驱动版本。"""
        return self.windows if system == "win32" else self.linux


#: **对照表**(2026-10-06 查过 download.pytorch.org:torch 2.14.1 + Python 3.13 + Windows 只有 cu126 / cu130 / cu132 三个源有包,
#: cu132 没有 torchaudio,不用;Linux x86_64 两个源都有 manylinux_2_28 的三件,另要的 nvidia-* 和 triton 同一个源里有)。cu130 是 ComfyUI 0.39.0 自己的 Windows 便携版用的那个,README 说 20 系及以上**必须**用它;
#: cu126 给 10 系及更老的显卡(README:「DO NOT USE THIS ON NEWER 20 SERIES AND ABOVE GPUS」)。CUDA 13 去掉了 Maxwell / Pascal /
#: Volta,所以两行的算力不重叠。按从新到旧排:挑第一个这块显卡能用、驱动也撑得住的。
CUDA_CHANNELS = (
    CudaChannel("cu130", "13.0", windows=(580, 0), linux=(580, 65, 6), lowest=(7, 5)),
    CudaChannel("cu126", "12.6", windows=(560, 76), linux=(560, 28, 3), lowest=(5, 0), highest=(7, 0)),
)
#: PyTorch 的 Linux 包是 manylinux_2_28:系统的 glibc 要这么新(CentOS 7 那种 2.17 的装不上,pip 只会说「找不到这个版本」)。
GLIBC_NEED = (2, 28)

#: 空间按十进制的 GB 算(和界面上 formatBytes、系统的「存储空间」说的是同一个数);显存按 GiB(驱动报的是 MiB)。
GB = 1000 ** 3
GIB = 1024 ** 3
#: 要多少剩余空间(ADR 0041 §4):装完 Mac 上 2 GB、pip 缓存 0.8 GB(实测),CUDA 版 torch 大得多。
DISK_NEED = {"mps": 5 * GB, "cuda": 8 * GB}
#: Windows 上路径最长 259 个字符(没开长路径支持时)。venv 里最深的是 torch 的文件(2.14.1+cu130 的 wheel 里最长 127 个
#: 字符,中央目录实测),前面还有 `.venv\\Lib\\site-packages\\`;安装目录本身超过这个长度,pip 装 torch 会半路失败。
WINDOWS_MAX_PATH = 259
DEEPEST_IN_VENV = len(".venv\\Lib\\site-packages\\") + 135

RECORD = "mosael-install.json"
LOCK = "install.lock"
SOURCE = "ComfyUI"
VENV = ".venv"
DOWNLOADS = "downloads"
RECORD_VERSION = 1

#: 宿主做的那几步之前,插件这边按这个顺序做。`disk` 每次都查,不记。
STEPS = ("disk", "download", "extract", "venv", "torch", "requirements", "nodes")

#: pip 的参数:和宿主 core/pip_install 一样(没人回答提问、不提示新版 pip、一个 2 GB 的下载 15 秒超时太短、断了多试几次、
#: 有现成轮子的版本优先 —— 免得为了新版本号在本机编译)。`raw` 进度条一行一个「Progress 已下 of 总共」,按字节报进度。
PIP_ARGS = ("--no-input", "--disable-pip-version-check", "--timeout", "60", "--retries", "10", "--prefer-binary",
            "--progress-bar", "raw")
#: 一次子进程最多跑多久(装 CUDA 版 torch 要下 2 GB;慢的网一两个小时)。
PIP_TIMEOUT_SECONDS = 4 * 3600
SHORT_TIMEOUT_SECONDS = 600
#: 试 torch 能不能用显卡:第一次导入 CUDA 版 torch 要读几百 MB 的库。
TORCH_CHECK_TIMEOUT_SECONDS = 300
#: 进度最多多久报一次(状态变了、换了一个文件立刻报)。
PROGRESS_SECONDS = 0.25
#: 失败时从 pip 的输出里留多少行来挑原因。
TAIL_LINES = 400
NVIDIA_SMI_TIMEOUT_SECONDS = 15

_PIP_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)\s*$")
_PIP_FILE = re.compile(r"^\s*(?:Downloading|Using cached) (\S+)")
_PIP_INSTALLING = re.compile(r"^\s*Installing collected packages")


def _is_windows() -> bool:
    return os.name == "nt"


def _flags() -> dict[str, Any]:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if _is_windows() else {}  # type: ignore[attr-defined]


def _gb(value: float) -> str:
    return f"{value / GB:.1f} GB"


# --- 这台机器 --------------------------------------------------------------------


@dataclass(frozen=True)
class Gpu:
    name: str
    #: 显存(字节)。
    memory: int
    #: 算力(`8.9` → (8, 9));读不出来是 None。
    compute: tuple[int, int] | None = None


@dataclass(frozen=True)
class Machine:
    """装之前要知道的:系统、建 venv 用的那个 Python 是什么架构、哪个小版本;Windows、Linux 上还有 NVIDIA 驱动和显卡。"""

    system: str  # sys.platform:darwin / win32 / linux
    arch: str  # platform.machine():arm64 / x86_64 / AMD64 / ARM64
    python_minor: str
    driver: tuple[int, ...] | None = None
    gpus: tuple[Gpu, ...] = ()
    #: nvidia-smi 没跑成时它(或系统)说了什么。
    nvidia_error: str = ""
    #: Windows 的长路径支持开了没有(别的系统没这回事)。
    long_paths: bool = True
    #: Linux 上系统的 C 库(`glibc-2.35`;认不出是空串,比如 Alpine 的 musl)。
    libc: str = ""


_PYTHON_FACTS = ("import platform, sys; lib, ver = platform.libc_ver(); print('MOSAEL_PY', "
                 "f'{sys.version_info[0]}.{sys.version_info[1]}', platform.machine(), sys.platform, f'{lib}-{ver}' if lib else '-')")


def _python_facts(python: Path, locale: str) -> tuple[str, str, str, str]:
    """建 venv 用的那个 Python:小版本、架构、系统、C 库(Linux 上是系统的 glibc,`platform.libc_ver` 问的是运行时的那个;
    别处是空串)。跑它一次(它就是宿主随包的那一个,几十毫秒)。"""
    try:
        done = subprocess.run([str(python), "-c", _PYTHON_FACTS], capture_output=True, text=True, timeout=60, **_flags())
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComfyError(say(locale, f"宿主给的 Python 跑不起来:{python}({exc})",
                             f"The Python Mosael provided won't run: {python} ({exc})")) from exc
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] == "MOSAEL_PY":
            return parts[1], parts[2], parts[3], "" if parts[4] == "-" else parts[4]
    raise ComfyError(say(locale, f"宿主给的 Python 跑不起来:{python}\n{(done.stderr or '').strip()[-300:]}",
                         f"The Python Mosael provided won't run: {python}\n{(done.stderr or '').strip()[-300:]}"))


def parse_driver(text: str) -> tuple[int, ...] | None:
    """`581.57` / `580.65.06` → (581, 57) / (580, 65, 6)。认不出是 None。"""
    parts = text.strip().split(".")
    return tuple(int(part) for part in parts) if parts and all(part.isdigit() for part in parts) else None


def parse_memory(text: str) -> int:
    """`24564 MiB` → 字节。认不出是 0。"""
    found = re.match(r"^\s*(\d+)\s*MiB\s*$", text)
    return int(found.group(1)) * 1024 ** 2 if found else 0


def parse_gpus(text: str) -> tuple[tuple[int, ...] | None, list[tuple[str, int]]]:
    """`nvidia-smi --query-gpu=driver_version,name,memory.total --format=csv,noheader` 的输出 → (驱动版本, [(显卡名, 显存)])。
    一行一块卡:第一格驱动、最后一格显存,中间是名字(名字里万一有逗号也不切坏)。"""
    driver: tuple[int, ...] | None = None
    gpus: list[tuple[str, int]] = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 3:
            continue
        version = parse_driver(cells[0])
        if version is None:
            continue
        driver = driver or version
        gpus.append((", ".join(cells[1:-1]), parse_memory(cells[-1])))
    return driver, gpus


def parse_compute(text: str) -> list[tuple[int, int] | None]:
    """`nvidia-smi --query-gpu=compute_cap --format=csv,noheader` → 每块卡的算力。"""
    found: list[tuple[int, int] | None] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\.(\d+)\s*$", line)
        found.append((int(match.group(1)), int(match.group(2))) if match else None)
    return found


def _nvidia_smi() -> str | None:
    """nvidia-smi 在哪:PATH 上的,或者驱动常装的那几个地方(Windows 的两个老地方;Linux 上后端作为服务跑时 PATH 可能很短,
    容器里 NVIDIA 运行时放在 /usr/local/nvidia/bin)。"""
    found = shutil.which("nvidia-smi")
    if found:
        return found
    for candidate in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                      Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
                      Path("/usr/bin/nvidia-smi"), Path("/usr/local/nvidia/bin/nvidia-smi")):
        if candidate.is_file():
            return str(candidate)
    return None


Runner = Callable[[list[str]], str]


def _run_text(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_SECONDS, **_flags())
    if done.returncode != 0:
        raise OSError((done.stderr or done.stdout or f"exit {done.returncode}").strip()[:300])
    return done.stdout or ""


def read_nvidia(run: Runner = _run_text, smi: str | None = None) -> tuple[tuple[int, ...] | None, tuple[Gpu, ...], str]:
    """问 nvidia-smi:驱动版本、每块卡的名字和显存(ADR 0041 §4 那一条命令),再单问一次算力(老驱动不认这一项,问不到就是 None)。"""
    smi = smi or _nvidia_smi()
    if smi is None:
        return None, (), "nvidia-smi not found"
    try:
        driver, cards = parse_gpus(run([smi, "--query-gpu=driver_version,name,memory.total", "--format=csv,noheader"]))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, (), str(exc) or type(exc).__name__
    try:
        computes = parse_compute(run([smi, "--query-gpu=compute_cap", "--format=csv,noheader"]))
    except (OSError, subprocess.SubprocessError):
        computes = []
    gpus = tuple(Gpu(name, memory, computes[index] if index < len(computes) else None)
                 for index, (name, memory) in enumerate(cards))
    return driver, gpus, "" if gpus else "nvidia-smi listed no GPU"


def _long_paths_enabled() -> bool:
    """Windows 的长路径支持(注册表 LongPathsEnabled)。读不到当没开。"""
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (ImportError, OSError):
        return False


def probe_machine(python: Path, locale: str) -> Machine:
    minor, arch, system, libc = _python_facts(python, locale)
    if system == "darwin":
        return Machine(system=system, arch=arch, python_minor=minor)
    driver, gpus, problem = read_nvidia()
    return Machine(system=system, arch=arch, python_minor=minor, driver=driver, gpus=gpus, nvidia_error=problem,
                   long_paths=_long_paths_enabled() if system == "win32" else True, libc=libc)


# --- 能不能装、装哪种 --------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """这台机器能不能装、装哪种 PyTorch。`flavour`:`mps` 或某个 CUDA 源的 key;不能装时是空串。"""

    ok: bool
    flavour: str
    platform: dict[str, str]
    reason: dict[str, str]
    warnings: tuple[dict[str, str], ...] = ()

    @property
    def cuda(self) -> CudaChannel | None:
        return next((channel for channel in CUDA_CHANNELS if channel.key == self.flavour), None)


def _version(numbers: tuple[int, ...] | tuple[int, int]) -> str:
    return ".".join(str(one) for one in numbers)


def _driver_text(numbers: tuple[int, ...]) -> str:
    """驱动版本照 NVIDIA 的写法:Linux 的三段式后两段补成两位(580.65.06),Windows 的两段式照写(581.57)。"""
    if len(numbers) == 3:
        return f"{numbers[0]}.{numbers[1]:02d}.{numbers[2]:02d}"
    return _version(numbers)


def _other_ways(zh: str, en: str) -> dict[str, str]:
    return {"zh": f"{zh}。可以「用我自己装的」(选一个装好的 ComfyUI 目录),或者连一台服务器",
            "en": f"{en}. You can use your own install (pick an installed ComfyUI folder) or connect to a server instead"}


def judge(machine: Machine) -> Verdict:
    """ADR 0041 拍板 3:Apple 芯片 Mac、Windows / Linux(x86_64)+ NVIDIA 装;别的说清楚为什么不装。"""
    if machine.system == "darwin":
        if machine.arch == "arm64":
            return Verdict(True, "mps", {"zh": "Apple 芯片 Mac", "en": "Mac with Apple silicon"},
                           {"zh": "PyPI 上的 PyTorch 直接带 MPS(用 Apple 芯片的显卡算)",
                            "en": "PyTorch from PyPI comes with MPS (computes on the Apple silicon GPU)"})
        return Verdict(False, "", {"zh": "Intel 芯片的 Mac", "en": "Mac with an Intel processor"},
                       _other_ways("Intel 芯片的 Mac 这一版不装:PyTorch 已经不给 Intel Mac 发新版本,只能用 CPU 算,非常慢",
                                   "Macs with an Intel processor aren't supported in this version: PyTorch no longer ships "
                                   "new releases for them, and the CPU alone is very slow"))
    if machine.system == "win32":
        if machine.arch.upper() not in ("AMD64", "X86_64"):
            return Verdict(False, "", {"zh": f"Windows({machine.arch})", "en": f"Windows ({machine.arch})"},
                           _other_ways("这一版只给 x64 的 Windows 装", "This version installs only on x64 Windows"))
        return _judge_nvidia(machine)
    if machine.system.startswith("linux"):
        if machine.arch.lower() not in ("x86_64", "amd64"):
            return Verdict(False, "", {"zh": f"Linux({machine.arch})", "en": f"Linux ({machine.arch})"},
                           _other_ways("这一版只给 x86_64 的 Linux 装", "This version installs only on x86_64 Linux"))
        glibc = _glibc(machine.libc)
        if glibc is None or glibc < GLIBC_NEED:
            have_zh = machine.libc.replace("-", " ") if glibc else "认不出是 glibc(Alpine 这类 musl 系统)"
            have_en = machine.libc.replace("-", " ") if glibc else "not recognised as glibc (musl systems such as Alpine)"
            return Verdict(False, "", {"zh": "Linux", "en": "Linux"}, _other_ways(
                f"PyTorch 的 Linux 包要 glibc {_version(GLIBC_NEED)} 以上,这台是 {have_zh}",
                f"PyTorch's Linux packages need glibc {_version(GLIBC_NEED)} or newer; this machine has {have_en}"))
        return _judge_nvidia(machine)
    return Verdict(False, "", {"zh": machine.system, "en": machine.system},
                   _other_ways("这个系统这一版不装", "This system isn't supported in this version"))


def _glibc(libc: str) -> tuple[int, ...] | None:
    """`glibc-2.35` → (2, 35);不是 glibc(或认不出)是 None。"""
    name, _, version = libc.partition("-")
    return parse_driver(version) if name == "glibc" else None


def _judge_nvidia(machine: Machine) -> Verdict:
    system = "Windows" if machine.system == "win32" else "Linux"
    if not machine.gpus or machine.driver is None:
        linux_zh = ";Linux 上要装 NVIDIA 的专有驱动,在容器里要把显卡带进来(比如 docker run --gpus all)" if system == "Linux" else ""
        linux_en = "; on Linux the proprietary NVIDIA driver is needed, and a container needs the GPU passed in (such as "                    "docker run --gpus all)" if system == "Linux" else ""
        return Verdict(False, "", {"zh": f"{system},没找到 NVIDIA 显卡", "en": f"{system}, no NVIDIA GPU found"},
                       _other_ways("这一版只给 NVIDIA 显卡装:没找到 nvidia-smi,或者它没列出显卡(没装 NVIDIA 驱动、"
                                   f"是 AMD / Intel 显卡、或者只有 CPU){linux_zh}。{machine.nvidia_error}".rstrip(),
                                   "This version installs only for NVIDIA GPUs: nvidia-smi wasn't found or listed no GPU "
                                   f"(no NVIDIA driver, an AMD / Intel GPU, or CPU only){linux_en}. {machine.nvidia_error}".rstrip()))
    gpu = machine.gpus[0]  # ComfyUI 缺省用第 0 块
    memory = f"{gpu.memory / GIB:.0f} GB" if gpu.memory else "?"
    driver = _driver_text(machine.driver)
    named = {"zh": f"{system} + {gpu.name}(显存 {memory},驱动 {driver})",
             "en": f"{system} + {gpu.name} ({memory} VRAM, driver {driver})"}
    compute = gpu.compute
    fits = [channel for channel in CUDA_CHANNELS
            if compute is None or (channel.lowest <= compute and (channel.highest is None or compute <= channel.highest))]
    if not fits:
        return Verdict(False, "", named, _other_ways(
            f"这块显卡太老(算力 {_version(compute or (0, 0))}):PyTorch {TORCH[0][1]} 已经不支持它",
            f"This GPU is too old (compute capability {_version(compute or (0, 0))}): PyTorch {TORCH[0][1]} no longer supports it"))
    usable = [channel for channel in fits if machine.driver >= channel.driver(machine.system)]
    if not usable:
        newest = fits[0]
        need = _driver_text(newest.driver(machine.system))
        return Verdict(False, "", named, {
            "zh": f"驱动 {driver} 太旧:这块显卡要用 CUDA {newest.cuda} 版的 PyTorch,得 {need} 以上的驱动。"
                  f"先到 NVIDIA 官网升级显卡驱动,再回来装",
            "en": f"Driver {driver} is too old: this GPU needs the CUDA {newest.cuda} build of PyTorch, which requires driver "
                  f"{need} or newer. Update the NVIDIA driver first, then come back and install",
        })
    channel = usable[0]
    need = _driver_text(channel.driver(machine.system))
    warnings: tuple[dict[str, str], ...] = ()
    if compute is None:
        warnings = ({"zh": "nvidia-smi 没说这块显卡的算力,按 20 系及以上挑的;装完 PyTorch 会试一下显卡,不行会说",
                     "en": "nvidia-smi didn't report this GPU's compute capability, so a 20-series-or-newer GPU was assumed; "
                           "the GPU is tried right after PyTorch is installed"},)
    return Verdict(True, channel.key, named, {
        "zh": f"装 CUDA {channel.cuda} 版的 PyTorch(驱动 {driver} 撑得住,要 {need} 以上)",
        "en": f"Installs the CUDA {channel.cuda} build of PyTorch (driver {driver} is new enough; it needs {need} or newer)",
    }, warnings)


def torch_requirements(flavour: str) -> list[str]:
    """PyTorch 三件钉死的版本。CUDA 的连同后缀(`torch==2.14.1+cu130`):换了 CUDA 源时 pip 才认得「这不是装着的那一个」,
    也挡住 PyPI 上同版本号的 CPU 版混进来。"""
    suffix = "" if flavour == "mps" else f"+{flavour}"
    return [f"{name}=={version}{suffix}" for name, version in TORCH]


def torch_index(flavour: str, sources: dict[str, str]) -> str:
    """装 PyTorch 那一步用哪个源:MPS 版就是 PyPI 上的,走 pip 源(空 = 官方 PyPI);CUDA 版走 PyTorch 源下的那个频道。"""
    if flavour == "mps":
        return sources.get("pip_index_url", "")
    base = (sources.get("pytorch_index_url") or "https://download.pytorch.org/whl").rstrip("/")
    return f"{base}/{flavour}"


def _torch_label(flavour: str) -> dict[str, str]:
    version = TORCH[0][1]
    if flavour == "mps":
        return {"zh": f"PyTorch {version}(MPS)", "en": f"PyTorch {version} (MPS)"}
    channel = next(one for one in CUDA_CHANNELS if one.key == flavour)
    return {"zh": f"PyTorch {version}(CUDA {channel.cuda})", "en": f"PyTorch {version} (CUDA {channel.cuda})"}


def _titles(flavour: str, version: str = COMFYUI_VERSION) -> dict[str, dict[str, str]]:
    torch = _torch_label(flavour) if flavour else {"zh": "PyTorch", "en": "PyTorch"}
    check = {"zh": "试一下 Apple 显卡", "en": "try the Apple GPU"} if flavour == "mps" else \
        {"zh": "试一下显卡", "en": "try the GPU"}
    return {
        "disk": {"zh": "查剩余空间", "en": "Check free disk space"},
        "download": {"zh": f"下载 ComfyUI {version} 源码(按 sha256 校验)",
                     "en": f"Download the ComfyUI {version} source (checked by sha256)"},
        "extract": {"zh": "解开源码", "en": "Unpack the source"},
        "venv": {"zh": "建 Python 环境、升级 pip", "en": "Create the Python environment and upgrade pip"},
        "torch": {"zh": f"装 {torch['zh']},{check['zh']}", "en": f"Install {torch['en']} and {check['en']}"},
        "requirements": {"zh": "装 ComfyUI 的依赖和 ComfyUI-Manager", "en": "Install ComfyUI's dependencies and ComfyUI-Manager"},
        "nodes": {"zh": f"装 pysssss(ComfyUI-Custom-Scripts {service.PYSSSSS_COMMIT[:7]},模型库要它)",
                  "en": f"Install pysssss (ComfyUI-Custom-Scripts {service.PYSSSSS_COMMIT[:7]}, the model library needs it)"},
    }


# --- 安装记录 --------------------------------------------------------------------


def read_record(root: Path) -> dict[str, Any]:
    try:
        record = json.loads((root / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _write_record(root: Path, record: dict[str, Any]) -> None:
    """先写临时文件再改名:断电时要么是上一笔、要么是这一笔,不会是半截的 JSON。"""
    record = {**record, "version": RECORD_VERSION, "updated_at": datetime.now(UTC).isoformat()}
    temporary = root / f"{RECORD}.tmp"
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(root / RECORD)


def venv_python(root: Path, *, windows: bool | None = None) -> Path:
    """装好以后 venv 里的那个解释器(Windows 上是 `Scripts\\python.exe`)。"""
    windows = _is_windows() if windows is None else windows
    return root / VENV / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


def _venv_minor(root: Path) -> str:
    try:
        text = (root / VENV / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("version", "version_info"):
            parts = value.strip().split(".")
            if len(parts) >= 2:
                return f"{parts[0]}.{parts[1]}"
    return ""


def done_steps(root: Path, record: dict[str, Any], *, python_minor: str, flavour: str, windows: bool | None = None) -> set[str]:
    """记录里说做完了、而且现在看着还对的那几步。不对的作废,连同靠它的后几步:

    - Python 小版本变了 → venv 和装进去的包(torch、依赖)作废;源码、pysssss 不动;
    - PyTorch 的种类变了(换了驱动、换了显卡)→ 只重装 PyTorch;
    - 源码不在了 → 重新下、解,pysssss 也跟着重装;venv 不在了 → venv 和包重装。
    """
    done = {key for key in record.get("done") or [] if key in STEPS}
    if record.get("python_minor") != python_minor:
        done -= {"venv", "torch", "requirements"}
    if record.get("flavour") != flavour:
        done -= {"torch"}
    if not (root / SOURCE / "main.py").is_file():
        done -= {"extract", "nodes"}
    if "extract" not in done and "download" in done and \
            not (root / DOWNLOADS / _tarball_name(installing_version(record))).is_file():
        done -= {"download"}
    if not venv_python(root, windows=windows).is_file() or _venv_minor(root) != python_minor:
        done -= {"venv", "torch", "requirements"}
    if not (root / SOURCE / "custom_nodes" / service.PYSSSSS_DIR).is_dir():
        done -= {"nodes"}
    return done


def unfinished_change(record: dict[str, Any], locale: str) -> str:
    """上一次换版本(更新、回到上一版)被强行打断了(后端被杀、断电):记录里留着标记。这时源码和依赖可能半新半旧 —— 不起它、
    不在它上面接着装,先到连接页上「换回」把它收拾好(versions.rollback)。没有就是空串。"""
    back_to = str((record.get("restoring") or {}).get("version") or (record.get("previous") or {}).get("version") or "")
    if not (record.get("updating") or record.get("restoring")):
        return ""
    return say(locale, f"上一次换 ComfyUI 版本没做完(Mosael 被强行关掉了,或者断电):到连接页上点「换回 {back_to}」把它收拾好",
               f"The last ComfyUI version change didn't finish (Mosael was closed forcibly, or the power went out). Choose "
               f"“Go back to {back_to}” on the connection page to tidy it up")


def _tarball_name(version: str) -> str:
    return f"ComfyUI-{version}.tar.gz"


def installing_version(record: dict[str, Any], wanted: str = "") -> str:
    """装(或接着装)哪个版本:源码已经解开了就是记录里的那个(接着装不换版本);还没解开就是要的那个(没说就是最新钉死的)。
    记录里的、要的都得是钉死的版本之一。"""
    recorded = str(record.get("comfyui") or "")
    if "extract" in (record.get("done") or []) and recorded in COMFYUI_PINNED:
        return recorded
    return wanted if wanted in COMFYUI_PINNED else (recorded if recorded in COMFYUI_PINNED else COMFYUI_VERSION)


def _size_of(root: Path) -> int:
    """安装目录已经占了多少(接着装时少要一些空间)。"""
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                continue
    return total


def _free_space(root: Path) -> int:
    """安装目录所在那块盘还剩多少(目录还没建时问最近的那一层祖先)。"""
    probe = root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _need(flavour: str) -> int:
    return DISK_NEED["mps" if flavour == "mps" else "cuda"]


def _sources(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("sources")
    raw = raw if isinstance(raw, dict) else {}
    return {key: str(raw.get(key) or "").strip() for key in ("pip_index_url", "pytorch_index_url", "github_mirror")}


def _root(payload: dict[str, Any], locale: str) -> Path:
    raw = str(payload.get("directory") or "").strip()
    if not raw:
        raise ComfyError(say(locale, "宿主没给安装目录", "Mosael gave no install folder"))
    return Path(raw).expanduser()


def _base_python(payload: dict[str, Any], locale: str) -> Path:
    raw = str(payload.get("python") or "").strip()
    if not raw or not Path(raw).is_file():
        raise ComfyError(say(locale, f"宿主给的 Python 不在:{raw}", f"The Python Mosael provided doesn't exist: {raw}"))
    return Path(raw)


def _path_problem(root: Path, machine: Machine) -> dict[str, str] | None:
    """Windows 没开长路径支持、安装目录又太长:torch 的文件放不下。"""
    if machine.system != "win32" or machine.long_paths:
        return None
    longest = len(str(root)) + 1 + DEEPEST_IN_VENV
    if longest <= WINDOWS_MAX_PATH:
        return None
    return {"zh": f"安装目录的路径太长({len(str(root))} 个字符):PyTorch 的文件放进去会超过 Windows 的 {WINDOWS_MAX_PATH} 字符上限。"
                  f"打开 Windows 的长路径支持(组策略「启用 Win32 长路径」或注册表 LongPathsEnabled = 1),或者把 Mosael 的数据目录"
                  f"放到短一点的路径下\n{root}",
            "en": f"The install folder's path is too long ({len(str(root))} characters): PyTorch's files would exceed Windows' "
                  f"{WINDOWS_MAX_PATH}-character limit. Enable Windows long paths (the “Enable Win32 long paths” group policy or "
                  f"LongPathsEnabled = 1 in the registry), or move Mosael's data folder to a shorter path\n{root}"}


# --- service_plan ---------------------------------------------------------------


def plan(payload: dict[str, Any], locale: str, *, machine: Machine | None = None) -> dict[str, Any]:
    """给确认页:这台机器能不能装、装哪种 PyTorch、要多少空间、分几步(接着装时哪几步已经做完)、要从哪几处下载。不写任何东西。"""
    root = _root(payload, locale)
    machine = machine or probe_machine(_base_python(payload, locale), locale)
    verdict = judge(machine)
    sources = _sources(payload)
    record = read_record(root)
    version = installing_version(record, str(payload.get("version") or ""))
    titles = _titles(verdict.flavour, version)
    done = done_steps(root, record, python_minor=machine.python_minor, flavour=verdict.flavour,
                      windows=machine.system == "win32") if verdict.ok else set()
    problems: list[dict[str, Any]] = [{"level": "warning", "text": text} for text in verdict.warnings]
    need = _need(verdict.flavour) if verdict.ok else 0
    free = _free_space(root)
    remaining = max(need - _size_of(root), 0) if root.exists() else need
    left = [key for key in STEPS if key != "disk" and key not in done]
    if verdict.ok and left and free < remaining:
        problems.append({"level": "error", "text": _disk_text(free, remaining, need)})
    path_problem = _path_problem(root, machine) if verdict.ok else None
    if path_problem is not None:
        problems.append({"level": "error", "text": path_problem})
    downloads = []
    if verdict.ok:
        index = torch_index(verdict.flavour, sources)
        # 地址已经是改写过的(GitHub 镜像前缀接在前面、pip / PyTorch 源换过);`source` 说是被下载源里的哪一项改写的
        downloads = [
            {"label": {"zh": f"ComfyUI {version} 源码", "en": f"ComfyUI {version} source"},
             "url": pinned.source_url(COMFYUI_PINNED[version].url, sources["github_mirror"]), "source": "github"},
            {"label": _torch_label(verdict.flavour), "url": index or "https://pypi.org/simple",
             "source": "pip" if verdict.flavour == "mps" else "pytorch"},
            {"label": {"zh": "ComfyUI 的依赖、ComfyUI-Manager", "en": "ComfyUI's dependencies, ComfyUI-Manager"},
             "url": sources["pip_index_url"] or "https://pypi.org/simple", "source": "pip"},
            {"label": {"zh": "pysssss", "en": "pysssss"}, "url": pinned.source_url(service.PYSSSSS.url, sources["github_mirror"]),
             "source": "github"},
        ]
    return {
        "ok": verdict.ok,
        "platform": verdict.platform,
        "verdict": verdict.reason,
        "flavour": verdict.flavour,
        "torch": _torch_label(verdict.flavour) if verdict.ok else "",
        "comfyui": version,
        "python_minor": machine.python_minor,
        "disk_bytes": need,
        "free_bytes": free,
        "steps": [{"key": key, "title": titles[key], "done": key in done} for key in STEPS],
        "downloads": downloads,
        "problems": problems,
    }


def _disk_text(free: int, remaining: int, need: int) -> dict[str, str]:
    return {"zh": f"这块盘只剩 {_gb(free)},装 ComfyUI 还要 {_gb(remaining)}(一共至少 {_gb(need)})。清出空间再装",
            "en": f"Only {_gb(free)} is free on this disk; installing ComfyUI needs {_gb(remaining)} more ({_gb(need)} in "
                  f"total). Free up space, then install"}


# --- service_install ------------------------------------------------------------


class _Reporter:
    """一步一步地说:开头一行说有哪几步,之后每一步开始、进行中(字节、正在下哪个文件)、做完各一行。进行中的最多每 0.25 秒一行。"""

    def __init__(self, emit: Emit, titles: dict[str, dict[str, str]], steps: tuple[str, ...] = STEPS) -> None:
        self._emit = emit
        self._titles = titles
        self._steps = steps
        self._last = 0.0
        self._item: Any = None
        self.key = ""

    def outline(self, done: set[str]) -> None:
        self._emit({"event": "step", "outline": [{"key": key, "title": self._titles[key], "done": key in done}
                                                 for key in self._steps]})

    def begin(self, key: str) -> None:
        self.key = key
        self._item = None
        self._emit({"event": "step", "key": key, "state": "running"})

    def progress(self, *, done_bytes: int | None = None, total_bytes: int | None = None, item: Any = None,
                 force: bool = False) -> None:
        now = time.monotonic()
        changed = item != self._item
        # 一个文件下完的那一下总要报:不然下得快的(缓存里有、镜像快)界面上永远停在半截
        finished = done_bytes is not None and total_bytes is not None and done_bytes >= total_bytes
        if not (force or changed or finished) and now - self._last < PROGRESS_SECONDS:
            return
        self._last, self._item = now, item
        self._emit({"event": "step", "key": self.key, "state": "running", "done_bytes": done_bytes,
                    "total_bytes": total_bytes, "item": item})

    def finish(self, key: str) -> None:
        self._emit({"event": "step", "key": key, "state": "done"})


class _Log:
    """宿主给的日志文件:每一步的命令和完整输出(pip 的 raw 进度行不进日志 —— 一个 torch 就是几千行)。"""

    def __init__(self, path: str) -> None:
        self._file = open(path, "a", encoding="utf-8", errors="replace") if path else None  # noqa: SIM115

    def line(self, text: str) -> None:
        if self._file is not None:
            self._file.write(text.rstrip("\n") + "\n")
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()


@contextmanager
def _locked(root: Path, locale: str) -> Iterator[None]:
    """装的时候攥着 `install.lock`:同一个目录不会两次一起装(后端被强杀时上一次的插件进程可能还在跑)。进程没了锁自己松开。"""
    handle = open(root / LOCK, "a+")  # noqa: SIM115
    try:
        handle.seek(0)
        if _is_windows():
            import msvcrt  # type: ignore[import-not-found]

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise ComfyError(say(locale, "这个目录正在由另一次安装使用,等它结束(或者取消它)再来",
                             "Another install is using this folder. Wait for it to finish (or cancel it), then try again")) from exc
    try:
        yield
    finally:
        try:
            if _is_windows():
                import msvcrt  # type: ignore[import-not-found]

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            pass
        handle.close()


@dataclass
class _Job:
    root: Path
    base: Path
    machine: Machine
    flavour: str
    sources: dict[str, str]
    pip_cache: str
    locale: str
    log: _Log
    report: _Reporter
    is_cancelled: Callable[[], bool]
    record: dict[str, Any] = field(default_factory=dict)
    #: 装(或换到)哪个钉死的版本。
    version: str = COMFYUI_VERSION
    #: 这一次每一步的标题(pip 失败时说是哪一步没成);空就按安装的那几步。
    titles: dict[str, dict[str, str]] = field(default_factory=dict)
    #: 失败了点哪个按钮再来(中文、英文):装是「接着装」,换版本是「更新」。
    retry: tuple[str, str] = ("接着装", "Resume")

    @property
    def windows(self) -> bool:
        return self.machine.system == "win32"

    @property
    def python(self) -> Path:
        return venv_python(self.root, windows=self.windows)

    def say(self, zh: str, en: str) -> str:
        return say(self.locale, zh, en)


def _pip_env(job: _Job) -> dict[str, str]:
    """pip 的环境:插件进程自己的(宿主给的代理在里面),加上不缓冲输出(进度才跟得上)、宿主给的缓存目录。"""
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    for key in [key for key in env if key.upper() in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS")]:
        del env[key]  # 源只认这一次给的那个
    if job.pip_cache:
        env["PIP_CACHE_DIR"] = job.pip_cache
    return env


def _stream(job: _Job, argv: list[str], *, timeout: float, on_line: Callable[[str], None] | None = None) -> tuple[int, list[str]]:
    """跑一个子进程、一行一行读它的输出(进日志、交给 `on_line`),边读边看取消了没有、超时没有。交回 (退出码, 最后几百行)。

    取消、超时都是先请它退(terminate),10 秒不退再强杀;它在插件这一组里,插件自己被宿主强杀时它也跟着走。"""
    job.log.line(f"$ {' '.join(argv)}")
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               cwd=str(job.root), env=_pip_env(job), text=True, encoding="utf-8", errors="replace",
                               bufsize=1, **_flags())
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    tail: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if job.is_cancelled():
                raise pinned.Cancelled
            if time.monotonic() > deadline:
                raise ComfyError(job.say(f"{Path(argv[0]).name} 跑了 {int(timeout)} 秒还没完,停掉了。日志里看看卡在哪",
                                         f"{Path(argv[0]).name} didn't finish within {int(timeout)} seconds and was stopped. "
                                         f"Check the log to see where it got stuck"))
            if not line:
                continue
            text = line.rstrip("\r\n")
            if on_line is not None:
                on_line(text)
            if _PIP_PROGRESS.match(text):
                continue
            job.log.line(text)
            tail.append(text)
            if len(tail) > TAIL_LINES:
                del tail[: len(tail) - TAIL_LINES]
    except BaseException:
        _stop(process)
        raise
    code = process.wait()
    reader.join(timeout=2)
    job.log.line(f"(退出码 {code})")
    return code, tail


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


# pip 失败的常见病因:和宿主 core/pip_install._CAUSES 同一张表的意思,双语;越具体越靠前,取第一个命中的。
_PIP_CAUSES: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (re.compile(r"No space left|\[Errno 28\]|\[WinError 112\]|not enough space", re.I),
     "disk", "磁盘空间不足", "the disk is full"),
    (re.compile(r"MemoryError|Unable to allocate|Cannot allocate memory", re.I),
     "memory", "内存不足 —— 这些包要一次解开几百 MB,关掉占内存的程序再试", "out of memory — these packages unpack hundreds of MB "
     "at once; close memory-hungry programs and try again"),
    (re.compile(r"No matching distribution found|Could not find a version that satisfies", re.I),
     "source", "这个源上找不到要装的版本(镜像可能还没同步到)", "this source doesn't have the required version (a mirror may "
     "not have synced it yet)"),
    (re.compile(r"Read timed out|ConnectionError|Connection broken|Max retries exceeded|Temporary failure in name resolution|"
                r"SSLError|ProxyError|RemoteDisconnected", re.I),
     "source", "下载超时或断流", "the download timed out or broke off"),
    (re.compile(r"ResolutionImpossible|conflict is caused by", re.I),
     "conflict", "依赖之间版本冲突,凑不出一个都满足的组合", "the dependencies conflict; no combination satisfies all of them"),
    (re.compile(r"Microsoft Visual C\+\+.{0,40}required|command .{0,40}cl\.exe.{0,20}failed|RUST_BACKTRACE|rustc", re.I),
     "compile", "有个包没有现成的安装包、要在本机编译,而这一步失败了", "a package has no prebuilt wheel and compiling it on "
     "this machine failed"),
)
_PIP_VERDICT = re.compile(r"^ERROR:\s*(.+)$")
_PIP_NOISE = re.compile(r"^ERROR:\s*(note:|hint:|for more information)", re.I)


def explain_pip(job: _Job, tail: list[str], *, torch_step: bool, title: dict[str, str] | None = None) -> ComfyError:
    """pip 失败 → 一段人能照做的话:病因、该换哪个源再「接着装」、pip 自己的结论行(挑 `ERROR:` 那几行,不取尾巴)。
    `title` 是这一次 pip 在做什么(缺省按是不是装 PyTorch 那一步取安装步骤的标题)。"""
    text = "\n".join(tail)
    cause = next(((kind, zh, en) for pattern, kind, zh, en in _PIP_CAUSES if pattern.search(text)), None)
    verdict = [match.group(0) for line in tail if (match := _PIP_VERDICT.match(line.strip())) and not _PIP_NOISE.match(line.strip())]
    verdict = list(dict.fromkeys(verdict))[:3]
    key = "torch" if torch_step else "requirements"
    title = title or job.titles.get(key) or _titles(job.flavour)[key]
    again_zh, again_en = job.retry
    uses_pytorch_source = torch_step and job.flavour != "mps"
    source_zh = "「管理 → 下载源」里的「PyTorch 源」" if uses_pytorch_source else "「管理 → 下载源」里的 pip 源"
    source_en = "the PyTorch source under Admin → Download sources" if uses_pytorch_source else \
        "the pip source under Admin → Download sources"
    if cause is None:
        why_zh, why_en = "pip 没说清原因", "pip didn't say why"
        next_zh, next_en = "看看日志里 pip 说了什么", "check what pip said in the log"
    else:
        kind, why_zh, why_en = cause
        if kind == "disk":
            next_zh, next_en = f"清出空间后「{again_zh}」,已经下好的不会重下", \
                f"free up space, then choose {again_en}; what's downloaded isn't fetched again"
        elif kind == "source":
            next_zh, next_en = f"换一个{source_zh}再「{again_zh}」", f"switch {source_en} and choose {again_en}"
        else:
            next_zh, next_en = f"「{again_zh}」再试一次;还不行看看日志", f"choose {again_en} to try again; if it still fails, check the log"
    tail_text = (" / ".join(verdict))[:400]
    return ComfyError(say(job.locale,
                          f"{title['zh']}失败:{why_zh}。{next_zh}" + (f"\n{tail_text}" if tail_text else ""),
                          f"{title['en']} failed: {why_en}. To fix it, {next_en}" + (f"\n{tail_text}" if tail_text else "")))


def _pip_install(job: _Job, args: list[str], *, index: str, torch_step: bool, title: dict[str, str] | None = None) -> None:
    """`pip install` 一次:按字节报进度(raw 进度条)、报正在下哪个文件、装的时候说一声;失败说人话。

    **不加 `--upgrade`**:依赖那一步要是升级 requirements.txt 里没写版本的 `torch`,会从 pip 源换上 PyPI 的那一个 —— Windows 上
    就是 CPU 版(ComfyUI README 的「Torch not compiled with CUDA enabled」就是这么来的)。"""
    item: list[Any] = [None]

    def on_line(text: str) -> None:
        progress = _PIP_PROGRESS.match(text)
        if progress:
            job.report.progress(done_bytes=int(progress.group(1)), total_bytes=int(progress.group(2)), item=item[0])
            return
        found = _PIP_FILE.match(text)
        if found and not found.group(1).endswith(".metadata"):  # 只取元数据(PEP 658)的那几行一闪而过,不当「正在下」
            item[0] = found.group(1).rsplit("/", 1)[-1]
            job.report.progress(item=item[0], force=True)
        elif _PIP_INSTALLING.match(text):
            item[0] = {"zh": "把下好的包装进环境…", "en": "Installing the downloaded packages…"}
            job.report.progress(item=item[0], force=True)

    argv = [str(job.python), "-m", "pip", "install", *PIP_ARGS, *(["--index-url", index] if index else []), *args]
    code, tail = _stream(job, argv, timeout=PIP_TIMEOUT_SECONDS, on_line=on_line)
    if code != 0:
        raise explain_pip(job, tail, torch_step=torch_step, title=title)


_TORCH_CHECK = r"""
import json, sys
out = {}
try:
    import torch
    out["torch"] = str(torch.__version__)
    if DEVICE == "mps":
        out["ok"] = bool(torch.backends.mps.is_available()) and float((torch.ones(1, device="mps") + 1).cpu()[0]) == 2.0
    else:
        out["ok"] = bool(torch.cuda.is_available()) and float((torch.ones(1, device="cuda") + 1).cpu()[0]) == 2.0
        out["cuda"] = str(torch.version.cuda or "")
        if torch.cuda.is_available():
            out["gpu"] = torch.cuda.get_device_name(0)
except Exception as exc:
    out["ok"] = False
    out["error"] = f"{type(exc).__name__}: {exc}"
print("MOSAEL_TORCH " + json.dumps(out), flush=True)
"""


def _check_torch(job: _Job) -> None:
    """装好的 PyTorch 真能用显卡:导入、在显卡上算一个 1 + 1。CUDA 版在算力不对的显卡上能导入、`is_available()` 也是真,
    第一次算才报「no kernel image」—— 所以要真算一下。"""
    device = "mps" if job.flavour == "mps" else "cuda"
    said: dict[str, Any] = {}

    def on_line(text: str) -> None:
        if text.startswith("MOSAEL_TORCH "):
            try:
                said.update(json.loads(text[len("MOSAEL_TORCH "):]))
            except ValueError:
                pass

    code, tail = _stream(job, [str(job.python), "-c", f"DEVICE = {device!r}\n" + _TORCH_CHECK],
                         timeout=TORCH_CHECK_TIMEOUT_SECONDS, on_line=on_line)
    if said.get("ok") is True:
        return
    detail = str(said.get("error") or (tail[-1] if tail else f"exit {code}"))[:300]
    if device == "mps":
        raise ComfyError(job.say(f"装好的 PyTorch 用不了 Apple 显卡(MPS):{detail}",
                                 f"The installed PyTorch can't use the Apple GPU (MPS): {detail}"))
    raise ComfyError(job.say(f"装好的 PyTorch 用不了这块 NVIDIA 显卡:{detail}。多半是驱动太旧或显卡太老:先升级显卡驱动,再「接着装」",
                             f"The installed PyTorch can't use this NVIDIA GPU: {detail}. The driver is probably too old or the "
                             f"GPU too old: update the GPU driver, then choose Resume"))


def _installed_torch(job: _Job) -> str:
    """venv 里装着的 torch 是哪个版本(只读包的元数据,不导入它)。"""
    said: list[str] = []
    code = "import importlib.metadata as m; print('MOSAEL_VERSION ' + m.version('torch'))"
    _stream(job, [str(job.python), "-c", code], timeout=SHORT_TIMEOUT_SECONDS,
            on_line=lambda text: said.append(text[len("MOSAEL_VERSION "):]) if text.startswith("MOSAEL_VERSION ") else None)
    return said[-1].strip() if said else ""


# --- 每一步 ----------------------------------------------------------------------


def _step_disk(job: _Job, left: list[str]) -> None:
    need = _need(job.flavour)
    remaining = max(need - _size_of(job.root), 0)
    free = _free_space(job.root)
    job.log.line(f"剩余 {_gb(free)},还要 {_gb(remaining)}(一共至少 {_gb(need)});没做完的:{', '.join(left)}")
    if free < remaining:
        raise ComfyError(say(job.locale, **_disk_text(free, remaining, need)))
    path_problem = _path_problem(job.root, job.machine)
    if path_problem is not None:
        raise ComfyError(say(job.locale, **path_problem))


def _step_download(job: _Job) -> None:
    archive = COMFYUI_PINNED[job.version]
    target = job.root / DOWNLOADS / _tarball_name(job.version)
    if target.is_file():
        target.unlink()  # 上一次没解成的那一份:按记录它没下完(或者不对),重下
    url = pinned.source_url(archive.url, job.sources["github_mirror"])
    job.log.line(f"下载 {url}")
    job.report.progress(done_bytes=0, total_bytes=archive.size, item=f"{archive.name}.tar.gz", force=True)
    pinned.download(archive, target, job.locale, mirror=job.sources["github_mirror"], is_cancelled=job.is_cancelled,
                    on_bytes=lambda done, total: job.report.progress(done_bytes=done, total_bytes=total,
                                                                     item=f"{archive.name}.tar.gz"))
    job.log.line(f"sha256 对上了:{archive.sha256}")


def _step_extract(job: _Job) -> None:
    source = job.root / SOURCE
    tarball = job.root / DOWNLOADS / _tarball_name(job.version)
    if (source / "main.py").is_file():
        job.log.line(f"{source} 已经在了(上一次解完、没来得及记一笔),不重解")
    else:
        if source.exists():
            # 半截的(main.py 都没有):挪开,不删 —— 万一里面有人放了东西
            aside = job.root / f"{SOURCE}.incomplete-{int(time.time())}"
            source.replace(aside)
            job.log.line(f"{source} 不完整,挪到 {aside}")
        pinned.unpack(tarball, source, COMFYUI_PINNED[job.version], job.locale, is_cancelled=job.is_cancelled)
    tarball.unlink(missing_ok=True)
    job.record["comfyui"] = service.comfyui_version(source) or job.version


def _step_venv(job: _Job) -> None:
    venv = job.root / VENV
    if venv.exists():
        job.log.line(f"{venv} 是用别的 Python 建的(或者是半截的),删掉重建")
        shutil.rmtree(venv)
    code, tail = _stream(job, [str(job.base), "-m", "venv", str(venv)], timeout=SHORT_TIMEOUT_SECONDS)
    if code != 0 or not job.python.is_file():
        detail = (tail[-1] if tail else f"exit {code}")[:300]
        raise ComfyError(job.say(f"建 Python 环境失败:{detail}", f"Creating the Python environment failed: {detail}"))
    # 先把 venv 里的 pip 升上去(ensurepip 带的那个随 Python 冻结,只会越来越旧):失败不要紧,自带的也能装
    code, _tail = _stream(job, [str(job.python), "-m", "pip", "install", "--upgrade", *PIP_ARGS,
                                *(["--index-url", job.sources["pip_index_url"]] if job.sources["pip_index_url"] else []), "pip"],
                          timeout=SHORT_TIMEOUT_SECONDS)
    if code != 0:
        job.log.line("pip 自升级没成功,接着用自带的那个")
    job.record["python_minor"] = job.machine.python_minor


def _step_torch(job: _Job) -> None:
    _pip_install(job, torch_requirements(job.flavour), index=torch_index(job.flavour, job.sources), torch_step=True)
    job.report.progress(item={"zh": "试一下显卡…", "en": "Trying the GPU…"}, force=True)
    _check_torch(job)
    job.record["flavour"] = job.flavour


def _step_requirements(job: _Job) -> None:
    source = job.root / SOURCE
    args = ["-r", str(source / "requirements.txt")]
    if (source / "manager_requirements.txt").is_file():
        args += ["-r", str(source / "manager_requirements.txt")]
    before = _installed_torch(job)
    _pip_install(job, args, index=job.sources["pip_index_url"], torch_step=False)
    after = _installed_torch(job)
    if after != before:
        # 不该发生(没加 --upgrade):真发生了,装好的就是一个用不了显卡的 ComfyUI —— 说清楚,不放过去;记下 torch 那一步作废,
        # 「接着装」把它装回来
        job.record["done"] = [key for key in job.record["done"] if key != "torch"]
        _write_record(job.root, job.record)
        raise ComfyError(job.say(f"装依赖时 PyTorch 被换掉了({before} → {after})。「接着装」会把它装回来",
                                 f"Installing the dependencies replaced PyTorch ({before} → {after}). Resume puts it back"))


def _step_nodes(job: _Job) -> None:
    target = job.root / SOURCE / "custom_nodes" / service.PYSSSSS_DIR
    if target.is_dir():
        return
    service.install_pysssss(job.root / SOURCE, job.locale, mirror=job.sources["github_mirror"], is_cancelled=job.is_cancelled,
                            on_bytes=lambda done, total: job.report.progress(done_bytes=done, total_bytes=total,
                                                                             item=f"{service.PYSSSSS.name}.tar.gz"))


_RUN = {
    "download": _step_download,
    "extract": _step_extract,
    "venv": _step_venv,
    "torch": _step_torch,
    "requirements": _step_requirements,
    "nodes": _step_nodes,
}


def install(payload: dict[str, Any], locale: str, emit: Emit, *, machine: Machine | None = None,
            is_cancelled: Callable[[], bool] = pinned.cancelled) -> dict[str, Any]:
    """装,或者接着装。一步一步做,每一步做完记一笔;取消了就停在那一步(下次从它开始)。交回装好的目录(宿主据此试起一次)。"""
    root = _root(payload, locale)
    base = _base_python(payload, locale)
    machine = machine or probe_machine(base, locale)
    verdict = judge(machine)
    if not verdict.ok:
        raise ComfyError(say(locale, **verdict.reason))
    confirmed = str(payload.get("flavour") or "")
    if confirmed and confirmed != verdict.flavour:
        raise ComfyError(say(locale, f"这台机器的情况变了(确认时是 {confirmed},现在是 {verdict.flavour}):重新看一下安装计划再装",
                             f"This machine changed since you confirmed ({confirmed} then, {verdict.flavour} now). Review the "
                             f"install plan again, then install"))
    root.mkdir(parents=True, exist_ok=True)
    log = _Log(str(payload.get("log") or ""))
    try:
        with _locked(root, locale):
            record = read_record(root)
            unfinished = unfinished_change(record, locale)
            if unfinished:
                raise ComfyError(unfinished)
            version = installing_version(record, str(payload.get("version") or ""))
            titles = _titles(verdict.flavour, version)
            done = done_steps(root, record, python_minor=machine.python_minor, flavour=verdict.flavour,
                              windows=machine.system == "win32")
            # 记录里别的(换版本时留下的上一版、没做完的标记)原样留着:接着装、重建运行环境不碰它们
            job = _Job(root=root, base=base, machine=machine, flavour=verdict.flavour, sources=_sources(payload),
                       pip_cache=str(payload.get("pip_cache") or ""), locale=locale, log=log, report=_Reporter(emit, titles),
                       is_cancelled=is_cancelled, version=version, titles=titles,
                       record={**record, "comfyui": version, "flavour": record.get("flavour", ""),
                               "python_minor": record.get("python_minor", ""), "done": sorted(done, key=STEPS.index)})
            log.line(f"== {datetime.now(UTC).isoformat()} 装 ComfyUI 到 {root}({verdict.platform['zh']},{verdict.flavour},"
                     f"Python {machine.python_minor})")
            job.report.outline(done)
            left = [key for key in STEPS if key != "disk" and key not in done]
            for key in STEPS:
                if key == "disk":
                    if left:
                        job.report.begin(key)
                        _step_disk(job, left)
                    job.report.finish(key)
                    continue
                if key in done:
                    job.report.finish(key)
                    continue
                if job.is_cancelled():
                    raise pinned.Cancelled
                log.line(f"== 第 {STEPS.index(key) + 1} 步:{titles[key]['zh']}")
                job.report.begin(key)
                _RUN[key](job)
                job.record["done"] = sorted({*job.record["done"], key}, key=STEPS.index)
                _write_record(root, job.record)
                job.report.finish(key)
            log.line("== 七步都做完了")
            return {
                "directory": str(root),
                "python": str(job.python),
                "python_minor": job.record.get("python_minor") or machine.python_minor,
                "comfyui": job.record.get("comfyui") or version,
                "flavour": verdict.flavour,
            }
    except pinned.Cancelled:
        log.line("== 取消了:停在这一步,下次从它接着装")
        raise
    except ComfyError as exc:
        log.line(f"== 没装成:{exc}")
        raise
    finally:
        log.close()


__all__ = ["COMFYUI_PINNED", "COMFYUI_VERSION", "CUDA_CHANNELS", "CudaChannel", "DISK_NEED", "Gpu", "Machine", "STEPS", "TORCH",
           "Verdict", "done_steps", "explain_pip", "install", "installing_version", "judge", "parse_compute", "parse_driver", "parse_gpus",
           "parse_memory", "plan", "probe_machine", "read_nvidia", "read_record", "torch_index", "torch_requirements",
           "unfinished_change", "venv_python"]
