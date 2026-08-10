"""每一个外部命令都要在日志里留下痕迹:跑的是什么、跑了多久、退出码、失败时它说了什么。

这一整轮 bug 都卡在同一件事上:**外部命令是黑箱**。

- 转写报「Output file does not contain any stream」—— 那是 ffmpeg 的原话,而日志里既没有
  这条命令、也没有它的 stderr,只能靠把错误文本原样端到界面上才看见。
- 声音克隆发占位音 —— worker 子进程返回 0、宿主报成功,日志里一个字都没有。
- 装引擎「0 MB / 1.5 GB」不动 —— pip 在跑,跑了多久、装到哪了,日志里没有。

这些命令有 35 个调用点,散在音频、媒体、插件、沙箱里。**在 35 个地方各写一遍 log** 就是
这个仓库反复吃亏的那种做法:写第一遍时全都对,半年后各自漂移。所以只有一处 `run_logged`,
它同时负责跑和记。

判据不是"日志越多越好":成功的命令记一行 INFO(命令 + 耗时),失败的记 WARNING 并带上
stderr 尾巴 —— 因为失败时唯一有用的东西就是子进程自己说的那句话。
"""

from __future__ import annotations

import logging

import pytest

from app.core.child_process import run_logged


def test_a_successful_command_records_what_and_how_long(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.core.child_process"):
        result = run_logged(["/bin/echo", "hi"], what="回声", capture_output=True, text=True)

    assert result.returncode == 0
    line = "\n".join(record.getMessage() for record in caplog.records)
    assert "回声" in line
    assert "echo" in line
    assert "ms" in line or "s" in line, f"没记耗时:{line}"


def test_a_failing_command_records_what_it_said(caplog) -> None:
    """失败时唯一有用的东西,是子进程自己说的那句话。"""
    with caplog.at_level(logging.INFO, logger="app.core.child_process"):
        result = run_logged(
            ["/bin/sh", "-c", "echo 这条命令炸了 >&2; exit 3"],
            what="会炸的",
            capture_output=True,
            text=True,
        )

    assert result.returncode == 3
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "失败了却只有 INFO"
    message = warnings[-1].getMessage()
    assert "这条命令炸了" in message, f"没带上 stderr:{message}"
    assert "3" in message, f"没带上退出码:{message}"


def test_secrets_in_the_argv_do_not_reach_the_log(caplog) -> None:
    """日志会进日志文件、会被贴进 issue。参数里的密钥不能原样躺在那儿。

    真实形状:pip 的 `--index-url https://user:token@mirror/simple`,以及各家 CLI 的
    `--api-key sk-…`。
    """
    with caplog.at_level(logging.INFO, logger="app.core.child_process"):
        run_logged(
            ["/bin/echo", "--index-url", "https://u:s3cr3t@mirror.example/simple", "--api-key", "sk-abcdef123456"],
            what="带密钥的",
            capture_output=True,
            text=True,
        )

    line = "\n".join(record.getMessage() for record in caplog.records)
    assert "s3cr3t" not in line, f"密码进了日志:{line}"
    assert "sk-abcdef123456" not in line, f"密钥进了日志:{line}"


def test_a_timeout_is_recorded_not_just_raised(caplog) -> None:
    """超时也是一种结果 —— 它比失败更容易被当成"卡住了"。"""
    with caplog.at_level(logging.INFO, logger="app.core.child_process"):
        with pytest.raises(Exception):
            run_logged(["/bin/sleep", "5"], what="睡太久的", timeout=0.2, capture_output=True)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("超时" in r.getMessage() or "timeout" in r.getMessage().lower() for r in warnings), (
        f"超时没留下痕迹:{[r.getMessage() for r in caplog.records]}"
    )


def test_it_is_a_drop_in_for_subprocess_run() -> None:
    """它必须能原样替掉 `subprocess.run` —— 否则 35 个调用点没人愿意换。"""
    result = run_logged(["/bin/echo", "x"], what="t", capture_output=True, text=True)
    assert result.stdout.strip() == "x"
    assert hasattr(result, "returncode") and hasattr(result, "stderr")
