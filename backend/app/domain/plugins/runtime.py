"""Plugin runtime (plan §19.6): process-isolated tool execution.

Contract with the plugin's entry script:
- The manifest declares `entry` (a script path relative to the plugin dir).
- We spawn `<python> entry` with cwd = plugin dir and a minimal environment,
  write ONE JSON request to stdin and read ONE JSON response from stdout:

    stdin : {"tool": str, "input": {...}}
    stdout: {"ok": true, "output": {...}, "state": {...}} | {"ok": false, "error": str}

- 要交出一个**文件**(而不是一段 JSON)时,output 里放 `artifact`,写在
  MOSAEL_PLUGIN_OUTPUT_DIR 指的目录里,或者给一个后端去下的 url。见 artifacts。
- 要**记住**一点东西到下次调用(刷新出来的 access_token、同步游标)时,放 `state` ——
  它和 output 平级,**不进 output** 是有意的:output 会交给调用方和模型,而刷新出来的
  令牌不该出现在那里。见 state。

- The child gets a minimal environment: PATH/HOME/LANG (on Windows also the system variables a
  process cannot start without — see WINDOWS_ESSENTIALS) plus **the credentials
  this plugin itself declared** in its manifest (see credentials.py). It never
  receives the app's own provider keys, database, or API token — plugins cannot
  bypass the permission system by design because they receive nothing but their
  input payload and their own declared secrets.
- Anything long-running or mutating goes through jobs and confirmation cards.
- Every call is recorded in plugin_invocations; a crashing or hanging plugin
  fails its invocation, never the app.
- Called inside a job (a workflow node, anything run by dispatch_job), the process is
  registered as that job's child: cancelling the job kills it. See execute_tool.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from app.core.interpreter import base_python
from app.core.child_process import ChildProcess, popen_text, run_logged
from app.core.text import blame_line
from app.core.i18n import LocalizedError, get_current_locale
from app.domain.jobs import current_parent_job_id, detach_job_child, register_job_child
from app.domain.plugins.artifacts import SCRATCH_ENV as ARTIFACT_SCRATCH_ENV
from app.domain.plugins.manifest import LOCALE_ENV

logger = logging.getLogger(__name__)

#: 一次插件工具调用的**默认**预算。对标的是「一个插件工具该跑多久」。
#:
#: **借道这条运行时的产品功能不该继承它。** Blender 互通就是借道的:它在这 60 秒里要装下
#: `uvx` 冷启动 + MCP 握手 + 逐帧写关键帧 + 导出 glb —— 大一点的场景必然超时,而用户看到的
#: 是一句「Blender 未响应,请检查 Add-on 连接」,排查方向直接被指向 Add-on。所以预算是
#: 调用方可以给的**参数**,不是这条通道写死的常量(见 blender/bridge.BLENDER_TIMEOUT_SECONDS)。
PLUGIN_TIMEOUT_SECONDS = 60

#: 插件自己的**持久**目录,经这个环境变量告诉它。
#:
#: 插件目录本身不能当存储用:更新插件就是把整个目录换掉(registry.install_archive)。而有的插件
#: 要攒一份很贵的东西 —— Remotion 插件装的 node_modules 和渲染用的浏览器有几百 MB,每次更新
#: 都重装一遍是不可接受的。它和 MOSAEL_PLUGIN_OUTPUT_DIR 正相反:那个是这一次调用的、用完就删。
DATA_ENV = "MOSAEL_PLUGIN_DATA_DIR"


#: Windows 上**没有它们子进程就起不来**的那几个。Python 初始化要 SYSTEMROOT(否则连随机数都拿
#: 不到),Node 要它做 DNS,npm 要 APPDATA / LOCALAPPDATA 放缓存,TEMP 是一切临时文件的去处。
#: 都是系统路径,不是凭据 —— 「最小环境」挡的是应用的密钥,不是操作系统本身。
WINDOWS_ESSENTIALS = (
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
)


def base_env() -> dict[str, str]:
    """插件子进程的基础环境:PATH / HOME / LANG,Windows 上再加 WINDOWS_ESSENTIALS。

    此前只有前三个。在 Windows 上这等于起不来任何进程插件 —— 只是一直没人在 Windows 上跑过。
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    if sys.platform == "win32":
        upper = {key.upper(): value for key, value in os.environ.items()}
        env.update({key: upper[key] for key in WINDOWS_ESSENTIALS if key in upper})
    return env


def data_dir_for(package_id: str) -> Path:
    """一个插件的持久目录(不保证存在)。卸载时随包一起删(见 packages.uninstall)。"""
    from app.core.config import settings

    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in package_id).strip(".") or "plugin"
    return settings.data_dir / "plugin-data" / safe
MAX_OUTPUT_BYTES = 1_000_000


class PluginRuntimeError(LocalizedError, RuntimeError):
    """插件进程没跑成。带文案 key(`pluginErr_*`);插件自己报的原因走 `pluginErr_upstream`。"""


class PluginCancelled(PluginRuntimeError):
    """调用方(用户)取消了这次调用。不是插件坏了 —— 调用方据此把任务记成「已取消」而不是「失败」。"""


class PluginTimeout(PluginRuntimeError):
    """**我等得不够久**,不是对面坏了。

    这两件事此前在出口混成一句话。借道这条运行时的功能(Blender 互通)因此把「超时」
    说成了「Add-on 没连上」—— 而那时 Blender 其实正在好好地跑,于是排查从第一步就走错了路。
    """


@dataclass(frozen=True)
class ToolResult:
    """一次调用的两样产出。

    分成两样而不是一个字典,是因为它们的去向不同:`output` 回给调用方(以及模型),
    `state` 只落库、谁都看不到。混在一起的话,一个刚刷新出来的 access_token 会顺着
    工具结果流进对话记录里。
    """

    output: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)


def resolve_entry(plugin_dir: Path, entry: str) -> Path:
    """入口脚本的绝对路径。

    **要目录和入口,不要"一份清单"** —— 这里曾经收一个字典、自己读顶层 `entry`,于是同一个
    字段有了两个读法(清单模块认 `runtime.entry`,这里认顶层 `entry`),中间靠调用方现搭一个
    `{"_path", "entry"}` 的假清单粘着。粘住的两边一旦分开走,插件就装得上、跑不动。
    """
    if not entry:
        raise PluginRuntimeError("pluginErr_noEntry")
    if not plugin_dir.is_dir():
        raise PluginRuntimeError("pluginErr_dirMissing")
    entry_path = (plugin_dir / entry).resolve()
    if not str(entry_path).startswith(str(plugin_dir.resolve()) + os.sep):
        raise PluginRuntimeError("pluginErr_entryOutside")
    if not entry_path.is_file():
        raise PluginRuntimeError("pluginErr_entryMissing", entry=entry)
    return entry_path


class _CancelSwitch:
    """挂在任务名下的那个插件进程。记下「是不是取消杀的」,好把原因说对。"""

    def __init__(self, job_id: str, process: subprocess.Popen) -> None:
        self.job_id = job_id
        self._process = process
        self.pulled = False

    def kill(self) -> None:
        self.pulled = True
        self._process.kill()


def _attach_to(job_id: str, attached: list[_CancelSwitch]) -> Callable[[subprocess.Popen], None]:
    def attach(process: subprocess.Popen) -> None:
        switch = _CancelSwitch(job_id, process)
        attached.append(switch)
        register_job_child(job_id, switch)

    return attach


def check_required_input(tool: dict[str, Any], input_payload: dict[str, Any]) -> None:
    schema = tool.get("input_schema") or {}
    required = schema.get("required") if isinstance(schema, dict) else None
    if not isinstance(required, list):
        return
    missing = [key for key in required if isinstance(key, str) and key not in input_payload]
    if missing:
        raise PluginRuntimeError("pluginErr_missingInput", keys=", ".join(missing))


def execute_tool(
    plugin_dir: Path,
    entry: str,
    tool_name: str,
    input_payload: dict[str, Any],
    credentials: dict[str, str] | None = None,
    scratch_dir: Path | None = None,
    timeout: float = PLUGIN_TIMEOUT_SECONDS,
    data_dir: Path | None = None,
) -> ToolResult:
    """Run the plugin entry once. Returns the tool output dict; raises
    PluginRuntimeError with an actionable message on any failure.

    `credentials` are this plugin's own declared keys, injected as environment
    variables — never the app's.

    `scratch_dir` 是这次调用的产出目录:插件要交出一个文件时写在那儿,路径经
    MOSAEL_PLUGIN_OUTPUT_DIR 告诉它(见 artifacts 的说明)。协议本身只搬 JSON,
    所以搬字节这件事得另开一条路。"""
    entry_path = resolve_entry(plugin_dir, entry)
    #: **这次调用要说哪种语言。** 清单里的文案我们替它挑(见 manifest.text_of),但工具**跑出来**
    #: 的那些字(摘要、失败原因、枚举出来的项目名)只有插件自己写得出 —— 不告诉它读的人用什么
    #: 语言,它就只能压一种。请求体和环境变量都给一份:进程插件读哪个都行,而 MCP 那条只有环境变量。
    locale = get_current_locale()
    request = json.dumps({"tool": tool_name, "input": input_payload, "locale": locale}, ensure_ascii=False)
    env = _env(locale, credentials, scratch_dir, data_dir)
    started = time.monotonic()
    #: **跑在一个任务里时,这个进程归那个任务。** 取消任务要真的停下它,而不只是改一行状态 ——
    #: 否则一个跑十分钟的插件在用户点了停止之后照跑,工作流的并行分支、画板上的运行都一样。
    #: 登记在父任务名下(工作流里是工作流那个任务;同一个任务可以同时挂几个,见 jobs)。
    job_id = current_parent_job_id()
    attached: list[_CancelSwitch] = []
    try:
        result = run_logged(
            [_python(), str(entry_path)],
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=entry_path.parent,
            env=env, what="插件命令",
            on_child=_attach_to(job_id, attached) if job_id else None)
    except subprocess.TimeoutExpired as exc:
        raise PluginTimeout("pluginErr_timeout", seconds=f"{timeout:g}") from exc
    finally:
        for switch in attached:
            detach_job_child(switch.job_id, switch)
    if any(switch.pulled for switch in attached):
        # 是取消杀的,不是插件自己崩的 —— 别把一个 -9 退出码当成插件的错报出去。
        raise PluginCancelled("pluginErr_cancelled")
    duration_ms = int((time.monotonic() - started) * 1000)

    if result.returncode != 0:
        # 取尾巴会撞上进度条 / 收尾提示 —— 判据收在 core/text.blame_line 一处(那里记着它踩过几次)。
        why = blame_line(result.stderr or result.stdout, fallback="")
        if not why:
            raise PluginRuntimeError("pluginErr_processExitNoReason", code=result.returncode)
        raise PluginRuntimeError("pluginErr_processExit", code=result.returncode, detail=why)
    stdout = result.stdout.strip()
    if len(stdout) > MAX_OUTPUT_BYTES:
        raise PluginRuntimeError("pluginErr_outputTooLarge")
    try:
        response = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PluginRuntimeError("pluginErr_outputNotJson", tail=stdout[-300:]) from exc
    result = _final_response(response)
    result.output["_duration_ms"] = duration_ms
    return result


def _python() -> str:
    # 打包版里 sys.executable 是应用自己 —— 拿它跑插件等于再起一个后端(见 core/interpreter)。
    python = base_python()
    if not python:
        raise PluginRuntimeError("pluginErr_noPython")
    return python


def _env(
    locale: str, credentials: dict[str, str] | None, scratch_dir: Path | None, data_dir: Path | None
) -> dict[str, str]:
    return {
        **base_env(),
        "MOSAEL_PLUGIN": "1",
        #: **协议是 UTF-8 的 JSON,插件的 stdio 就是 UTF-8。** 不给这一格,子进程里的 Python 按 locale 编解码:
        #: 中文 Windows 上 stdin 按 GBK 解成乱码,英文 Windows 上 `ensure_ascii=False` 写中文直接
        #: UnicodeEncodeError —— 插件一个字都交不回来。跑插件的解释器是宿主挑的,所以由宿主说一次,
        #: 不让每个插件各自 reconfigure 一遍(第三方插件照着文档里的样板写,不会知道要这么做)。
        "PYTHONUTF8": "1",
        LOCALE_ENV: locale,
        **({ARTIFACT_SCRATCH_ENV: str(scratch_dir)} if scratch_dir is not None else {}),
        **({DATA_ENV: str(data_dir)} if data_dir is not None else {}),
        **(credentials or {}),
    }


def _final_response(response: Any) -> ToolResult:
    """最后那一个 JSON 对象 → 结果。一问一答和流式两条路共用这一段判读。"""
    if not isinstance(response, dict):
        raise PluginRuntimeError("pluginErr_outputNotObject")
    if not response.get("ok"):
        said = str(response.get("error") or "")
        if said:
            raise PluginRuntimeError("pluginErr_upstream", detail=said)
        raise PluginRuntimeError("pluginErr_failedNoReason")
    output = response.get("output")
    if not isinstance(output, dict):
        raise PluginRuntimeError("pluginErr_outputNoOutput")
    state = response.get("state")
    if state is not None and not isinstance(state, dict):
        raise PluginRuntimeError("pluginErr_stateNotObject")
    return ToolResult(output=output, state=dict(state or {}))


# ---------------------------------------------------------------------------
# 流式:一次长活(生成)的进度、回执与取消
# ---------------------------------------------------------------------------

#: 取消文件的路径经这个环境变量告诉插件。**宿主建它 = 请你停下**。
#:
#: 用文件不用信号:Windows 上没有可靠的 SIGTERM(那就是 TerminateProcess,插件没有机会去让
#: 远端停下 —— 对 ComfyUI 来说就是没机会 POST /interrupt),而「检查一个文件在不在」任何语言
#: 一行就写完。
CANCEL_ENV = "MOSAEL_PLUGIN_CANCEL_FILE"
#: 建了取消文件之后等插件自己收尾多久,再强杀。它要去停远端的活,那是一两次 HTTP 的事。
CANCEL_GRACE_SECONDS = 30.0
#: 多久问一次「取消了吗」。调用方的判据可能要查一次库,不必每一行输出都问。
CANCEL_POLL_SECONDS = 1.0
#: 一个回执最多多大。它会整份落进任务表(Job.payload.remote_task)。
MAX_TASK_BYTES = 8192


@dataclass(frozen=True)
class StreamHooks:
    """流式调用时宿主交给运行时的三样东西。

    `on_progress(比例, 一句话)`:插件说进度了。比例已经夹在 0..1。
    `on_task(回执)`:插件说「远端任务是这个」。**收到就得落库**(ADR 0019):从这一刻起那边在跑、
    可能在花钱,回执只活在这个进程里的话,后端一重启就再也找不回来。
    `is_cancelled()`:用户要停。至多每秒问一次。

    三个回调都在**调用 stream_tool 的那个线程**里被调 —— 调用方拿着的数据库会话不是线程安全的,
    所以读 stdout 的那个线程只负责把行放进队列,解释和回调都回到这里做。
    """

    on_progress: Callable[[float, str], None]
    on_task: Callable[[dict[str, Any]], None]
    is_cancelled: Callable[[], bool]


_EOF = object()


class _GracefulSwitch:
    """流式调用挂在任务名下的那个开关(和一问一答的 `_CancelSwitch` 同一套登记,见 jobs)。

    **拉下它不是直接杀**:先建取消文件,让插件去停远端的活(ComfyUI 要 POST /interrupt,否则它会把
    这张图跑完、占着显卡,而结果没人要);插件宽限期内不退,`_follow` 再杀。没有取消文件可建
    (没给暂存目录)才直接杀。
    """

    def __init__(self, job_id: str, cancel_file: Path | None, child: ChildProcess) -> None:
        self.job_id = job_id
        self._cancel_file = cancel_file
        self._child = child
        self.pulled = False

    def kill(self) -> None:
        self.pulled = True
        if self._cancel_file is not None:
            self._cancel_file.touch()
        else:
            self._child.kill()


def stream_tool(
    plugin_dir: Path,
    entry: str,
    tool_name: str,
    input_payload: dict[str, Any],
    credentials: dict[str, str] | None = None,
    *,
    hooks: StreamHooks,
    scratch_dir: Path | None = None,
    timeout: float = PLUGIN_TIMEOUT_SECONDS,
    data_dir: Path | None = None,
) -> ToolResult:
    """跑一次**长活**:插件边做边说,最后一行给结果。

    和 `execute_tool` 同一个入口、同一份环境、同一个结果形状;不同的是 stdout 是**一行一个 JSON
    对象**(NDJSON):

        {"event": "progress", "progress": 0.42, "message": "KSampler 12/20"}
        {"event": "task", "task": {"prompt_id": "…"}}
        {"ok": true, "output": {…}}

    取消与超时走同一条路:建取消文件(`MOSAEL_PLUGIN_CANCEL_FILE`)→ 给插件 CANCEL_GRACE_SECONDS
    去停远端的活 → 还不退就杀。超时不是直接杀:远端还在跑的话,插件是唯一知道怎么让它停下的一方。
    """
    entry_path = resolve_entry(plugin_dir, entry)
    locale = get_current_locale()
    request = json.dumps({"tool": tool_name, "input": input_payload, "locale": locale}, ensure_ascii=False)
    cancel_file = Path(f"{scratch_dir}.cancel") if scratch_dir is not None else None
    env = _env(locale, credentials, scratch_dir, data_dir)
    if cancel_file is not None:
        env[CANCEL_ENV] = str(cancel_file)
    process = popen_text(
        [_python(), str(entry_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=entry_path.parent,
        env=env,
    )
    child = ChildProcess(process)
    #: 跑在一个任务里时,这个进程归那个任务(和 execute_tool 同一条):取消任务就拉下开关。
    job_id = current_parent_job_id()
    switch = _GracefulSwitch(job_id, cancel_file, child) if job_id else None
    if switch is not None:
        register_job_child(job_id, switch)
    lines: queue.Queue[Any] = queue.Queue()

    def pump() -> None:
        try:
            for line in child.raw_lines():
                lines.put(line)
        except Exception:  # noqa: BLE001 — 管道断了就是读完了
            pass
        finally:
            lines.put(_EOF)

    reader = threading.Thread(target=pump, daemon=True, name=f"plugin-stream-{tool_name}")
    reader.start()
    try:
        if process.stdin is not None:
            try:
                process.stdin.write(request)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass  # 插件没读就退了 —— 退出码和 stderr 会说为什么
        final, stopped = _follow(child, lines, hooks, cancel_file, timeout, switch)
    except BaseException:
        child.kill()
        raise
    finally:
        if switch is not None:
            detach_job_child(switch.job_id, switch)
        why = child.finish()
        reader.join(timeout=1.0)
        if cancel_file is not None:
            cancel_file.unlink(missing_ok=True)

    if stopped == "cancelled":
        raise PluginCancelled("pluginErr_cancelled")
    if stopped == "timeout":
        raise PluginTimeout("pluginErr_timeout", seconds=f"{timeout:g}")
    if process.returncode not in (0, None) and final is None:
        reason = blame_line(why, fallback="")
        if not reason:
            raise PluginRuntimeError("pluginErr_processExitNoReason", code=process.returncode)
        raise PluginRuntimeError("pluginErr_processExit", code=process.returncode, detail=reason)
    if final is None:
        raise PluginRuntimeError("pluginErr_streamNoResult", shape='{"ok": true, "output": {…}}')
    return _final_response(final)


def _follow(
    child: ChildProcess,
    lines: "queue.Queue[Any]",
    hooks: StreamHooks,
    cancel_file: Path | None,
    timeout: float,
    switch: "_GracefulSwitch | None" = None,
) -> tuple[dict[str, Any] | None, str]:
    """读到 stdout 关上为止。返回 (最后那个结果对象, 停下的原因:""/"cancelled"/"timeout")。"""
    deadline = time.monotonic() + timeout
    next_check = 0.0
    asked_to_stop_at: float | None = None
    stopped = ""
    final: dict[str, Any] | None = None
    while True:
        try:
            line = lines.get(timeout=0.25)
        except queue.Empty:
            line = None
        if line is _EOF:
            return final, stopped
        if line:
            parsed = _parse_line(line)
            if parsed is not None:
                if "event" in parsed:
                    _dispatch(parsed, hooks)
                elif "ok" in parsed:
                    final = parsed
        now = time.monotonic()
        if asked_to_stop_at is None:
            if switch is not None and switch.pulled:
                stopped = "cancelled"
            elif now >= next_check:
                next_check = now + CANCEL_POLL_SECONDS
                if hooks.is_cancelled():
                    stopped = "cancelled"
            if not stopped and now >= deadline:
                stopped = "timeout"
            if stopped:
                asked_to_stop_at = now
                if cancel_file is not None:
                    cancel_file.touch()
                else:
                    child.kill()
        elif now - asked_to_stop_at > CANCEL_GRACE_SECONDS:
            logger.warning("插件在取消后 %.0f 秒仍未退出,强制结束", CANCEL_GRACE_SECONDS)
            child.kill()
            asked_to_stop_at = float("inf")


def _parse_line(line: str) -> dict[str, Any] | None:
    """一行 stdout → 一个 JSON 对象。不是的一律跳过:插件往 stdout 打了句日志不该让整次生成失败。"""
    text = line.strip()
    if not text.startswith("{"):
        return None
    if len(text) > MAX_OUTPUT_BYTES:
        logger.warning("插件的一行输出超过 %d 字节,已跳过", MAX_OUTPUT_BYTES)
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _dispatch(event: dict[str, Any], hooks: StreamHooks) -> None:
    kind = event.get("event")
    if kind == "progress":
        raw = event.get("progress")
        fraction = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0
        fraction = 0.0 if fraction != fraction else min(1.0, max(0.0, fraction))
        hooks.on_progress(fraction, str(event.get("message") or "")[:200])
    elif kind == "task":
        task = event.get("task")
        if isinstance(task, dict) and len(json.dumps(task, ensure_ascii=False)) <= MAX_TASK_BYTES:
            hooks.on_task(task)
        else:
            logger.warning("插件交回的回执不是对象或太大(上限 %d 字节),没有记下", MAX_TASK_BYTES)


__all__ = [
    "CANCEL_ENV", "CANCEL_GRACE_SECONDS", "DATA_ENV", "PluginCancelled", "PluginRuntimeError", "PluginTimeout",
    "StreamHooks", "ToolResult", "check_required_input", "data_dir_for", "execute_tool", "resolve_entry",
    "stream_tool", "PLUGIN_TIMEOUT_SECONDS",
]

