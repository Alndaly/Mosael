"""在本机运行**结构化命令**(不经 shell),用于 git、ffmpeg、语言工具链这类本地操作。

边界和 `host_code` 不同:
- 不拼接字符串、不经过 shell,参数逐个传;
- 只允许一组开发工具的可执行名;
- 工作目录必须由调用方过 `host_files` 的信任目录闸;
- 仍只在本机桌面、只有部署管理员能批准,且走确认卡。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.child_process import ProcessOutputLimitExceeded, run_bounded
from app.core.config import settings
from app.core.i18n import LocalizedError
from app.domain.host_code import child_env

TIMEOUT_SECONDS = 120.0
OUTPUT_CAP = 1024 * 1024
ARG_COUNT_CAP = 64
ARG_CHARS_CAP = 4096

#: 只允许开发/媒体工具,不允许 `rm`、`mv`、`cp` 这类已经由文件工具负责的破坏性操作。
ALLOWED_COMMANDS = frozenset({
    "git", "python", "python3", "node", "pnpm", "npm", "npx",
    "ffmpeg", "ffprobe", "rg", "ls", "pwd", "cat", "head", "tail", "wc", "mkdir",
})


class HostCommandError(LocalizedError, ValueError):
    """命令本身不合法(不在白名单、参数太多、超时、输出超限)。"""


def validate(command: str, args: list[str] | None, timeout: float) -> list[str]:
    name = str(command or "").strip()
    if name not in ALLOWED_COMMANDS or "/" in name or "\\" in name:
        raise HostCommandError("hostCmdErr_notAllowed", command=name)
    cleaned = [str(item) for item in (args or [])]
    if len(cleaned) > ARG_COUNT_CAP or any(len(item) > ARG_CHARS_CAP for item in cleaned):
        raise HostCommandError("hostCmdErr_argsTooLarge", limit=ARG_COUNT_CAP)
    if not 1 <= timeout <= TIMEOUT_SECONDS:
        raise HostCommandError("hostCmdErr_timeoutRange", max=f"{TIMEOUT_SECONDS:g}")
    return cleaned


def run(command: str, args: list[str] | None, *, cwd: Path, timeout: float = 60.0) -> dict[str, Any]:
    if not settings.local_desktop:
        raise HostCommandError("hostCodeErr_localOnly")
    cleaned = validate(command, args, timeout)
    executable = shutil.which(command)
    if not executable:
        raise HostCommandError("hostCmdErr_missing", command=command)
    try:
        completed = run_bounded(
            [executable, *cleaned], timeout=timeout, max_output_bytes=OUTPUT_CAP,
            env=child_env(), cwd=str(cwd), what=f"本机命令 {command}",
        )
    except subprocess.TimeoutExpired as exc:
        raise HostCommandError("hostCodeErr_timeout", seconds=f"{timeout:g}") from exc
    except ProcessOutputLimitExceeded as exc:
        raise HostCommandError("hostCodeErr_outputTooLarge", limit=OUTPUT_CAP // 1024) from exc
    return {
        "command": [command, *cleaned],
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.decode(errors="replace"),
        "stderr": completed.stderr.decode(errors="replace"),
    }
