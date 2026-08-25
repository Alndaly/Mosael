"""Plugin runtime (plan §19.6): process-isolated tool execution.

Contract with the plugin's entry script:
- The manifest declares `entry` (a script path relative to the plugin dir).
- We spawn `<python> entry` with cwd = plugin dir and a minimal environment,
  write ONE JSON request to stdin and read ONE JSON response from stdout:

    stdin : {"tool": str, "input": {...}}
    stdout: {"ok": true, "output": {...}, "state": {...}} | {"ok": false, "error": str}

- 要交出一个**文件**(而不是一段 JSON)时,output 里放 `artifact`,写在
  OPEN_STUDIO_PLUGIN_OUTPUT_DIR 指的目录里,或者给一个后端去下的 url。见 artifacts。
- 要**记住**一点东西到下次调用(刷新出来的 access_token、同步游标)时,放 `state` ——
  它和 output 平级,**不进 output** 是有意的:output 会交给调用方和模型,而刷新出来的
  令牌不该出现在那里。见 state。

- The child gets a minimal environment: PATH/HOME/LANG plus **the credentials
  this plugin itself declared** in its manifest (see credentials.py). It never
  receives the app's own provider keys, database, or API token — plugins cannot
  bypass the permission system by design because they receive nothing but their
  input payload and their own declared secrets.
- Anything long-running or mutating goes through jobs and confirmation cards.
- Every call is recorded in plugin_invocations; a crashing or hanging plugin
  fails its invocation, never the app.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from app.core.interpreter import base_python
from app.core.child_process import run_logged
from app.core.text import blame_line
from app.domain.plugins.artifacts import SCRATCH_ENV as ARTIFACT_SCRATCH_ENV

PLUGIN_TIMEOUT_SECONDS = 60
MAX_OUTPUT_BYTES = 1_000_000


class PluginRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolResult:
    """一次调用的两样产出。

    分成两样而不是一个字典,是因为它们的去向不同:`output` 回给调用方(以及模型),
    `state` 只落库、谁都看不到。混在一起的话,一个刚刷新出来的 access_token 会顺着
    工具结果流进对话记录里。
    """

    output: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)


def resolve_entry(manifest: dict[str, Any]) -> Path:
    plugin_dir = Path(str(manifest.get("_path") or ""))
    entry = str(manifest.get("entry") or "").strip()
    if not entry:
        raise PluginRuntimeError("插件未声明 entry 脚本,无法执行(manifest.entry)")
    if not plugin_dir.is_dir():
        raise PluginRuntimeError("插件目录不存在,请重新扫描")
    entry_path = (plugin_dir / entry).resolve()
    if not str(entry_path).startswith(str(plugin_dir.resolve()) + os.sep):
        raise PluginRuntimeError("entry 脚本必须位于插件目录内")
    if not entry_path.is_file():
        raise PluginRuntimeError(f"entry 脚本不存在: {entry}")
    return entry_path


def check_required_input(tool: dict[str, Any], input_payload: dict[str, Any]) -> None:
    schema = tool.get("input_schema") or {}
    required = schema.get("required") if isinstance(schema, dict) else None
    if not isinstance(required, list):
        return
    missing = [key for key in required if isinstance(key, str) and key not in input_payload]
    if missing:
        raise PluginRuntimeError(f"缺少必填输入: {', '.join(missing)}")


def execute_tool(
    manifest: dict[str, Any],
    tool_name: str,
    input_payload: dict[str, Any],
    credentials: dict[str, str] | None = None,
    scratch_dir: Path | None = None,
) -> ToolResult:
    """Run the plugin entry once. Returns the tool output dict; raises
    PluginRuntimeError with an actionable message on any failure.

    `credentials` are this plugin's own declared keys, injected as environment
    variables — never the app's.

    `scratch_dir` 是这次调用的产出目录:插件要交出一个文件时写在那儿,路径经
    OPEN_STUDIO_PLUGIN_OUTPUT_DIR 告诉它(见 artifacts 的说明)。协议本身只搬 JSON,
    所以搬字节这件事得另开一条路。"""
    entry_path = resolve_entry(manifest)
    request = json.dumps({"tool": tool_name, "input": input_payload}, ensure_ascii=False)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "OPEN_STUDIO_PLUGIN": "1",
        **({ARTIFACT_SCRATCH_ENV: str(scratch_dir)} if scratch_dir is not None else {}),
        **(credentials or {}),
    }
    started = time.monotonic()
    try:
        # 打包版里 sys.executable 是应用自己 —— 拿它跑插件等于再起一个后端(见 core/interpreter)。
        python = base_python()
        if not python:
            raise PluginRuntimeError("找不到可用于运行插件的 Python 解释器")
        result = run_logged(
            [python, str(entry_path)],
            input=request,
            capture_output=True,
            text=True,
            timeout=PLUGIN_TIMEOUT_SECONDS,
            cwd=entry_path.parent,
            env=env, what="插件命令")
    except subprocess.TimeoutExpired as exc:
        raise PluginRuntimeError(f"插件执行超时({PLUGIN_TIMEOUT_SECONDS}s)") from exc
    duration_ms = int((time.monotonic() - started) * 1000)

    if result.returncode != 0:
        # 取尾巴会撞上进度条 / 收尾提示 —— 判据收在 core/text.blame_line 一处(那里记着它踩过几次)。
        why = blame_line(result.stderr or result.stdout, fallback="插件没有留下原因")
        raise PluginRuntimeError(f"插件进程退出码 {result.returncode}:{why}")
    stdout = result.stdout.strip()
    if len(stdout) > MAX_OUTPUT_BYTES:
        raise PluginRuntimeError("插件输出超过大小限制 (1MB)")
    try:
        response = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PluginRuntimeError(f"插件输出不是合法 JSON: {stdout[-300:]}") from exc
    if not isinstance(response, dict):
        raise PluginRuntimeError("插件输出必须是 JSON 对象")
    if not response.get("ok"):
        raise PluginRuntimeError(str(response.get("error") or "插件返回失败但未说明原因"))
    output = response.get("output")
    if not isinstance(output, dict):
        raise PluginRuntimeError("插件成功响应必须包含 output 对象")
    output["_duration_ms"] = duration_ms
    state = response.get("state")
    if state is not None and not isinstance(state, dict):
        raise PluginRuntimeError("插件返回的 state 必须是对象")
    return ToolResult(output=output, state=dict(state or {}))


__all__ = ["PluginRuntimeError", "ToolResult", "execute_tool", "check_required_input", "resolve_entry", "PLUGIN_TIMEOUT_SECONDS"]
