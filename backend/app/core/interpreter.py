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
import sys
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


def base_python() -> str:
    """用来**创建**托管 venv 的解释器。找不到可用的返回空串。

    顺序:壳注入的独立解释器 → 本进程的解释器(开发时是真 Python)→ PATH 上的 python3。
    """
    injected = os.environ.get(BASE_PYTHON_ENV, "").strip()
    if injected and Path(injected).is_file():
        return injected
    mine = self_python()
    if mine and Path(mine).is_file():
        return mine
    found = shutil.which("python3") or shutil.which("python")
    return found or ""
