"""装引擎依赖失败时,说出来的必须是**原因**,不是输出的最后一行。

真机上这两条报错就是这么丢掉的(Windows,0.18.0):

- 声音克隆:`安装 f5-tts 运行依赖失败:note: run with 'RUST_BACKTRACE=1' ...`
- 转写:一段 zipfile 的 traceback 尾巴

两处当时都是 `(stderr or stdout)[-300:]`。pip 的输出以收尾提示结束是常态,于是**按位置裁**
必然裁到没信息的那一头 —— 和 `audio/voices.explain_worker_failure` 里把
`[end of libtorchcodec loading traceback]` 当成错误原因,是同一个毛病的第二次发作。

所以这里钉的不是"有没有报错",而是「挑出来的那几行**是不是**说明原因的那几行」。
每条用例都配一句"按老办法(取尾巴)会得到什么" —— 不然这个测试自己就是空的。
"""
from __future__ import annotations

import pytest

from app.core.pip_install import explain, verdict_lines

#: 真机上那次 Rust 编译失败的形状:结论在中间,尾巴是一句纯提示。
RUST_OUTPUT = """\
Collecting f5-tts
  Downloading f5_tts-1.1.7.tar.gz (98 kB)
  Installing build dependencies: started
Building wheels for collected packages: pyopenjtalk
  Building wheel for pyopenjtalk (pyproject.toml): started
  error: could not compile `tokenizers` (lib) due to 1 previous error
  ERROR: Failed building wheel for pyopenjtalk
ERROR: Could not build wheels for pyopenjtalk, which is required to install pyproject.toml-based projects
note: This error originates from a subprocess, and is likely not a problem with pip.
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
"""

#: 真机上那次转写安装失败的形状:pip 自己崩了,没有 ERROR: 行,只有 traceback 收尾那句。
MEMORY_OUTPUT = """\
Collecting funasr
Collecting torch
  Downloading torch-2.9.0-cp312-cp312-win_amd64.whl (241.6 MB)
Installing collected packages: torch
Traceback (most recent call last):
  File "C:\\Users\\k\\AppData\\Local\\Programs\\Open Studio\\resources\\python\\Lib\\zipfile\\__init__.py", line 1118, in read
    buf += self._read1(self.MAX_N)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\\Users\\k\\AppData\\Local\\Programs\\Open Studio\\resources\\python\\Lib\\zipfile\\__init__.py", line 1068, in _read1
    data = self._decompressor.decompress(data, n)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
MemoryError: Unable to allocate output buffer.
"""


def test_rust_failure_names_the_package_not_the_closing_note() -> None:
    lines = verdict_lines(RUST_OUTPUT)
    joined = " ".join(lines)
    assert "Could not build wheels for pyopenjtalk" in joined
    # 老办法会得到这一句 —— 它必须**不是**我们端出去的结论。
    assert not any("RUST_BACKTRACE" in line for line in lines)
    assert not any(line.lower().startswith("note:") for line in lines)


def test_memory_failure_names_the_error_not_the_caret_line() -> None:
    lines = verdict_lines(MEMORY_OUTPUT)
    assert lines, "pip 自己崩掉时没有 ERROR: 行,但 traceback 收尾那句说得出发生了什么"
    assert "MemoryError: Unable to allocate output buffer." in lines[0]
    # `^^^^` 那行正好是老办法会截到的位置。
    assert not any("^^^" in line for line in lines)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (MEMORY_OUTPUT, "内存不足"),
        (RUST_OUTPUT, "Rust"),
        ("ERROR: Could not install packages...\nOSError: [Errno 28] No space left on device", "磁盘空间不足"),
        ("ERROR: No matching distribution found for torch==9.9.9", "找不到能装的版本"),
        ("ERROR: Exception:\nTimeoutError: Read timed out. (read timeout=15)", "pip 镜像"),
    ],
)
def test_known_causes_get_a_next_step(output: str, expected: str) -> None:
    """认得出的病因要给出**能照做的下一句**,而不只是把英文原样端出去。"""
    assert expected in explain(output)


def test_unknown_failure_admits_it_rather_than_pretending() -> None:
    """认不出来时不能编一个原因 —— 说不知道,并把原文附上。"""
    message = explain("something went sideways in a way nobody anticipated")
    assert "pip 没有说明原因" in message
    assert "sideways" in message


def test_no_output_at_all_is_said_plainly() -> None:
    assert "没有任何输出" in explain("")


def test_the_log_path_is_handed_over() -> None:
    """完整输出落了盘就得说在哪 —— 否则下一次还是只能请用户录屏。"""
    from pathlib import Path

    message = explain(RUST_OUTPUT, log_path=Path("/tmp/pip-x.log"))
    assert "/tmp/pip-x.log" in message


def test_a_verdict_line_is_not_swallowed_by_the_noise_filter() -> None:
    """噪声过滤只该滤掉纯提示行。把结论一起滤掉,就又回到了"报了个寂寞"。"""
    assert verdict_lines("ERROR: Failed building wheel for x\nnote: hi") == [
        "ERROR: Failed building wheel for x"
    ]


# ---------------------------------------------------------------------------
# 装依赖这件事本身:参数是不是对的,以及两个引擎走的是不是同一条路
# ---------------------------------------------------------------------------
def test_install_prefers_prebuilt_but_does_not_forbid_source(monkeypatch, tmp_path) -> None:
    """`--prefer-binary` 要在,`--only-binary` 不能在。

    前者挡的是「为了版本号新一点去本机编译 Rust」—— Windows 上 f5-tts 装不上正是这么来的
    (rjieba 每版都发源码包,而 win + py3.12 的轮子不是每版都有)。
    后者会把 `transformers_stream_generator` 这种**只有源码包**的依赖一并挡死,
    于是 f5-tts 彻底装不上。要挡的是"为了新版本去编译",不是"编译"本身。
    """
    from app.core import pip_install, run_log

    seen: list[list[str]] = []

    def fake_run(args, **kwargs):
        seen.append([str(a) for a in args])
        return __import__("subprocess").CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(pip_install, "run_logged", fake_run)
    monkeypatch.setattr(run_log.settings, "data_dir", tmp_path)  # 落盘搬去了 core/run_log
    pip_install.install("py", ["f5-tts"], what="装", index_url="https://mirror.example/simple")

    install_call = seen[-1]
    assert "--prefer-binary" in install_call
    assert not any(arg.startswith("--only-binary") for arg in install_call)
    # 镜像要真的传下去 —— 转写那边此前就是漏了这一项,而设置页写着它管"引擎依赖"。
    assert install_call[install_call.index("--index-url") + 1] == "https://mirror.example/simple"


def test_a_failed_install_keeps_the_whole_output_on_disk(monkeypatch, tmp_path) -> None:
    """失败时完整输出必须落盘。此前它哪儿都没有 —— 连日志里也只留 800 字符,
    于是真机上的报错除了让用户重跑一遍并录屏之外无法诊断。"""
    import subprocess

    from app.core import pip_install, run_log

    monkeypatch.setattr(
        pip_install, "run_logged",
        lambda args, **kw: subprocess.CompletedProcess(args, 1, "", RUST_OUTPUT),
    )
    monkeypatch.setattr(run_log.settings, "data_dir", tmp_path)  # 落盘搬去了 core/run_log
    with pytest.raises(pip_install.PipInstallError) as excinfo:
        pip_install.install("py", ["f5-tts"], what="装克隆依赖")

    logs = list((tmp_path / "logs").glob("pip-*.log"))
    assert len(logs) == 1
    body = logs[0].read_text(encoding="utf-8")
    assert "RUST_BACKTRACE" in body and "Could not build wheels" in body
    assert str(logs[0]) in str(excinfo.value), "错误信息要指出日志在哪,否则落盘等于没落"


def test_both_engines_install_through_the_same_door() -> None:
    """克隆和转写不能各自裸调 pip。

    抄一遍就会产生差异 —— 上一版的差异是「克隆带 pip 镜像、转写不带」,而设置项写的是
    「装引擎依赖时用的 pip 索引」。同理适用于 `--prefer-binary`、超时重试、日志落盘:
    每多一个调用点,就多一处会漏掉它们的地方。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "pip_install.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"pip", "install"' in text or "'pip', 'install'" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"这些地方绕开了 core/pip_install:{offenders}"
