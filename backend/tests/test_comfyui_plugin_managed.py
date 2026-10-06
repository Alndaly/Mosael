"""ComfyUI 插件的「让 Mosael 装」(ADR 0041 §4):安装计划和安装本身,对着本地的假下载源、假解释器走一遍。

- **这台机器能不能装、装哪种 PyTorch**:Apple 芯片 Mac → MPS;Windows / Linux + NVIDIA 按 `nvidia-smi` 的驱动版本、显卡算力挑
  CUDA 源(对照表钉着 NVIDIA 的发行说明和 download.pytorch.org 上真有的那几个,驱动下限两个系统各一行);Intel Mac、ARM、
  没有 NVIDIA 显卡、驱动太旧、显卡太老、Linux 的 glibc 太旧都说清楚为什么。nvidia-smi 的输出用夹具解析(这台机器跑不了
  Windows、没有 NVIDIA);
- **装**:查空间、下源码(按 sha256 校验)、解开(不越界)、建 venv、装 PyTorch(试一下显卡)、装依赖(不升级 torch)、装 pysssss;
  每一步做完记一笔。假的 Python 是 shell 脚本:建 venv 时放一个假的 venv 解释器,它回答 pip(按字节报进度)、试显卡、问版本;
- **接着装**:取消(下载中、pip 中)、失败之后再来,从没做完的那一步开始;Python 小版本变了只重建 venv 和装进去的包,
  源码、pysssss、模型不动;PyTorch 的种类变了只重装 PyTorch;
- **说人话**:sha256 对不上、空间不够、pip 失败(按这一步说该换哪个源)、同一个目录两次一起装。
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
_PLUGIN_MODULES = ("service", "shared_models", "model_files", "comfy_http", "lines", "pinned", "managed", "versions")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="假解释器是 shell 脚本")
GB = 1000 ** 3  # 空间按十进制的 GB(和插件一样)


@pytest.fixture
def managed():
    saved = {name: sys.modules.pop(name) for name in _PLUGIN_MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import managed as module

        yield module
    finally:
        sys.path.remove(str(TOOLS))
        for name in _PLUGIN_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _error_type():
    from lines import ComfyError

    return ComfyError


MAC = {"system": "darwin", "arch": "arm64", "python_minor": "3.13"}


def _windows(managed, *, driver: str = "581.57", name: str = "NVIDIA GeForce RTX 4090", memory: int = 24 * GB,
             compute: tuple[int, int] | None = (8, 9), long_paths: bool = True):
    return managed.Machine(system="win32", arch="AMD64", python_minor="3.13", driver=managed.parse_driver(driver),
                           gpus=(managed.Gpu(name, memory, compute),), long_paths=long_paths)


def _linux(managed, *, driver: str = "580.65.06", name: str = "NVIDIA GeForce RTX 4090", compute: tuple[int, int] | None = (8, 9),
           arch: str = "x86_64", libc: str = "glibc-2.35", gpus: bool = True):
    return managed.Machine(system="linux", arch=arch, python_minor="3.13", driver=managed.parse_driver(driver) if gpus else None,
                           gpus=(managed.Gpu(name, 24 * GB, compute),) if gpus else (), libc=libc,
                           nvidia_error="" if gpus else "nvidia-smi not found")


# ---- nvidia-smi 和对照表 ------------------------------------------------------------


def test_nvidia_smi_的输出_驱动_显卡_显存(managed) -> None:
    text = "581.57, NVIDIA GeForce RTX 4090, 24564 MiB\n581.57, NVIDIA RTX A2000, Laptop GPU, 4096 MiB\n\nNo devices were found\n"
    driver, gpus = managed.parse_gpus(text)
    assert driver == (581, 57)
    assert gpus == [("NVIDIA GeForce RTX 4090", 24564 * 1024 ** 2), ("NVIDIA RTX A2000, Laptop GPU", 4096 * 1024 ** 2)], \
        "名字里万一有逗号也不切坏:第一格驱动、最后一格显存"
    assert managed.parse_driver("580.65.06") == (580, 65, 6) and managed.parse_driver("N/A") is None
    assert managed.parse_memory("[N/A]") == 0
    assert managed.parse_compute("8.9\n7.5\n[N/A]\n") == [(8, 9), (7, 5), None]
    assert managed.parse_gpus("NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.") == (None, [])


def test_问_nvidia_smi_两次_算力问不到也不挡(managed) -> None:
    asked: list[list[str]] = []

    def run(argv: list[str]) -> str:
        asked.append(argv)
        if "--query-gpu=compute_cap" in argv:
            raise OSError('Field "compute_cap" is not a valid field to query.')
        return "566.36, NVIDIA GeForce GTX 1080 Ti, 11264 MiB\n"

    driver, gpus, problem = managed.read_nvidia(run, smi="nvidia-smi.exe")
    assert asked[0] == ["nvidia-smi.exe", "--query-gpu=driver_version,name,memory.total", "--format=csv,noheader"], \
        "就是 ADR 里那一条命令"
    assert driver == (566, 36) and gpus == (managed.Gpu("NVIDIA GeForce GTX 1080 Ti", 11264 * 1024 ** 2, None),) and not problem

    def broken(argv: list[str]) -> str:
        raise OSError("NVIDIA-SMI has failed")

    assert managed.read_nvidia(broken, smi="nvidia-smi.exe")[2] == "NVIDIA-SMI has failed"


def test_没有_nvidia_smi_就是没找到(managed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(managed, "_nvidia_smi", lambda: None)
    assert managed.read_nvidia(lambda _argv: "") == (None, (), "nvidia-smi not found")


def test_对照表_从新到旧_算力不重叠_驱动下限照_NVIDIA_的发行说明(managed) -> None:
    channels = managed.CUDA_CHANNELS
    assert [one.key for one in channels] == ["cu130", "cu126"], "torch 2.14.1 + cp313 + Windows 真有包的(cu132 没有 torchaudio)"
    assert channels[0].driver("win32") == (580, 0), "CUDA 13.x:R580 及以上"
    assert channels[0].driver("linux") == (580, 65, 6), "CUDA 13.0 GA:Linux x86_64 580.65.06(R580 在 Linux 上的第一版)"
    assert channels[1].driver("win32") == (560, 76), "CUDA 12.6 GA:Windows 560.76"
    assert channels[1].driver("linux") == (560, 28, 3), "CUDA 12.6 GA:Linux x86_64 560.28.03"
    assert channels[0].lowest == (7, 5) and channels[1].highest == (7, 0), "20 系及以上只用 cu130,10 系及更老只用 cu126(ComfyUI README)"
    assert managed.TORCH == (("torch", "2.14.1"), ("torchvision", "0.29.1"), ("torchaudio", "2.11.0"))


@pytest.mark.parametrize(("driver", "name", "compute", "flavour"), [
    ("581.57", "NVIDIA GeForce RTX 4090", (8, 9), "cu130"),
    ("580.88", "NVIDIA GeForce RTX 2060", (7, 5), "cu130"),
    ("595.12", "NVIDIA GeForce RTX 5090", (12, 0), "cu130"),
    ("566.36", "NVIDIA GeForce GTX 1080 Ti", (6, 1), "cu126"),
    ("581.57", "NVIDIA TITAN V", (7, 0), "cu126"),
    ("560.76", "NVIDIA GeForce GTX 970", (5, 2), "cu126"),
])
def test_Windows_NVIDIA_挑这块显卡能用_驱动撑得住的最高那个(managed, driver: str, name: str, compute, flavour: str) -> None:
    verdict = managed.judge(_windows(managed, driver=driver, name=name, compute=compute))
    assert verdict.ok and verdict.flavour == flavour
    assert name in verdict.platform["zh"] and driver in verdict.platform["en"]


def test_Windows_NVIDIA_驱动太旧_显卡太老_没找到显卡_都说清楚(managed) -> None:
    old = managed.judge(_windows(managed, driver="572.16", compute=(8, 9)))
    assert not old.ok and "572.16" in old.reason["zh"] and "580" in old.reason["zh"] and "升级" in old.reason["zh"]
    old_pascal = managed.judge(_windows(managed, driver="552.22", name="NVIDIA GeForce GTX 1060", compute=(6, 1)))
    assert not old_pascal.ok and "560.76" in old_pascal.reason["en"]
    kepler = managed.judge(_windows(managed, driver="475.14", name="NVIDIA GeForce GTX 780", compute=(3, 5)))
    assert not kepler.ok and "太老" in kepler.reason["zh"]
    none = managed.judge(managed.Machine(system="win32", arch="AMD64", python_minor="3.13", nvidia_error="nvidia-smi not found"))
    assert not none.ok and "NVIDIA" in none.reason["zh"] and "用我自己装的" in none.reason["zh"]
    unknown = managed.judge(_windows(managed, compute=None))
    assert unknown.ok and unknown.flavour == "cu130" and unknown.warnings, "算力问不到:按 20 系及以上挑,并提醒装完会试一下显卡"


def test_别的平台这一版不装_说清楚换哪条路(managed) -> None:
    assert managed.judge(managed.Machine(**MAC)).flavour == "mps"
    for machine, word in [
        (managed.Machine(system="darwin", arch="x86_64", python_minor="3.13"), "Intel"),
        (_linux(managed, arch="aarch64"), "x86_64"),
        (managed.Machine(system="win32", arch="ARM64", python_minor="3.13"), "x64"),
    ]:
        verdict = managed.judge(machine)
        assert not verdict.ok and verdict.flavour == ""
        assert word in verdict.reason["zh"] and "连一台服务器" in verdict.reason["zh"] and "server" in verdict.reason["en"]


@pytest.mark.parametrize(("driver", "name", "compute", "flavour"), [
    ("580.65.06", "NVIDIA GeForce RTX 4090", (8, 9), "cu130"),
    ("580.95.05", "NVIDIA A100-SXM4-80GB", (8, 0), "cu130"),
    ("590.44.01", "NVIDIA GeForce RTX 2080 Ti", (7, 5), "cu130"),
    ("560.28.03", "Tesla P100-PCIE-16GB", (6, 0), "cu126"),
    ("575.57.08", "Tesla V100-SXM2-32GB", (7, 0), "cu126"),
])
def test_Linux_NVIDIA_同一张对照表_驱动下限按_Linux_那一列(managed, driver: str, name: str, compute, flavour: str) -> None:
    verdict = managed.judge(_linux(managed, driver=driver, name=name, compute=compute))
    assert verdict.ok and verdict.flavour == flavour
    assert verdict.platform["zh"].startswith("Linux + ") and name in verdict.platform["zh"] and driver in verdict.platform["en"]


def test_Linux_驱动太旧_ARM_glibc_太旧_没有_NVIDIA_都说清楚(managed) -> None:
    old = managed.judge(_linux(managed, driver="575.64.05", compute=(8, 9)))
    assert not old.ok and "580.65.06" in old.reason["zh"], "Linux 上 R580 要 580.65.06,不是 Windows 那一列的 580"
    old_pascal = managed.judge(_linux(managed, driver="555.42.06", name="Tesla P100", compute=(6, 0)))
    assert not old_pascal.ok and "560.28.03" in old_pascal.reason["en"]
    arm = managed.judge(_linux(managed, arch="aarch64"))
    assert not arm.ok and "x86_64" in arm.reason["zh"]
    centos7 = managed.judge(_linux(managed, libc="glibc-2.17"))
    assert not centos7.ok and "glibc 2.28" in centos7.reason["zh"] and "glibc 2.17" in centos7.reason["zh"]
    musl = managed.judge(_linux(managed, libc=""))
    assert not musl.ok and "musl" in musl.reason["zh"] and "musl" in musl.reason["en"]
    none = managed.judge(_linux(managed, gpus=False))
    assert not none.ok and none.platform["zh"] == "Linux,没找到 NVIDIA 显卡"
    assert "--gpus all" in none.reason["zh"] and "nvidia-smi" in none.reason["en"] and "用我自己装的" in none.reason["zh"]
    windows_none = managed.judge(managed.Machine(system="win32", arch="AMD64", python_minor="3.13"))
    assert "--gpus" not in windows_none.reason["zh"], "容器那一句只对 Linux 说"


def test_Linux_问一遍这台机器_C_库_nvidia_smi(managed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\necho 'MOSAEL_PY 3.13 x86_64 linux glibc-2.35'\n", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setattr(managed, "read_nvidia", lambda: ((580, 65, 6), (managed.Gpu("NVIDIA L4", 24 * GB, (8, 9)),), ""))
    machine = managed.probe_machine(python, "zh")
    assert (machine.system, machine.arch, machine.libc, machine.driver) == ("linux", "x86_64", "glibc-2.35", (580, 65, 6))
    assert machine.long_paths is True, "长路径只是 Windows 的事"
    python.write_text("#!/bin/sh\necho 'MOSAEL_PY 3.13 arm64 darwin -'\n", encoding="utf-8")
    monkeypatch.setattr(managed, "read_nvidia", lambda: pytest.fail("Mac 不问 nvidia-smi"))
    assert managed.probe_machine(python, "zh") == managed.Machine(system="darwin", arch="arm64", python_minor="3.13")


def test_PyTorch_三件钉死版本_CUDA_的带后缀_从哪个源装(managed) -> None:
    assert managed.torch_requirements("mps") == ["torch==2.14.1", "torchvision==0.29.1", "torchaudio==2.11.0"]
    assert managed.torch_requirements("cu130") == ["torch==2.14.1+cu130", "torchvision==0.29.1+cu130", "torchaudio==2.11.0+cu130"], \
        "带后缀:换了 CUDA 源 pip 才认得不是装着的那个,PyPI 上同版本号的 CPU 版也混不进来"
    sources = {"pip_index_url": "https://mirrors.aliyun.com/pypi/simple/", "pytorch_index_url": "https://mirror.nju.edu.cn/pytorch/whl/"}
    assert managed.torch_index("mps", sources) == "https://mirrors.aliyun.com/pypi/simple/", "Mac 的 PyTorch 是 PyPI 上的,走 pip 源"
    assert managed.torch_index("cu130", sources) == "https://mirror.nju.edu.cn/pytorch/whl/cu130"
    assert managed.torch_index("cu126", {"pip_index_url": "", "pytorch_index_url": ""}) == "https://download.pytorch.org/whl/cu126"


def test_Windows_的路径(managed, tmp_path: Path) -> None:
    assert managed.venv_python(tmp_path, windows=True) == tmp_path / ".venv" / "Scripts" / "python.exe"
    assert managed.venv_python(tmp_path, windows=False) == tmp_path / ".venv" / "bin" / "python"
    short = Path("C:/Users/me/.mosael/local-services/0123456789abcdef0123456789abcdef")
    long = Path("C:/Users/" + "x" * 80 + "/.mosael/local-services/0123456789abcdef0123456789abcdef")
    machine = _windows(managed, long_paths=False)
    assert managed._path_problem(short, machine) is None
    problem = managed._path_problem(long, machine)
    assert problem is not None and "LongPathsEnabled" in problem["zh"] and "259" in problem["en"]
    assert managed._path_problem(long, _windows(managed, long_paths=True)) is None, "开了长路径支持就不拦"


# ---- 安装计划 ----------------------------------------------------------------------


def test_安装计划_Mac_七步_要多少空间_从哪几处下(managed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(managed, "_free_space", lambda _root: 200 * GB)
    root = tmp_path / "local-services" / "abc"
    planned = managed.plan({"directory": str(root), "python": sys.executable,
                            "sources": {"github_mirror": "https://ghproxy.example/"}}, "zh", machine=managed.Machine(**MAC))
    assert planned["ok"] and planned["flavour"] == "mps" and planned["torch"]["zh"] == "PyTorch 2.14.1(MPS)"
    assert [one["key"] for one in planned["steps"]] == list(managed.STEPS) and not any(one["done"] for one in planned["steps"])
    assert planned["disk_bytes"] == 5 * GB and planned["free_bytes"] == 200 * GB and planned["problems"] == []
    urls = [one["url"] for one in planned["downloads"]]
    assert urls[0] == "https://ghproxy.example/" + managed.COMFYUI_PINNED["0.39.0"].url, "GitHub 上的接镜像前缀"
    assert urls[1] == urls[2] == "https://pypi.org/simple", "没配 pip 源:官方 PyPI"
    assert not root.exists(), "只看、不写"


def test_安装计划_空间不够_Windows_要_8_GB(managed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(managed, "_free_space", lambda _root: 6 * GB)
    planned = managed.plan({"directory": str(tmp_path / "x"), "python": sys.executable}, "en", machine=_windows(managed))
    assert planned["ok"] and planned["disk_bytes"] == 8 * GB
    assert [one["level"] for one in planned["problems"]] == ["error"] and "8.0 GB" in planned["problems"][0]["text"]["en"]
    mac = managed.plan({"directory": str(tmp_path / "x"), "python": sys.executable}, "en", machine=managed.Machine(**MAC))
    assert mac["problems"] == [], "Mac 5 GB 就够"


def test_安装计划_不能装的也摆出原因_不报空间(managed, tmp_path: Path) -> None:
    planned = managed.plan({"directory": str(tmp_path), "python": sys.executable}, "zh", machine=_linux(managed, gpus=False))
    assert not planned["ok"] and planned["flavour"] == "" and planned["downloads"] == [] and planned["problems"] == []
    assert "NVIDIA" in planned["verdict"]["zh"]


def test_安装计划_Linux_NVIDIA_走_PyTorch_源的_CUDA_频道_要_8_GB(managed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(managed, "_free_space", lambda _root: 200 * GB)
    planned = managed.plan({"directory": str(tmp_path / "x"), "python": sys.executable}, "zh", machine=_linux(managed))
    assert planned["ok"] and planned["flavour"] == "cu130" and planned["disk_bytes"] == 8 * GB
    assert planned["downloads"][1]["url"] == "https://download.pytorch.org/whl/cu130" and planned["downloads"][1]["source"] == "pytorch"


# ---- 安装:假的下载源、假的 Python --------------------------------------------------------


def _tarball(members: dict[str, bytes], top: str = "ComfyUI-0.39.0") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name if name.startswith(("/", "..")) else f"{top}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


COMFY_FILES = {
    "main.py": b"print('ComfyUI')\n",
    "comfy/__init__.py": b"",
    "comfyui_version.py": b'__version__ = "0.39.0"\n',
    "requirements.txt": b"torch\ncomfy-kitchen==0.2.37\n",
    "manager_requirements.txt": b"comfyui_manager==4.2.2\n",
    "custom_nodes/example_node.py.example": b"",
    "models/checkpoints/put_checkpoints_here": b"",
}

#: 假的 venv 解释器:回答 pip(记下参数、按字节报进度,按环境变量失败 / 慢)、试显卡、问 torch 的版本。
FAKE_VENV_PYTHON = r"""#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "pip" ] && [ "$3" = "freeze" ]; then
  echo "freeze" >> "$FAKE_LOG"
  if [ -n "$FAKE_FREEZE_FAIL" ]; then echo "ERROR: freeze broke"; exit 2; fi
  if [ -f "$FAKE_FREEZE" ]; then cat "$FAKE_FREEZE"; fi
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  echo "$*" >> "$FAKE_LOG"
  case "$*" in
    *"--no-deps"*) step=restore ;;
    *" -r "*) step=requirements ;;
    *"--upgrade"*" pip"*) step=pip ;;
    *) step=torch ;;
  esac
  echo "Collecting things for $step"
  if [ -n "$FAKE_PIP_SLEEP" ] && [ "$step" = "$FAKE_PIP_SLOW" ]; then
    i=0
    while [ $i -lt 600 ]; do echo "Progress $i of 600"; sleep "$FAKE_PIP_SLEEP"; i=$((i+1)); done
  fi
  if [ "$step" = "$FAKE_PIP_FAIL" ]; then
    echo "ERROR: Could not find a version that satisfies the requirement comfy-kitchen==0.2.37 (from versions: none)"
    echo "ERROR: No matching distribution found for comfy-kitchen==0.2.37"
    exit 1
  fi
  echo "  Downloading $step-1.0-py3-none-any.whl (3.0 MB)"
  echo "Progress 0 of 3000000"
  echo "Progress 1500000 of 3000000"
  echo "Progress 3000000 of 3000000"
  echo "Installing collected packages: $step"
  echo "Successfully installed $step-1.0"
  if [ "$step" = "requirements" ] && [ -n "$FAKE_TORCH_AFTER" ]; then echo "$FAKE_TORCH_AFTER" > "$FAKE_TORCH_FILE"; fi
  if [ "$step" = "requirements" ] && [ -n "$FAKE_FREEZE_AFTER" ]; then cp "$FAKE_FREEZE_AFTER" "$FAKE_FREEZE"; fi
  if [ "$step" = "restore" ] && [ -n "$FAKE_FREEZE_RESTORED" ]; then cp "$FAKE_FREEZE_RESTORED" "$FAKE_FREEZE"; fi
  exit 0
fi
if [ "$1" = "-c" ]; then
  case "$2" in
    *MOSAEL_TORCH*)
      echo "torch check" >> "$FAKE_LOG"
      if [ "$FAKE_GPU" = "broken" ]; then echo 'MOSAEL_TORCH {"ok": false, "error": "RuntimeError: no kernel image"}'; else echo 'MOSAEL_TORCH {"ok": true, "torch": "2.14.1"}'; fi ;;
    *MOSAEL_VERSION*)
      if [ -f "$FAKE_TORCH_FILE" ]; then echo "MOSAEL_VERSION $(cat "$FAKE_TORCH_FILE")"; else echo "MOSAEL_VERSION 2.14.1"; fi ;;
  esac
  exit 0
fi
exit 3
"""

#: 假的「随包 Python」:`-m venv <目录>` 建一个假 venv(两种系统的解释器路径都放,pyvenv.cfg 写 FAKE_MINOR)。
FAKE_BASE_PYTHON = r"""#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  echo "venv $3" >> "$FAKE_LOG"
  mkdir -p "$3/bin" "$3/Scripts"
  printf 'home = /fake\nversion = %s.15\n' "${FAKE_MINOR:-3.13}" > "$3/pyvenv.cfg"
  cp "$FAKE_VENV_SOURCE" "$3/bin/python"; cp "$FAKE_VENV_SOURCE" "$3/Scripts/python.exe"
  chmod +x "$3/bin/python" "$3/Scripts/python.exe"
  exit 0
fi
exit 4
"""


class Setup:
    def __init__(self, managed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.managed = managed
        self.service = sys.modules["service"]
        self.pinned = sys.modules["pinned"]
        self.root = tmp_path / "local-services" / "conn"
        self.log = tmp_path / "logs" / "service-install-conn.log"
        self.log.parent.mkdir(parents=True)
        self.calls = tmp_path / "calls.log"
        self.calls.write_text("", encoding="utf-8")
        venv_source = tmp_path / "fake-venv-python"
        venv_source.write_text(FAKE_VENV_PYTHON, encoding="utf-8")
        venv_source.chmod(0o755)
        self.base = tmp_path / "fake-base-python"
        self.base.write_text(FAKE_BASE_PYTHON, encoding="utf-8")
        self.base.chmod(0o755)
        for key, value in {"FAKE_LOG": str(self.calls), "FAKE_VENV_SOURCE": str(venv_source),
                           "FAKE_TORCH_FILE": str(tmp_path / "torch-version")}.items():
            monkeypatch.setenv(key, value)
        for key in ("FAKE_PIP_FAIL", "FAKE_PIP_SLEEP", "FAKE_PIP_SLOW", "FAKE_MINOR", "FAKE_GPU", "FAKE_TORCH_AFTER", "FAKE_FREEZE",
                    "FAKE_FREEZE_FAIL", "FAKE_FREEZE_AFTER", "FAKE_FREEZE_RESTORED"):
            monkeypatch.delenv(key, raising=False)
        self.tarballs = tmp_path / "tarballs"
        self.tarballs.mkdir()
        self.serve_comfy(_tarball(COMFY_FILES), monkeypatch)
        nodes = _tarball({"__init__.py": b"# pysssss\n"}, top="ComfyUI-Custom-Scripts-609f3af")
        source = tmp_path / "pysssss.tar.gz"
        source.write_bytes(nodes)
        monkeypatch.setattr(self.service, "PYSSSSS", dataclasses.replace(
            self.service.PYSSSSS, url=source.as_uri(), sha256=hashlib.sha256(nodes).hexdigest(), size=len(nodes)))
        monkeypatch.setattr(managed, "_free_space", lambda _root: 500 * GB)
        self.events: list[dict[str, Any]] = []

    def serve_comfy(self, data: bytes, monkeypatch: pytest.MonkeyPatch, *, sha: str | None = None, version: str = "0.39.0") -> None:
        """钉死的那个版本改成从本地这个文件下(sha256 按它算,或者故意给错的)。"""
        path = self.tarballs / f"ComfyUI-{version}.tar.gz"
        path.write_bytes(data)
        monkeypatch.setitem(self.managed.COMFYUI_PINNED, version, dataclasses.replace(
            self.managed.COMFYUI_PINNED[version], url=path.as_uri(), sha256=sha or hashlib.sha256(data).hexdigest(), size=len(data)))

    def payload(self, **extra: Any) -> dict[str, Any]:
        return {"directory": str(self.root), "python": str(self.base), "flavour": "mps", "log": str(self.log),
                "pip_cache": str(self.root.parent / "pip-cache"),
                "sources": {"pip_index_url": "https://pypi.example/simple", "pytorch_index_url": "https://torch.example/whl"},
                **extra}

    def install(self, machine=None, *, is_cancelled=None, **extra: Any) -> dict[str, Any]:
        kwargs = {"is_cancelled": is_cancelled} if is_cancelled is not None else {}
        return self.managed.install(self.payload(**extra), "zh", self.events.append,
                                    machine=machine or self.managed.Machine(**MAC), **kwargs)

    def record(self) -> dict[str, Any]:
        return json.loads((self.root / "mosael-install.json").read_text(encoding="utf-8"))

    def pip_calls(self) -> list[str]:
        return [line for line in self.calls.read_text(encoding="utf-8").splitlines() if line.startswith("-m pip install")]

    def reset_calls(self) -> None:
        self.calls.write_text("", encoding="utf-8")
        self.events.clear()


@pytest.fixture
def setup(managed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return Setup(managed, tmp_path, monkeypatch)


@posix_only
def test_装_七步按顺序_每步记一笔_交回装好的目录(setup: Setup) -> None:
    done = setup.install()
    root = setup.root
    assert done == {"directory": str(root), "python": str(root / ".venv" / "bin" / "python"), "python_minor": "3.13",
                    "comfyui": "0.39.0", "flavour": "mps"}
    record = setup.record()
    assert record["done"] == ["download", "extract", "venv", "torch", "requirements", "nodes"], "查空间每次都查,不记"
    assert (record["python_minor"], record["flavour"], record["comfyui"], record["version"]) == ("3.13", "mps", "0.39.0", 1)
    assert (root / "ComfyUI" / "main.py").is_file() and (root / "ComfyUI" / "models" / "checkpoints").is_dir()
    assert (root / "ComfyUI" / "custom_nodes" / "ComfyUI-Custom-Scripts" / "__init__.py").is_file()
    assert not list((root / "downloads").iterdir()), "源码包解完就删"
    pips = setup.pip_calls()
    assert len(pips) == 3, pips
    assert "--upgrade" in pips[0] and pips[0].endswith(" pip"), "先升 pip"
    assert pips[1].endswith("torch==2.14.1 torchvision==0.29.1 torchaudio==2.11.0")
    assert "--index-url https://pypi.example/simple" in pips[1], "Mac 的 PyTorch 走 pip 源"
    assert f"-r {root / 'ComfyUI' / 'requirements.txt'} -r {root / 'ComfyUI' / 'manager_requirements.txt'}" in pips[2]
    assert "--upgrade" not in pips[2], "不升级:requirements.txt 里没写版本的 torch 会被换成 PyPI 上的(Windows 上就是 CPU 版)"
    for call in pips:
        assert "--prefer-binary" in call and "--progress-bar raw" in call and "--timeout 60" in call
    assert "torch check" in setup.calls.read_text(encoding="utf-8"), "装完 PyTorch 试一下显卡"
    outline = setup.events[0]["outline"]
    assert [one["key"] for one in outline] == list(setup.managed.STEPS) and not any(one["done"] for one in outline)
    progress = [event for event in setup.events if event.get("key") == "torch" and event.get("done_bytes") is not None]
    assert progress and progress[-1]["total_bytes"] == 3_000_000 and progress[-1]["item"] == "torch-1.0-py3-none-any.whl"
    assert [event["key"] for event in setup.events if event.get("state") == "done"] == list(setup.managed.STEPS)
    log = setup.log.read_text(encoding="utf-8")
    assert "-m pip install" in log and "Progress 1500000" not in log, "完整输出落盘,raw 进度行不进日志"
    assert (root / "install.lock").exists()


@posix_only
def test_装_Windows_CUDA_走_PyTorch_源的那个频道_venv_是_Scripts_python_exe(setup: Setup) -> None:
    done = setup.install(setup.managed.Machine(system="win32", arch="AMD64", python_minor="3.13", driver=(581, 57),
                                               gpus=(setup.managed.Gpu("RTX 4090", 24 * GB, (8, 9)),)), flavour="cu130")
    assert done["python"] == str(setup.root / ".venv" / "Scripts" / "python.exe") and done["flavour"] == "cu130"
    torch = setup.pip_calls()[1]
    assert "--index-url https://torch.example/whl/cu130" in torch
    assert torch.endswith("torch==2.14.1+cu130 torchvision==0.29.1+cu130 torchaudio==2.11.0+cu130")
    assert "--index-url https://pypi.example/simple" in setup.pip_calls()[2], "依赖照样走 pip 源"


@posix_only
def test_装_Linux_CUDA_走_PyTorch_源的那个频道_venv_是_bin_python(setup: Setup) -> None:
    done = setup.install(_linux(setup.managed), flavour="cu130")
    assert done["python"] == str(setup.root / ".venv" / "bin" / "python") and done["flavour"] == "cu130"
    torch = setup.pip_calls()[1]
    assert "--index-url https://torch.example/whl/cu130" in torch
    assert torch.endswith("torch==2.14.1+cu130 torchvision==0.29.1+cu130 torchaudio==2.11.0+cu130")
    assert "--index-url https://pypi.example/simple" in setup.pip_calls()[2], "依赖照样走 pip 源"


@posix_only
def test_确认之后机器变了就不装(setup: Setup) -> None:
    with pytest.raises(_error_type(), match="重新看一下安装计划"):
        setup.install(flavour="cu130")
    assert not (setup.root / "mosael-install.json").exists()


@posix_only
def test_源码包_sha256_对不上_不解_不记(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    setup.serve_comfy(_tarball({**COMFY_FILES, "main.py": b"evil"}), monkeypatch, sha="0" * 64)
    with pytest.raises(_error_type(), match="sha256") as caught:
        setup.install()
    assert "镜像或代理" in str(caught.value)
    assert not (setup.root / "ComfyUI").exists() and list((setup.root / "downloads").iterdir()) == [], "半截的(.part)也不留"
    assert not (setup.root / "mosael-install.json").exists()
    assert "没装成" in setup.log.read_text(encoding="utf-8")


@posix_only
def test_源码包里有越界路径_不解(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    setup.serve_comfy(_tarball({**COMFY_FILES, "../../escaped.py": b"x"}), monkeypatch)
    with pytest.raises(_error_type(), match="解不开"):
        setup.install()
    assert not (setup.root / "ComfyUI").exists() and not (setup.root.parent / "escaped.py").exists()
    assert setup.record()["done"] == ["download"], "下载那一步做完了(sha256 对上了),解开没成"


@posix_only
def test_空间不够_不开始(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup.managed, "_free_space", lambda _root: 3 * GB)
    with pytest.raises(_error_type(), match="只剩 3.0 GB"):
        setup.install()
    assert not (setup.root / "downloads").exists() and setup.pip_calls() == []


@posix_only
def test_pip_失败说人话_换哪个源_再来从没做完的那一步接着装(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PIP_FAIL", "requirements")
    with pytest.raises(_error_type()) as caught:
        setup.install()
    said = caught.value.texts
    assert "装 ComfyUI 的依赖和 ComfyUI-Manager失败" in said["zh"] and "找不到要装的版本" in said["zh"]
    assert "pip 源" in said["zh"] and "接着装" in said["zh"], "依赖那一步:换 pip 源"
    assert "ERROR: No matching distribution found for comfy-kitchen==0.2.37" in said["zh"], "挑 pip 自己的结论行,不取尾巴"
    assert setup.record()["done"] == ["download", "extract", "venv", "torch"]
    monkeypatch.delenv("FAKE_PIP_FAIL")
    setup.reset_calls()
    setup.install()
    calls = setup.calls.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("venv ") for line in calls) and len(setup.pip_calls()) == 1 and " -r " in setup.pip_calls()[0], \
        "接着装:不重建 venv、不重装 torch,从依赖那一步开始"
    assert setup.record()["done"][-2:] == ["requirements", "nodes"]
    assert [one["done"] for one in setup.events[0]["outline"]] == [False, True, True, True, True, False, False]


def test_pip_失败_装_PyTorch_那一步说换_PyTorch_源_别的病因也认得出(managed, tmp_path: Path) -> None:
    job = managed._Job(root=tmp_path, base=tmp_path, machine=_windows(managed), flavour="cu130", sources={}, pip_cache="",
                       locale="zh", log=managed._Log(""), report=None, is_cancelled=lambda: False)  # type: ignore[arg-type]
    network = managed.explain_pip(job, ["Collecting torch", "  ReadTimeoutError: Read timed out.",
                                        "ERROR: note: This error originates from a subprocess",
                                        "ERROR: Could not install packages due to an OSError"], torch_step=True)
    assert "下载超时或断流" in network.texts["zh"] and "PyTorch 源" in network.texts["zh"], "CUDA 版 PyTorch:换 PyTorch 源"
    assert "note:" not in network.texts["zh"], "没信息的提示行不当结论"
    assert "PyTorch source" in network.texts["en"]
    disk = managed.explain_pip(job, ["ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device"],
                               torch_step=True)
    assert "磁盘空间不足" in disk.texts["zh"] and "清出空间" in disk.texts["zh"]
    mac = dataclasses.replace(job, flavour="mps")
    assert "pip 源" in managed.explain_pip(mac, ["ERROR: No matching distribution found for torch==2.14.1"], torch_step=True).texts["zh"], \
        "Mac 的 PyTorch 本来就从 pip 源来"
    unknown = managed.explain_pip(job, ["something odd"], torch_step=False)
    assert "pip 没说清原因" in unknown.texts["zh"] and "日志" in unknown.texts["zh"]


@posix_only
def test_装好的_PyTorch_用不了显卡_说清楚_这一步不记(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_GPU", "broken")
    with pytest.raises(_error_type(), match="用不了 Apple 显卡"):
        setup.install()
    assert setup.record()["done"] == ["download", "extract", "venv"]


@posix_only
def test_装依赖时_torch_被换掉了_说清楚_接着装把它装回来(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_TORCH_AFTER", "2.15.0")
    with pytest.raises(_error_type(), match="PyTorch 被换掉了"):
        setup.install()
    assert "torch" not in setup.record()["done"], "torch 那一步作废"


@posix_only
def test_取消_下载中_停在那一步_半截的不留下_接着装(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    asked = {"n": 0}

    def cancel_on_second_look() -> bool:
        asked["n"] += 1
        return asked["n"] >= 2

    monkeypatch.setattr(setup.pinned, "CHUNK", 1)  # 一个字节一读:下到一半看第二眼时取消
    with pytest.raises(setup.pinned.Cancelled):
        setup.install(is_cancelled=cancel_on_second_look)
    assert not (setup.root / "downloads" / "ComfyUI-0.39.0.tar.gz.part").exists(), "半截的不留下"
    assert not (setup.root / "mosael-install.json").exists(), "一步都没做完,没有可记的"
    assert "取消了" in setup.log.read_text(encoding="utf-8")
    monkeypatch.setattr(setup.pinned, "CHUNK", 256 * 1024)
    setup.install()
    assert setup.record()["done"] == ["download", "extract", "venv", "torch", "requirements", "nodes"]


@posix_only
def test_取消_pip_中_停掉_pip_记到上一步_接着装从这一步开始(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PIP_SLEEP", "0.05")
    monkeypatch.setenv("FAKE_PIP_SLOW", "torch")
    flag = threading.Event()
    seen: list[str] = []

    def emit(event: dict[str, Any]) -> None:
        seen.append(json.dumps(event))
        if event.get("key") == "torch" and (event.get("done_bytes") or 0) >= 5:
            flag.set()

    started = time.monotonic()
    with pytest.raises(setup.pinned.Cancelled):
        setup.managed.install(setup.payload(), "zh", emit, machine=setup.managed.Machine(**MAC), is_cancelled=flag.is_set)
    assert time.monotonic() - started < 20, "pip 被停掉,不是等它跑完 600 行"
    assert setup.record()["done"] == ["download", "extract", "venv"]
    monkeypatch.delenv("FAKE_PIP_SLEEP")
    setup.reset_calls()
    setup.install()
    assert setup.pip_calls()[0].endswith("torchaudio==2.11.0"), "从 torch 那一步接着装"


@posix_only
def test_Python_小版本变了_只重建_venv_和包_源码_模型_pysssss_不动(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MINOR", "3.12")
    setup.install(setup.managed.Machine(system="darwin", arch="arm64", python_minor="3.12"))
    model = setup.root / "ComfyUI" / "models" / "checkpoints" / "mine.safetensors"
    model.write_bytes(b"weights")
    old_marker = setup.root / ".venv" / "old-3.12"
    old_marker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("FAKE_MINOR", "3.13")
    setup.reset_calls()
    planned = setup.managed.plan(setup.payload(), "zh", machine=setup.managed.Machine(**MAC))
    assert [one["key"] for one in planned["steps"] if not one["done"]] == ["disk", "venv", "torch", "requirements"]
    setup.install()
    assert model.read_bytes() == b"weights", "模型不动"
    assert not old_marker.exists(), "旧的 venv 删掉重建"
    calls = setup.calls.read_text(encoding="utf-8").splitlines()
    assert calls[0].startswith("venv ") and len(setup.pip_calls()) == 3
    record = setup.record()
    assert record["python_minor"] == "3.13" and record["done"] == ["download", "extract", "venv", "torch", "requirements", "nodes"]


@posix_only
def test_PyTorch_种类变了_只重装_PyTorch(setup: Setup) -> None:
    """换了驱动(cu126 → cu130)这一类:记录里的种类和这次的对不上,只有 torch 那一步重来(带后缀的版本 pip 才会换)。"""
    setup.install()
    record = {**setup.record(), "flavour": "cu126"}
    (setup.root / "mosael-install.json").write_text(json.dumps(record), encoding="utf-8")
    setup.reset_calls()
    setup.install()
    pips = setup.pip_calls()
    assert len(pips) == 1 and pips[0].endswith("torchaudio==2.11.0"), "只重装 PyTorch"
    assert setup.record()["flavour"] == "mps"


@posix_only
def test_同一个目录两次一起装_第二次直说(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PIP_SLEEP", "0.05")
    monkeypatch.setenv("FAKE_PIP_SLOW", "torch")
    stop = threading.Event()
    first = threading.Thread(target=lambda: _quietly(lambda: setup.install(is_cancelled=stop.is_set)), daemon=True)
    first.start()
    deadline = time.monotonic() + 20
    while not (setup.root / "install.lock").exists() or not setup.pip_calls():
        assert time.monotonic() < deadline
        time.sleep(0.05)
    try:
        with pytest.raises(_error_type(), match="另一次安装"):
            setup.managed.install(setup.payload(), "zh", lambda _event: None, machine=setup.managed.Machine(**MAC))
    finally:
        stop.set()
        first.join(timeout=30)


def _quietly(work) -> None:
    try:
        work()
    except BaseException:  # noqa: BLE001
        pass


def test_记录对不上的那几步作废_连同靠它的(managed, tmp_path: Path) -> None:
    root = tmp_path
    (root / "ComfyUI" / "custom_nodes" / "ComfyUI-Custom-Scripts").mkdir(parents=True)
    (root / "ComfyUI" / "main.py").write_text("", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (root / ".venv" / "pyvenv.cfg").write_text("version = 3.13.15\n", encoding="utf-8")
    everything = ["download", "extract", "venv", "torch", "requirements", "nodes"]
    record = {"done": everything, "python_minor": "3.13", "flavour": "mps"}
    assert managed.done_steps(root, record, python_minor="3.13", flavour="mps", windows=False) == set(everything)
    assert managed.done_steps(root, {**record, "python_minor": "3.12"}, python_minor="3.13", flavour="mps", windows=False) == \
        {"download", "extract", "nodes"}, "Python 换了:venv 和装进去的包作废,源码、pysssss 不动"
    assert managed.done_steps(root, record, python_minor="3.13", flavour="cu130", windows=False) == set(everything) - {"torch"}
    (root / "ComfyUI" / "main.py").unlink()
    assert managed.done_steps(root, record, python_minor="3.13", flavour="mps", windows=False) == \
        {"venv", "torch", "requirements"}, "源码不在了:重下(解完压缩包就删了)、重解,pysssss 跟着重装"
    assert managed.done_steps(root, {**record, "done": ["download"]}, python_minor="3.13", flavour="mps", windows=False) == set(), \
        "下载记着做完了、压缩包却不在(也没解开):重下"
    assert "venv" not in managed.done_steps(root, record, python_minor="3.13", flavour="mps", windows=True), \
        "Windows 上找的是 Scripts\\python.exe"


def test_主入口_安装计划走一问一答_装走流式(tmp_path: Path) -> None:
    import subprocess

    request = {"tool": "comfyui_generation", "locale": "en",
               "input": {"op": "service_plan", "directory": str(tmp_path / "x"), "python": sys.executable}}
    env = {key: value for key, value in os.environ.items() if key != "SERVER_URL"}
    result = subprocess.run([sys.executable, str(TOOLS / "main.py")], input=json.dumps(request), capture_output=True,
                            text=True, env=env, timeout=120)
    response = json.loads(result.stdout.strip().splitlines()[-1])
    assert response["ok"] is True and [one["key"] for one in response["output"]["steps"]][0] == "disk"
    request["input"] = {"op": "service_install", "directory": str(tmp_path / "x"), "python": str(tmp_path / "no-such-python")}
    result = subprocess.run([sys.executable, str(TOOLS / "main.py")], input=json.dumps(request), capture_output=True,
                            text=True, env=env, timeout=120)
    response = json.loads(result.stdout.strip().splitlines()[-1])
    assert response["ok"] is False and "doesn't exist" in response["error"]["en"]
    for op, check in (("service_versions", lambda one: one["ok"] and one["output"]["latest"] == "0.39.0"),
                      ("service_update", lambda one: not one["ok"] and "isn't fully installed" in one["error"]["en"]),
                      ("service_rollback", lambda one: not one["ok"] and "no earlier version" in one["error"]["en"])):
        request["input"] = {"op": op, "directory": str(tmp_path / "x")}
        result = subprocess.run([sys.executable, str(TOOLS / "main.py")], input=json.dumps(request), capture_output=True,
                                text=True, env=env, timeout=120)
        assert check(json.loads(result.stdout.strip().splitlines()[-1])), (op, result.stdout)


# ---- 换版本(versions:更新、回到上一版、被打断之后收拾)------------------------------------------


COMFY_OLD_FILES = {
    **COMFY_FILES,
    "main.py": b"print('ComfyUI 0.38')\n",
    "comfyui_version.py": b'__version__ = "0.38.0"\n',
    "requirements.txt": b"torch\ncomfy-kitchen==0.2.36\n",
}
COMFY_NEW_FILES = {**COMFY_FILES, "models/frame_interpolation/put_here": b"",
                   "custom_nodes/websocket_image_save.py": b"# 0.39\n", "input/example.png": b"png"}
#: 装着 0.38.0 时 pip freeze 说的;装 0.39.0 的依赖之后说的(前一个包升了版本、多了一个)。PyTorch 那一行、-e、@ 地址的不进对比。
FREEZE_OLD = "comfy-kitchen==0.2.36\ntorch==2.14.1\nPillow==11.0.0\n-e vcs+https://example/x#egg=x\nlocal @ file:///tmp/l.whl\n"
FREEZE_NEW = "comfy-kitchen==0.2.37\ntorch==2.15.0\nPillow==11.0.0\nnewpkg==2.0\n-e vcs+https://example/x#egg=x\n"


class Versions:
    """装着 0.38.0 的一份(两种版本的源码包都从本地下),里面放好五样东西,pip freeze 按文件回答。"""

    def __init__(self, setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import versions

        self.setup = setup
        self.module = versions
        setup.serve_comfy(_tarball(COMFY_OLD_FILES, top="ComfyUI-0.38.0"), monkeypatch, version="0.38.0")
        setup.serve_comfy(_tarball(COMFY_NEW_FILES), monkeypatch, version="0.39.0")
        self.freeze = tmp_path / "freeze.txt"
        self.freeze.write_text(FREEZE_OLD, encoding="utf-8")
        (tmp_path / "freeze-old.txt").write_text(FREEZE_OLD, encoding="utf-8")
        (tmp_path / "freeze-new.txt").write_text(FREEZE_NEW, encoding="utf-8")
        monkeypatch.setenv("FAKE_FREEZE", str(self.freeze))
        monkeypatch.setenv("FAKE_FREEZE_RESTORED", str(tmp_path / "freeze-old.txt"))
        setup.install(version="0.38.0")
        monkeypatch.setenv("FAKE_FREEZE_AFTER", str(tmp_path / "freeze-new.txt"))  # 装好以后再装依赖才是新版本的那一套
        source = setup.root / "ComfyUI"
        self.mine = {
            source / "models" / "checkpoints" / "mine.safetensors": b"weights",
            source / "custom_nodes" / "my-node" / "__init__.py": b"# mine",
            source / "user" / "default" / "workflows" / "w.json": b"{}",
            source / "input" / "photo.png": b"in",
            source / "output" / "out.png": b"out",
        }
        for path, data in self.mine.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        setup.reset_calls()

    def payload(self, **extra: Any) -> dict[str, Any]:
        return {key: value for key, value in self.setup.payload(**extra).items() if key not in ("python", "flavour")}

    def update(self, **extra: Any) -> dict[str, Any]:
        return self.module.update(self.payload(**extra), "zh", self.setup.events.append)

    def rollback(self) -> dict[str, Any]:
        return self.module.rollback(self.payload(), "zh", self.setup.events.append)

    def versions(self) -> dict[str, Any]:
        return self.module.versions({"directory": str(self.setup.root)}, "zh")

    def launch(self) -> dict[str, Any]:
        return self.module.launch({"directory": str(self.setup.root), "port": 8189}, "zh")

    def version_on_disk(self) -> str:
        return (self.setup.root / "ComfyUI" / "comfyui_version.py").read_text(encoding="utf-8")

    def assert_mine_in_place(self) -> None:
        for path, data in self.mine.items():
            assert path.read_bytes() == data, path

    def assert_back_on_old(self) -> None:
        root = self.setup.root
        assert '"0.38.0"' in self.version_on_disk()
        self.assert_mine_in_place()
        for name in ("ComfyUI.next", "ComfyUI.previous", "ComfyUI.discarded", "ComfyUI.skeleton"):
            assert not (root / name).exists(), name
        record = self.setup.record()
        assert record["comfyui"] == "0.38.0" and not {"previous", "updating", "restoring"} & set(record), record
        assert not list(root.glob("pip-freeze-*.txt"))


@pytest.fixture
def versioned(setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Versions:
    return Versions(setup, tmp_path, monkeypatch)


@posix_only
def test_更新_新源码解到旁边_先记下包_换上_五样搬过去_装新依赖_上一版留着(versioned: Versions) -> None:
    root = versioned.setup.root
    assert versioned.versions() == {"current": "0.38.0", "latest": "0.39.0", "update": "0.39.0", "previous": "", "unfinished": ""}
    done = versioned.update()
    assert done == {"directory": str(root), "python": str(root / ".venv" / "bin" / "python"), "comfyui": "0.39.0",
                    "previous": "0.38.0"}
    assert '"0.39.0"' in versioned.version_on_disk()
    versioned.assert_mine_in_place()
    assert (root / "ComfyUI" / "models" / "frame_interpolation" / "put_here").is_file(), "新版本多出来的模型目录补进来"
    assert (root / "ComfyUI" / "custom_nodes" / "websocket_image_save.py").read_bytes() == b"# 0.39\n", \
        "新包自带的、旧的里没有的补进来"
    assert (root / "ComfyUI" / "custom_nodes" / "ComfyUI-Custom-Scripts" / "__init__.py").is_file(), "pysssss 跟着搬过来"
    previous = root / "ComfyUI.previous"
    assert '"0.38.0"' in (previous / "comfyui_version.py").read_text(encoding="utf-8"), "上一版留在旁边"
    assert not any((previous / name).exists() for name in ("models", "custom_nodes", "user", "input", "output")), \
        "五样搬走了,不留两份"
    assert (root / "pip-freeze-0.38.0.txt").read_text(encoding="utf-8") == FREEZE_OLD, "装依赖之前记下的那一份"
    assert not (root / "ComfyUI.next").exists() and not (root / "ComfyUI.skeleton").exists()
    record = versioned.setup.record()
    assert record["comfyui"] == "0.39.0" and record["previous"] == {"version": "0.38.0", "freeze": "pip-freeze-0.38.0.txt"}
    assert "updating" not in record and record["done"] == ["download", "extract", "venv", "torch", "requirements", "nodes"]
    calls = versioned.setup.calls.read_text(encoding="utf-8").splitlines()
    assert calls.index("freeze") < next(i for i, line in enumerate(calls) if " -r " in line), "先 freeze 再装依赖"
    pips = versioned.setup.pip_calls()
    assert len(pips) == 1 and f"-r {root / 'ComfyUI' / 'requirements.txt'}" in pips[0] and "--upgrade" not in pips[0]
    assert not [line for line in calls if line.startswith("venv ")], "venv 不重建"
    outline = versioned.setup.events[0]["outline"]
    assert [one["key"] for one in outline] == list(versioned.module.UPDATE_STEPS)
    assert "0.39.0" in outline[1]["title"]["zh"]
    assert versioned.versions() == {"current": "0.39.0", "latest": "0.39.0", "update": "", "previous": "0.38.0", "unfinished": ""}


@posix_only
def test_回到上一版_五样搬回去_只把变了的包按_freeze_装回_新的那份删掉(versioned: Versions) -> None:
    versioned.update()
    versioned.setup.reset_calls()
    done = versioned.rollback()
    assert done["comfyui"] == "0.38.0"
    versioned.assert_back_on_old()
    pips = versioned.setup.pip_calls()
    assert len(pips) == 1 and pips[0].endswith("--no-deps comfy-kitchen==0.2.36"), \
        "只装回变了的;PyTorch、-e、@ 地址的不动,多出来的包留着"
    assert "--index-url https://pypi.example/simple" in pips[0]
    assert [one["key"] for one in versioned.setup.events[0]["outline"]] == list(versioned.module.ROLLBACK_STEPS)
    assert versioned.versions() == {"current": "0.38.0", "latest": "0.39.0", "update": "0.39.0", "previous": "", "unfinished": ""}
    with pytest.raises(_error_type(), match="没有可以回去的上一版"):
        versioned.rollback()


@posix_only
def test_再更新一次_上一版又留着_已经是最新的_没钉死的版本都不换(versioned: Versions) -> None:
    versioned.update()
    versioned.rollback()
    versioned.update()
    assert versioned.versions()["previous"] == "0.38.0" and (versioned.setup.root / "pip-freeze-0.38.0.txt").is_file()
    with pytest.raises(_error_type(), match="不比 0.39.0 旧"):
        versioned.update()
    with pytest.raises(_error_type(), match="没有钉死"):
        versioned.update(version="9.9.9")


@posix_only
def test_更新_装依赖失败_自己换回去_说已经换回(versioned: Versions, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PIP_FAIL", "requirements")
    with pytest.raises(_error_type()) as caught:
        versioned.update()
    text = str(caught.value)
    assert "源上找不到" in text and "已经换回 0.38.0" in text, text
    assert "装新版本的依赖" in text and "再「更新」" in text and "接着装" not in text, "说的是这一步、点哪个再来"
    versioned.assert_back_on_old()
    assert not [call for call in versioned.setup.pip_calls() if "--no-deps" in call], "包没变(装依赖没成),不用装回"
    assert "已经换回 0.38.0" in versioned.setup.log.read_text(encoding="utf-8")


@posix_only
def test_更新_换上之前出错_原来的没动(versioned: Versions, monkeypatch: pytest.MonkeyPatch) -> None:
    versioned.setup.serve_comfy(_tarball(COMFY_NEW_FILES), monkeypatch, sha="0" * 64)
    with pytest.raises(_error_type(), match="还是 0.38.0") as caught:
        versioned.update()
    assert "sha256" in str(caught.value)
    versioned.assert_back_on_old()
    assert "freeze" not in versioned.setup.calls.read_text(encoding="utf-8"), "下载没成,还没到 freeze"


@posix_only
def test_更新_换源码时改名失败_换回去(versioned: Versions, monkeypatch: pytest.MonkeyPatch) -> None:
    real = versioned.module._carry

    def carry(job, origin, destination, *, fresh):
        if fresh:
            real(job, origin, destination, fresh=fresh)  # 都搬过去了,最后一下(Windows 上一个文件被占着)失败
            raise PermissionError("[WinError 32] The process cannot access the file")
        return real(job, origin, destination, fresh=fresh)

    monkeypatch.setattr(versioned.module, "_carry", carry)
    with pytest.raises(_error_type(), match="WinError 32") as caught:
        versioned.update()
    assert "已经换回 0.38.0" in str(caught.value)
    versioned.assert_back_on_old()


@posix_only
def test_更新_取消_换回去再停(versioned: Versions, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PIP_SLEEP", "0.05")
    monkeypatch.setenv("FAKE_PIP_SLOW", "requirements")
    flag = threading.Event()

    def emit(event: dict[str, Any]) -> None:
        if event.get("key") == "requirements" and (event.get("done_bytes") or 0) >= 5:
            flag.set()

    with pytest.raises(versioned.setup.pinned.Cancelled):
        versioned.module.update(versioned.payload(), "zh", emit, is_cancelled=flag.is_set)
    versioned.assert_back_on_old()


@posix_only
def test_被强行打断_标记留着_不起_不接着装_换回收拾干净(versioned: Versions) -> None:
    versioned.update()
    # 后端在装新依赖时被杀:源码换好了、包装了一半、「换到一半」的标记还在
    record = versioned.setup.record()
    record["updating"] = "0.39.0"
    (versioned.setup.root / "mosael-install.json").write_text(json.dumps(record), encoding="utf-8")
    assert versioned.versions() == {"current": "0.39.0", "latest": "0.39.0", "update": "", "previous": "0.38.0",
                                    "unfinished": "update"}
    with pytest.raises(_error_type(), match="换回 0.38.0"):
        versioned.launch()
    with pytest.raises(_error_type(), match="没做完"):
        versioned.setup.install()
    with pytest.raises(_error_type(), match="没做完"):
        versioned.update()
    versioned.rollback()
    versioned.assert_back_on_old()
    assert versioned.launch()["argv"][1] == str(versioned.setup.root / "ComfyUI" / "main.py"), "收拾好了就能起"


@posix_only
def test_打断在改名之前_回退只收拾_源码一直是原来那份(versioned: Versions) -> None:
    root = versioned.setup.root
    record = versioned.setup.record()
    (root / "pip-freeze-0.38.0.txt").write_text(FREEZE_OLD, encoding="utf-8")
    (root / "ComfyUI.next").mkdir()
    record.update({"previous": {"version": "0.38.0", "freeze": "pip-freeze-0.38.0.txt"}, "updating": "0.39.0"})
    (root / "mosael-install.json").write_text(json.dumps(record), encoding="utf-8")
    assert versioned.versions()["unfinished"] == "update"
    versioned.rollback()
    versioned.assert_back_on_old()
    assert not versioned.setup.pip_calls(), "依赖没动过"


@posix_only
def test_打断在搬五样的中途_换回时旧的那份里的真数据不当占位删(versioned: Versions) -> None:
    """改名做完、models 还没搬过去就断了(新源码里是新包自带的占位 models,真的那份还在旧源码里):换回时旧的那份里已经有
    models,新源码里那个占位的留在原处、跟着换下来的源码删掉;真的 models 一个文件都不少。"""
    root = versioned.setup.root
    (root / "pip-freeze-0.38.0.txt").write_text(FREEZE_OLD, encoding="utf-8")
    (root / "ComfyUI").replace(root / "ComfyUI.previous")
    new = root / "ComfyUI"
    (new / "models" / "checkpoints").mkdir(parents=True)
    (new / "models" / "checkpoints" / "put_checkpoints_here").write_bytes(b"")
    (new / "main.py").write_text("print('0.39')\n", encoding="utf-8")
    (new / "comfyui_version.py").write_text('__version__ = "0.39.0"\n', encoding="utf-8")
    for name in ("custom_nodes", "user", "input", "output"):
        (root / "ComfyUI.previous" / name).replace(new / name)
    record = versioned.setup.record()
    record.update({"comfyui": "0.39.0", "previous": {"version": "0.38.0", "freeze": "pip-freeze-0.38.0.txt"}, "updating": "0.39.0"})
    (root / "mosael-install.json").write_text(json.dumps(record), encoding="utf-8")
    versioned.rollback()
    versioned.assert_back_on_old()


@posix_only
def test_回退_装回依赖失败_停在那里_下次接着装回(versioned: Versions, monkeypatch: pytest.MonkeyPatch) -> None:
    versioned.update()
    monkeypatch.setenv("FAKE_PIP_FAIL", "restore")
    with pytest.raises(_error_type(), match="把版本变了的包装回") as caught:
        versioned.rollback()
    assert "pip 源再「换回 0.38.0」" in str(caught.value), "点哪个再来:换回,不是接着装"
    assert '"0.38.0"' in versioned.version_on_disk(), "源码已经换回来了"
    versioned.assert_mine_in_place()
    assert versioned.versions() == {"current": "0.38.0", "latest": "0.39.0", "update": "", "previous": "0.38.0",
                                    "unfinished": "rollback"}
    with pytest.raises(_error_type(), match="没做完"):
        versioned.launch()
    monkeypatch.delenv("FAKE_PIP_FAIL")
    versioned.setup.reset_calls()
    versioned.rollback()
    versioned.assert_back_on_old()
    assert len(versioned.setup.pip_calls()) == 1


@posix_only
def test_换下来的源码里是链接_只删链接_不跟着出去(versioned: Versions, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    versioned.update()
    (versioned.setup.root / "ComfyUI" / "linked").symlink_to(outside, target_is_directory=True)
    versioned.rollback()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep", "删换下来的那份时链接只删链接"
    versioned.assert_back_on_old()


def test_换版本_还没装好的不让换(managed, tmp_path: Path) -> None:
    import versions

    with pytest.raises(_error_type(), match="还没装好"):
        versions.update({"directory": str(tmp_path)}, "zh", lambda _event: None)
    assert versions.versions({"directory": str(tmp_path / "nothing")}, "zh") == \
        {"current": "", "latest": "0.39.0", "update": "", "previous": "", "unfinished": ""}
