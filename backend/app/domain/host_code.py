"""在**这台电脑上、不隔离地**跑一段 Python —— `run_code` 的另一半。

沙箱(`domain/sandbox`)是默认:无网、只读、看不到本机文件,适合算东西。但有些事的全部意义
就是动本机 —— 整理下载目录、调一个本机命令行工具、读用户指给你的某个文件。在沙箱里做这些
只会得到"找不到文件",于是这里提供明确的另一条路,而**不是**让沙箱在不可用时退回到这里
(那正是 sandbox 模块开头记着的、被移除的旧状态)。两条路是两个工具、两张不同措辞的卡、
两档独立的放行准则:用户对「算个数」点过「始终允许」,不该连带放行「动我的文件」。

边界:
- **只在本机桌面后端**(`settings.local_desktop`)。远程部署上"这台电脑"是服务器,不是用户的。
- 进程以后端的身份运行,能读写后端能读写的一切。所以不继承后端里的凭据类环境变量 ——
  代码要动的是用户的文件,不是我们手里的供应商密钥。
- 用户代码的 print 不会搅乱结果通道:包装器把它收进 `printed` 一并交回。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.core.i18n import LocalizedError, tr
from app.core.child_process import ProcessOutputLimitExceeded, run_bounded
from app.core.config import settings
from app.core.interpreter import base_python
from app.core.text import blame_line

TIMEOUT_SECONDS = 120.0
OUTPUT_CAP = 1024 * 1024

_WRAPPER = """\
import contextlib, io, json, sys
payload = json.load(sys.stdin)
scope = {"inputs": payload.get("inputs") or {}}
printed = io.StringIO()
with contextlib.redirect_stdout(printed):
    exec(compile(payload["code"], "<agent>", "exec"), scope)
sys.stdout.write(json.dumps({"output": scope.get("output"), "printed": printed.getvalue()[-20000:]},
                            ensure_ascii=False, default=str))
"""

#: 名字像凭据的环境变量不交给子进程。宁可多挡一个,子进程要用的话用户会在代码里自己写。
_SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIAL)", re.I)


class HostCodeError(LocalizedError, RuntimeError):
    """代码出错、超时、输出超限,或者这里根本不是用户自己的电脑。带文案 key(`hostCodeErr_*`)。"""


def _unavailable_key() -> str | None:
    if not settings.local_desktop:
        return "hostCodeErr_localOnly"
    if not base_python():
        return "hostCodeErr_noPython"
    return None


def available() -> str | None:
    """能跑就返回 None,不能跑返回一句说给人听的原因(按当时的语言)。开卡前就问,别让人批准一张注定失败的卡。"""
    key = _unavailable_key()
    return tr(key) if key else None


def child_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if not key.startswith("MOSAEL_") and not _SECRET_NAME.search(key)}


def run(code: str, inputs: dict[str, Any], *, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    reason = _unavailable_key()
    if reason:
        raise HostCodeError(reason)
    payload = json.dumps({"code": code, "inputs": inputs}, ensure_ascii=False).encode()
    try:
        completed = run_bounded([base_python(), "-c", _WRAPPER], input=payload, timeout=timeout,
                                max_output_bytes=OUTPUT_CAP, env=child_env(), what="本机执行代码",
                                cwd=str(Path.home()))
    except subprocess.TimeoutExpired as exc:
        raise HostCodeError("hostCodeErr_timeout", seconds=f"{timeout:g}") from exc
    except ProcessOutputLimitExceeded as exc:
        raise HostCodeError("hostCodeErr_outputTooLarge", limit=OUTPUT_CAP // 1024) from exc
    if completed.returncode != 0:
        why = blame_line(completed.stderr.decode(errors="replace"), fallback="")
        if not why:
            raise HostCodeError("hostCodeErr_failedNoReason")
        raise HostCodeError("hostCodeErr_failed", detail=why)
    try:
        result = json.loads(completed.stdout.decode())
    except ValueError as exc:
        raise HostCodeError("hostCodeErr_badOutput") from exc
    return {"output": result.get("output"), "printed": result.get("printed") or ""}
