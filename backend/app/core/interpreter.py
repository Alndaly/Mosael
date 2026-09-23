"""「哪个可执行文件是一个真 Python」——**全项目只在这里回答一次**。

打包版的后端是 PyInstaller 冻结二进制:`sys.executable` 指向**应用自己**,不是解释器。拿它
去 `-m venv` 不会建出环境,只会把整个后端再启动一遍 —— Windows 上用户看到的就是这一幕:

    创建运行环境失败:… ERROR: [Errno 10048] error while attempting to bind on
    address ('127.0.0.1', 8800) … INFO: Mosael backend shutting down

"创建失败的原因"里印的其实是另一个自己的启动日志。同样地,探测「这个解释器装了 f5_tts 吗」
是要**执行**它的,拿冻结的 exe 去探同样会再起一个后端。

这个答案本来写对过一次(在 tts_config 里),但它住在 TTS 专属模块中,转写那边没找到,于是
又抄了一份 `sys.executable` —— 同一个问题两处回答,又一次。所以搬到这里,谁都能找到。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

#: 壳(Electron)把随包分发的独立 CPython 路径经这个环境变量注入进来。
BASE_PYTHON_ENV = "MOSAEL_TTS_BASE_PYTHON"


def is_frozen() -> bool:
    """跑在 PyInstaller 打出来的二进制里。"""
    return bool(getattr(sys, "frozen", False))


def self_python() -> str:
    """本进程的解释器 —— **冻结时没有这个东西**,返回空串。

    调用方要么用它,要么承认"这里没有解释器",而不是把应用自己当解释器使。
    """
    return "" if is_frozen() else sys.executable


#: 开发时,`pnpm fetch:tts-python` 把随包的那个解释器抓到仓库里的这个位置。
REPO_BUNDLED_PYTHON = Path(__file__).resolve().parents[3] / "build" / "python" / (
    "python.exe" if sys.platform == "win32" else "bin/python3"
)


def base_python() -> str:
    """用来**创建**托管 venv 的解释器。找不到可用的返回空串。

    顺序:壳注入的独立解释器 → 开发时仓库里那一份随包解释器 → 本进程的解释器 → PATH 上的 python3。

    开发时也优先用随包那一份,而不是后端自己:两者次版本可以不同(后端 3.14,随包 3.13 ——
    whisperx 还不支持 3.14),而托管 venv 装什么、装不装得上,取决于建它的解释器。开发时用的
    不是用户那一个,就是在验一个用户不会遇到的环境。
    """
    injected = os.environ.get(BASE_PYTHON_ENV, "").strip()
    if injected and Path(injected).is_file():
        return injected
    if not is_frozen() and REPO_BUNDLED_PYTHON.is_file():
        return str(REPO_BUNDLED_PYTHON)
    mine = self_python()
    if mine and Path(mine).is_file():
        return mine
    found = shutil.which("python3") or shutil.which("python")
    return found or ""


def python_minor(python: str) -> str:
    """这个解释器的「主.次」版本,如 `3.14`。跑不起来返回空串。

    就是本进程的话直接读,不再起一个子进程 —— 开发时 base_python() 往往就是它自己。
    """
    try:
        if Path(python).resolve() == Path(sys.executable).resolve() and not is_frozen():
            return f"{sys.version_info.major}.{sys.version_info.minor}"
    except OSError:
        return ""
    from app.core.child_process import run_logged

    try:
        done = run_logged([python, "-V"], capture_output=True, text=True, timeout=30, what="读解释器版本")
    except (OSError, subprocess.SubprocessError):
        return ""
    # 「Python 3.14.7」—— 只要主.次。
    parts = done.stdout.strip().removeprefix("Python ").split(".") if done.returncode == 0 else []
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() else ""


def venv_python_minor(venv: Path) -> str:
    """一个 venv 是用哪个「主.次」版本建的 —— 读 `pyvenv.cfg`,不执行里面的解释器。

    执行不了正是要判断的情形之一:建它的那个解释器可能已经随旧版应用一起没了。
    """
    try:
        text = (venv / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("version", "version_info"):
            parts = value.strip().split(".")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                return f"{parts[0]}.{parts[1]}"
    return ""


def drop_venvs_built_on_another_python(roots: Iterable[Path]) -> list[Path]:
    """托管 venv(`<root>/venv-*`)是用**另一个次版本**的解释器建的,就删掉。返回删了哪些。

    venv 不能跨次版本用:它的 site-packages 在 `lib/python3.X/` 下,编译过的扩展绑着那个 ABI,
    而建它的解释器(随包那个)会随应用升级被换掉。留着它,引擎看起来「装好了」却一跑就炸;
    删掉,引擎回到「未安装」,用户点一次下载就用现在的解释器重建。模型权重不在 venv 里,不受影响。

    认不出版本(没有 pyvenv.cfg)的不动 —— 那不是我们建的,或者是半截的,都轮不到这里判。
    """
    base = base_python()
    want = python_minor(base) if base else ""
    if not want:
        return []
    dropped: list[Path] = []
    for root in roots:
        for venv in sorted(root.glob("venv-*")):
            have = venv_python_minor(venv)
            if have and have != want:
                shutil.rmtree(venv, ignore_errors=True)
                dropped.append(venv)
    return dropped
