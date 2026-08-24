"""合成失败时,界面上要出现**一句话**,不是一屏 traceback。

用户截图里那张卡片长这样:

    语音合成失败:
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ^^^^^^^^^^^^^^^^^^^^^^ File "/Users/kinda/.open-studio/tts/fish-speech-src/
    fish_speech/utils/__init__.py", line 3, in <module> from .file import
    get_latest_checkpoint File ".../file.py", line 6, in <module>
    from natsort import natsorted
    ModuleNotFoundError: No module named 'natsort'

有用的信息只有最后一行,而它被埋在四行文件路径和一排插入符后面 —— 那排 `^^^^` 是终端里
指向出错列的记号,在浏览器里换了行,变成一片噪声。

判据和下载失败那条一样(`tts_models._explain_failure`):**取子进程说的最后一句**。
traceback 的最后一行就是异常本身,前面那些是给读代码的人看的,不是给点了「生成配音」的人看的。
完整的 traceback 仍然进日志 —— 排查要它,界面不要。
"""

from __future__ import annotations

from app.domain.voices import voices

RAW = '''Traceback (most recent call last):
  File "/x/tts_worker.py", line 152, in run_fish
    from tools.server.inference import inference_wrapper
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/kinda/.open-studio/tts/fish-speech-src/fish_speech/utils/__init__.py", line 3, in <module>
    from .file import get_latest_checkpoint
  File "/Users/kinda/.open-studio/tts/fish-speech-src/fish_speech/utils/file.py", line 6, in <module>
    from natsort import natsorted
ModuleNotFoundError: No module named 'natsort'
'''


def test_only_the_last_line_reaches_the_card() -> None:
    message = voices.explain_worker_failure(RAW)

    assert "natsort" in message
    assert "^^^" not in message, f"插入符进了界面:{message}"
    assert "Traceback" not in message, message
    assert message.count("\n") == 0, f"界面上那句话不该换行:{message!r}"


def test_a_missing_module_says_what_to_do() -> None:
    """缺依赖是**能行动**的:去哪补。光扔一个模块名,用户只能去搜。"""
    message = voices.explain_worker_failure(RAW)

    assert "下载" in message or "运行环境" in message, message


def test_an_ordinary_failure_is_passed_through() -> None:
    message = voices.explain_worker_failure("RuntimeError: CUDA out of memory\n")

    assert "CUDA out of memory" in message


def test_empty_stderr_does_not_produce_an_empty_card() -> None:
    assert voices.explain_worker_failure("   \n  ").strip() != ""


def test_the_failure_path_itself_does_not_crash() -> None:
    """**错误路径上的错误**是这一轮反复出现的形状。

    我给这条路加日志时写了 `logger.warning(...)`,而 voices.py 里当时没有 `logger` ——
    模块照样 import 得动(名字只在运行时才求值),于是一个只在"合成失败"时才触发的
    NameError 会把真正的失败原因盖掉。KB 那个 `_schedule_enhanced_index` 是同一个形状:
    自由变量藏在 except 里,整条增强索引一次都没跑过,而没人看得出来。
    """
    import ast
    import pathlib

    for path in (pathlib.Path("app/domain/voices/voices.py"), pathlib.Path("app/ai/runtime/tts_models.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Name) and n.id == "logger" for n in ast.walk(tree)):
            assert any(
                isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "logger" for t in n.targets)
                for n in tree.body
            ), f"{path} 用了 logger 却没定义 —— 只在失败时才炸的那种"
