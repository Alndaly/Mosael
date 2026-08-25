"""打包版的后端**不是一个 Python 解释器**,也**没有 .py 源文件在盘上**。

Windows 打包版上,用户点「下载」拿到两条报错,它们是同一件事的两面:

    创建运行环境失败:… ERROR: [Errno 10048] error while attempting to bind on
    address ('127.0.0.1', 8800) … INFO: Open Studio backend shutting down

    …\\resources\\python\\python.exe: can't open file
    '…\\_internal\\app\\audio\\tts_worker.py': [Errno 2] No such file or directory

第一条:`[sys.executable, "-m", "venv", …]` —— 在 PyInstaller 冻结进程里 `sys.executable`
就是**应用自己**,于是"创建运行环境"把整个后端又启动了一遍,撞在 8800 上,再把 uvicorn 的
启动日志当成"创建失败的原因"端给用户。

第二条:worker 是被**另一个解释器当脚本跑**的,所以它必须是盘上一个真文件;而冻结之后
`app/ai/runtime/workers/tts.py` 只存在于归档里,`Path(__file__).with_name()` 指向一个不存在的路径。

「哪个解释器是真 Python」这件事其实**早就答对过一次** —— `base_python()` 就是为这个写的,
连注释都写着"打包版 sys.executable 指向它自己"。它只是住在 TTS 专属模块里,转写那边没找到,
于是又抄了一份 `sys.executable`。同一个问题两处回答,又一次。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib
import sys

import pytest

from app.core import interpreter


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    """假装自己是打包版:sys.frozen 为真,sys.executable 指向那个 .exe。"""
    fake_exe = tmp_path / "Open Studio.exe"
    fake_exe.write_text("not a python", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    return fake_exe


def test_the_frozen_exe_is_never_offered_as_an_interpreter(frozen, monkeypatch) -> None:
    """冻结的 .exe 拿去 `-m venv` 只会把后端再启动一遍(用户看到的 10048 就是这个)。"""
    monkeypatch.delenv("OPEN_STUDIO_TTS_BASE_PYTHON", raising=False)
    monkeypatch.setattr(interpreter.shutil, "which", lambda name: None)

    assert interpreter.base_python() == "", "把应用自己当成了 Python"


def test_the_shell_can_hand_us_a_real_one(frozen, monkeypatch, tmp_path) -> None:
    """壳随包带了一个独立 CPython,经环境变量指进来 —— 那个才是能建 venv 的。"""
    real = tmp_path / "python.exe"
    real.write_text("", encoding="utf-8")
    monkeypatch.setenv("OPEN_STUDIO_TTS_BASE_PYTHON", str(real))

    assert interpreter.base_python() == str(real)


def test_candidate_interpreters_exclude_the_frozen_exe(frozen, monkeypatch) -> None:
    """探测「这个解释器装了 f5_tts 吗」会**执行**它 —— 拿冻结的 exe 探,等于再起一个后端。"""
    from app.ai.runtime import asr_models, tts_models

    for candidates in (tts_models.candidate_pythons("f5-tts"), asr_models.candidate_pythons("whisperx")):
        assert all(str(frozen) != str(path) for path in candidates), (
            f"候选解释器里有应用自己:{[str(p) for p in candidates]}"
        )


#: 允许直接读 `sys.executable` 的地方,以及原因。
ALLOWED_SYS_EXECUTABLE = {
    "app/core/interpreter.py": "它就是回答这个问题的那一处",
}


def test_only_one_place_decides_what_python_means() -> None:
    """新写一处 `sys.executable` 就会红 —— 打包版上它是应用自己,不是解释器。"""
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        rel = str(path)
        if rel in ALLOWED_SYS_EXECUTABLE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "executable"
                and isinstance(node.value, ast.Name)
                and node.value.id == "sys"
            ):
                offenders.append(f"{rel}:{node.lineno}")

    assert offenders == [], (
        "这些地方自己回答了「哪个是 Python」,而打包版上 sys.executable 是应用自己 —— "
        "拿它 -m venv 会把后端再启动一遍:\n  " + "\n  ".join(offenders)
    )


def _scripts_run_by_another_interpreter() -> set[str]:
    """哪些 .py 会被**另一个解释器当文件打开**。两条判据,缺一不可:

    1. `app/ai/runtime/workers/` 下的一切 —— 那个目录的存在意义就是这个(见它的说明);
    2. 任何 `Path(__file__).with_name("x.py")` —— 老写法,别处可能还有。

    只留第 2 条会**假绿**:worker 挪进 workers/ 之后不再用 with_name 定位(改成
    workers.tts_script()),于是这个函数一个都扫不到、`--add-data` 漏了也不会红。
    真机上那是"点了下载转半天,然后 can't open file"。假绿比红更危险 —— 它让人以为查过了。
    """
    wanted = {
        str(path) for path in sorted(pathlib.Path("app/ai/runtime/workers").glob("*.py"))
        if path.name != "__init__.py"
    }
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "with_name"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.endswith(".py")
            ):
                wanted.add(str(path.parent / node.args[0].value))
    return wanted


def test_every_worker_script_ships_as_a_real_file() -> None:
    """冻结之后源码只在归档里。被当脚本跑的那几个必须在打包命令里点名带上。

    用户看到的 `can't open file '…\\_internal\\app\\audio\\tts_worker.py'` 就是漏了这一步。

    盯的是 **package.json 里的 build:backend**,不是 .spec —— 那个文件是这条命令每次重新
    生成的产物(还在 .gitignore 里)。盯一份没人读的清单,等于没盯。
    """
    build = (pathlib.Path("..") / "package.json").read_text(encoding="utf-8")
    command = next(line for line in build.splitlines() if '"build:backend"' in line)

    missing = [
        script for script in sorted(_scripts_run_by_another_interpreter())
        if f"--add-data {script}:" not in command
    ]

    assert missing == [], (
        "这些脚本要被另一个解释器当文件打开,但打包时没带上 —— 装好的用户会拿到 "
        "'No such file or directory':\n  " + "\n  ".join(missing)
    )
