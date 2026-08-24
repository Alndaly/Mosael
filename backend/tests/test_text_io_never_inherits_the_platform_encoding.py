"""文本 I/O 必须**自己说清用什么编码**,不能问平台要。

用户在 Windows 上和智能体说话,拿到的是:

    'gbk' codec can't decode byte 0x88 in position 52: illegal multibyte sequence

Python 的 `text=True` 在不给 `encoding` 时用**平台默认编码**:mac/Linux 上是 UTF-8,中文
Windows 上是 GBK。sidecar 是 Node,按 UTF-8 写 JSON;父进程按 GBK 读,于是第一句带中文的
回复就把整轮对话炸掉。反方向同理 —— 用户的中文 prompt 写进它的 stdin 时,GBK 编不出去的
字符会当场抛 `can't encode character`。

**这不是三个调用点的事,是一整类**:仓库里二十来处 `text=True` 一个都没写 encoding,只是
其它几处平时不过中文而已(ffprobe 的文件名、pip 的日志、渲染器的进度 —— 换个中文路径就轮到
它们)。所以判据是"这类事只有一处实现",不是"把 adapters.py 修一下"。

这台机器上复现同一条报错(把 GBK 显式写出来即可):

    UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 36
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib
import sys

from app.core.child_process import TEXT_IO, popen_text

#: 允许直接 Popen 的地方,以及原因。和 test_subprocess_has_one_door 是同一条纪律。
ALLOWED_POPEN = {
    "app/core/child_process.py": "它就是那个口子本身",
}


def test_the_door_pins_utf8() -> None:
    """口子本身必须定死编码 —— 它要是也问平台要,下面所有测试都白做。"""
    assert TEXT_IO["encoding"] == "utf-8"


def test_a_child_speaking_chinese_round_trips() -> None:
    """按用户实际走的路验:子进程按 UTF-8 吐中文,我们读回来还是那句话。"""
    said = "这是一段中文的智能体回复,足够长以便越过第 52 个字节。"
    code = f"import sys;sys.stdout.buffer.write({said!r}.encode('utf-8')+b'\\n')"

    process = popen_text([sys.executable, "-c", code], stdout=-1)
    line = process.stdout.readline()
    process.wait()

    assert process.stdout.encoding.lower().replace("-", "") == "utf8", (
        f"读子进程用的是 {process.stdout.encoding} —— 中文 Windows 上这里会是 GBK"
    )
    assert line.strip() == said


def test_popen_only_happens_behind_the_door() -> None:
    """新写一处裸 Popen 就会红 —— 它会继承平台编码,而这正是 Windows 上炸掉的那条路。"""
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        rel = str(path)
        if rel in ALLOWED_POPEN:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "Popen"
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                offenders.append(f"{rel}:{node.lineno}")

    assert offenders == [], (
        "这些地方绕开 popen_text 直接起子进程,于是按平台默认编码收发 —— "
        "中文 Windows 上是 GBK,一遇到中文就炸:\n  " + "\n  ".join(offenders)
    )


def test_raw_text_mode_always_names_its_encoding() -> None:
    """就算走了 subprocess 自己的 API,文本模式也得把编码写出来。"""
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            raw = (
                isinstance(func, ast.Attribute)
                and func.attr in {"Popen", "run", "check_output"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            )
            if not raw:
                continue
            asks_for_text = any(
                kw.arg in {"text", "universal_newlines"}
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            )
            names = {kw.arg for kw in node.keywords}
            if asks_for_text and "encoding" not in names and None not in names:
                offenders.append(f"{path}:{node.lineno}")

    assert offenders == [], "文本模式没写 encoding:\n  " + "\n  ".join(offenders)


def test_text_files_declare_their_encoding_too() -> None:
    """`Path.read_text()` / `write_text()` 同理:不给 encoding 就是问平台要。"""
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"read_text", "write_text"}:
                continue
            if "encoding" not in {kw.arg for kw in node.keywords}:
                offenders.append(f"{path}:{node.lineno} {node.func.attr}")

    assert offenders == [], (
        "这些文本文件读写没写 encoding —— 换台机器就换一种编码:\n  " + "\n  ".join(offenders)
    )
