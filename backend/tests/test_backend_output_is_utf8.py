"""后端写出去的日志一律是 UTF-8,不跟系统的区域编码走(core/logging.write_stdio_as_utf8)。

桌面壳把后端输出接进 backend.log,启动小窗读它的最后一句。输出是文件时 Python 按区域编码写 —— 中文 Windows 上是
GBK,小窗按 UTF-8 读,状态就成了乱码(维护者:「应用打开后的那个 loading 窗口状态存在乱码」)。

这里用 `PYTHONIOENCODING=gbk` 在任何平台上重现「区域编码是 GBK、输出是文件」;先证明不处理时写出的确实是 GBK,
再证明处理之后是 UTF-8 —— 只断言后者的话,换到一台 UTF-8 的机器上它天然就绿。
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import run_backend

BACKEND = pathlib.Path(__file__).resolve().parents[1]
LINE = "正在迁移数据库 · 插件已就绪"


def _child_output(tmp_path: pathlib.Path, *, fix: bool) -> tuple[bytes, bytes]:
    prelude = "from app.core.logging import write_stdio_as_utf8; write_stdio_as_utf8(); " if fix else ""
    code = f"import sys; {prelude}print({LINE!r}); print({LINE!r}, file=sys.stderr)"
    out, err = tmp_path / "out.log", tmp_path / "err.log"
    with out.open("wb") as stdout, err.open("wb") as stderr:
        subprocess.run([sys.executable, "-c", code], cwd=BACKEND, stdout=stdout, stderr=stderr, check=True,
                       env={**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"})
    return out.read_bytes(), err.read_bytes()


def test_区域编码是GBK时_不处理写出的是GBK_处理之后是UTF8(tmp_path: pathlib.Path) -> None:
    raw_out, raw_err = _child_output(tmp_path, fix=False)
    assert raw_out.strip() == LINE.encode("gbk") and raw_err.strip() == LINE.encode("gbk"), "模拟没生效,下面那条证明不了什么"

    out, err = _child_output(tmp_path, fix=True)
    assert out.decode("utf-8").strip() == LINE
    assert err.decode("utf-8").strip() == LINE


def test_打包入口第一件事就是把输出改成UTF8(monkeypatch) -> None:
    """管理命令和服务都从 run_backend.main 进来:改编码要排在它们之前,否则先写出的那几行还是旧编码。"""
    calls: list[str] = []
    monkeypatch.setattr("app.core.logging.write_stdio_as_utf8", lambda: calls.append("utf8"))
    monkeypatch.setattr("app.cli.main", lambda argv: calls.append("cli") or 0)
    monkeypatch.setattr(sys, "argv", ["mosael-backend", "reset-password", "somebody"])
    try:
        run_backend.main()
    except SystemExit:
        pass
    assert calls == ["utf8", "cli"]
