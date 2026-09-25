"""ComfyUI 插件的入口:替 Mosael 做生成(见 docs/PLUGIN_MANIFEST 的「替宿主做生成」)。

一个工具 `comfyui_generation`,两种 `op`:

    {"op": "models"}      → 一行结果:这台 ComfyUI 上有哪些模型(内置文生图、粘贴的模板、保存的每张工作流)
    {"op": "generate", …} → 一行一个事件(进度、回执),最后一行是结果

标准库之外什么都不用 —— 插件跑在随应用发的那个 Python 上。
"""

from __future__ import annotations

import json
import os
import sys
import traceback

import models
import run
from comfy_http import Comfy, env_base_url
from lines import ComfyError, say


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    request = json.loads(sys.stdin.read() or "{}")
    payload = request.get("input") or {}
    locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    try:
        if request.get("tool") != "comfyui_generation":
            raise ComfyError(say(locale, f"不认识的工具:{request.get('tool')}", f"Unknown tool: {request.get('tool')}"))
        comfy = Comfy(env_base_url(), locale)
        op = payload.get("op")
        if op == "models":
            output = {"models": models.catalog(comfy, locale)}
        elif op == "generate":
            output = run.generate(payload, comfy, locale, emit)
        else:
            raise ComfyError(say(locale, f"不认识的操作:{op}", f"Unknown op: {op}"))
        emit({"ok": True, "output": output})
    except ComfyError as exc:
        emit({"ok": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — 插件自己的 bug:把原因交回去,别只留一个退出码
        traceback.print_exc(file=sys.stderr)
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
