"""ComfyUI 插件的入口。

两类调用走同一个入口(见 docs/PLUGIN_MANIFEST):

**替宿主做生成** —— 工具 `comfyui_generation`,只给宿主调:

    {"op": "models"}      → 一行结果:这台 ComfyUI 上有哪些模型(内置文生图、粘贴的模板、保存的每张工作流)+ 指纹
    {"op": "tools"}       → 一行结果:每张工作流一个工具(入参、输出都从那张图推出来)+ 指纹
    {"op": "fingerprint"} → 一行结果:清单的指纹(宿主隔一会儿问一次,变了才重新拉目录)
    {"op": "generate", …} → 一行一个事件(进度、回执),最后一行是结果

**给智能体和工作流的工具**:

    wf_<id>                                                每张工作流自己的那个(运行时报出,流式)
    list_workflows / server_status / list_models           只读,一问一答
    import_outputs                                         流式(清单里 `stream: true`):进度一行一个,最后一行是结果
    interrupt / clear_queue / free_memory                  会动服务器,一问一答

标准库之外什么都不用 —— 插件跑在随应用发的那个 Python 上。
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Callable

import models
import run
import server
import tooling
import workflows
from comfy_http import Comfy, env_access_token, env_base_url
from lines import ComfyError, say


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _generation(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    op = payload.get("op")
    if op == "models":
        return {"models": models.catalog(comfy, locale), "fingerprint": models.fingerprint(comfy)}
    if op == "tools":
        return {"tools": tooling.catalog(comfy, locale), "fingerprint": models.fingerprint(comfy)}
    if op == "fingerprint":
        # 模型清单和工具清单出自同一批图,指纹是同一个(请求里的 `capability` 说问的是哪一份)
        return {"fingerprint": models.fingerprint(comfy)}
    if op == "generate":
        return run.generate(payload, comfy, locale, emit)
    raise ComfyError(say(locale, f"不认识的操作:{op}", f"Unknown op: {op}"))


#: 一问一答的工具。
_PLAIN: dict[str, Callable[[dict[str, Any], Comfy, str], dict[str, Any]]] = {
    "list_workflows": workflows.list_workflows,
    "server_status": server.server_status,
    "list_models": server.list_models,
    "interrupt": server.interrupt,
    "clear_queue": server.clear_queue,
    "free_memory": server.free_memory,
}
#: 流式的工具(清单里声明了 `stream: true`):边跑边说进度,宿主取消时去停 ComfyUI 那边的任务。
_STREAMING: dict[str, Callable[[dict[str, Any], Comfy, str, run.Emit], dict[str, Any]]] = {
    "import_outputs": workflows.import_outputs,
}


def main() -> None:
    request = json.loads(sys.stdin.read() or "{}")
    payload = request.get("input") or {}
    locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    tool = request.get("tool")
    try:
        comfy = Comfy(env_base_url(), locale, env_access_token())
        if tool == "comfyui_generation":
            output = _generation(payload, comfy, locale)
        elif tool in _PLAIN:
            output = _PLAIN[tool](payload, comfy, locale)
        elif tool in _STREAMING:
            output = _STREAMING[tool](payload, comfy, locale, emit)
        elif isinstance(tool, str) and tool.startswith("wf_"):
            # 每张工作流一个的那些工具(运行时报给宿主的,见 tooling)
            output = tooling.run_tool(tool, payload, comfy, locale, emit)
        else:
            raise ComfyError(say(locale, f"不认识的工具:{tool}", f"Unknown tool: {tool}"))
        emit({"ok": True, "output": output})
    except ComfyError as exc:
        emit({"ok": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — 插件自己的 bug:把原因交回去,别只留一个退出码
        traceback.print_exc(file=sys.stderr)
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
