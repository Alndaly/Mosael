"""ComfyUI 插件的入口。

两类调用走同一个入口(见 docs/PLUGIN_MANIFEST):

**替宿主做生成** —— 工具 `comfyui_generation`,只给宿主调:

    {"op": "models"}      → 一行结果:这台 ComfyUI 上有哪些模型(内置文生图、粘贴的模板、保存的每张工作流)+ 指纹
    {"op": "tools"}       → 一行结果:每张工作流一个工具(入参、输出都从那张图推出来)+ 指纹
    {"op": "fingerprint"} → 一行结果:清单的指纹(宿主隔一会儿问一次,变了才重新拉目录)
    {"op": "generate", …} → 一行一个事件(进度、回执),最后一行是结果;带 `graph` 跑工作台画布上现在这张(见 run)

**本机服务**(ADR 0041,清单 `services` 里的那一种归这个工具,见 service):

    {"op": "service_detect" | "service_launch" | "service_add_nodes" | "service_discover" | "service_readdress", …}
                                           → 怎么认一个装好的目录、怎么起、补装 pysssss、本机发现、改端口时搬数据
    {"op": "service_plan", …}              → 让 Mosael 装:这台机器能不能装、装哪种 PyTorch、要多少空间、分几步(见 managed)
    {"op": "service_install", …}           → 流式:一步一行进度,取消了停在那一步,再来从没做完的那一步接着装
    {"op": "service_versions", …}          → 让 Mosael 装的那一份:装着哪个、能更新到哪个、能回到哪个、有没有没做完的(见 versions)
    {"op": "service_update" | "service_rollback", …} → 流式:换到更新的钉死版本(没成自己换回去)/ 回到上一版
    {"op": "service_uninstall", …}         → 卸载之前:是不是一份让 Mosael 装的、模型文件夹在哪、多大(见 managed)
    {"op": "service_model_folders", …}     → 共用的模型文件夹:每一处认成什么、在跑的话加载了没有、几个模型(见 shared_models)
    {"op": "service_busy"}                 → 闲置自动停之前:任务队列里有没有在跑、在排的

**模型库**(ADR 0034,同一个工具认领 `model_library`):

    {"op": "library"}                      → 全部模型文件、各目录数目、工作流缺的模型、下载走哪条路(见 library)
    {"op": "detail", "folder", "name"}     → 一个文件的完整元数据
    {"op": "resolve", "url"}               → 一个链接指的是哪个文件(见 sources)
    {"op": "search_sources", "filename", "folder"} → 按文件名去 HuggingFace / ModelScope / Civitai 找下载地址,每个候选的链接 resolve 都认(见 model_search)
    {"op": "download", "url", "folder", "filename"} → 流式:下到这台 ComfyUI 上(见 install)
    {"op": "node_folders", "nodes"}         → 工作台:选中节点上选模型文件的那几格各是哪个模型目录(见 workbench)
    {"op": "lookup", "folder", "name", "refresh"?} → 在 Civitai 上找这个文件(按哈希,或文件名和大小;见 lookup)
    {"op": "save_preview", "folder", "name", "path"} → 把宿主交来的那张图写成这个文件的预览图(见 previews)

**工作流库**(ADR 0035,同一个工具认领 `workflow_library`,见 workflow_library):

    {"op": "workflows"}                                 → 全部工作流(图摘要、输入 / 参数 / 输出、用到的模型、缺什么)
    {"op": "workflow", "path"}                          → 一张的原文
    {"op": "copy_workflow" | "rename_workflow" | "restore_workflow", "path", "new_path"} → 不覆盖,撞名回 conflict
    {"op": "trash_workflow", "path"}                    → 挪进回收目录(不硬删)
    {"op": "make_folder", "path"}                       → 新建文件夹(写一个隐藏的占位文件;已有回 conflict)
    {"op": "rename_folder", "path", "new_path"}         → 文件夹改名 / 挪走(整个目录一次挪;不覆盖)
    {"op": "trash_folder", "path"}                      → 删除文件夹:只删空的,挪进回收目录;里面还有文件回 not_empty
    {"op": "app", "path"}                               → 一张的应用表单(ADR 0038):全部能填的项、文件里的标记、改动时间
    {"op": "app", "content"}                            → 同上,读的是工作台画布上现在这张(不读文件,没有改动时间)
    {"op": "annotate", "path", "modified", "app", "results"} → 只改 mosael 标记、覆盖写;改动时间对不上回 stale
    {"op": "app_marks", "content", "app", "results"}    → 工作台:应用表单写进画布要改成的那几处标记(不写文件,见 workbench)

**工作台里的智能体**(ADR 0042,都只读 —— 改画布的是桥,这里只算;宿主经 `workflow_library` 问,见 canvas / canvas_edit / diagnose /
templates / node_types / node_packs):

    {"op": "canvas_summary", "content"}                 → 一张图(画布上这张、一张模板)的摘要:每一层的节点、控件的值、连线
    {"op": "check_graph", "content", "error"?, "baseline"?} → 问题单:按节点列,带严重程度、原因、改法;给了上次运行的报错就拆到节点;
                                                          给了改之前的那一份就说修好了几个、多出来几个
    {"op": "edit_plan", "content", "ops"}               → 一批改动:校验(一条说不通整批不交)、交给桥的那一批、改动清单、子图用了几处、
                                                          改前改后各一次诊断
    {"op": "templates", "query"?, "task"?, "model"?, "locale"?, "limit"?} → 官方模板和节点包自带的模板:要哪些模型、多大、
                                                          要哪一版 ComfyUI,这台机器上有哪几个、缺哪几个
    {"op": "template", "name", "pack"?}                 → 一张模板的整图,照这台机器改好能改的(说改了什么),缺什么、多大
    {"op": "node_types", "query"?, "classes"?, "limit"?} → 节点类型:输入(类型、必填、可选值、缺省值)和输出
    {"op": "node_packs", "content"?}                    → 装了哪些节点包(版本、开没开、提供哪些节点);给了图就说每个节点来自哪个包
    {"op": "node_pack_search", "query"?, "node_types"?} → 找节点包:先查 Manager 的映射,再查 Comfy 官方注册表
    {"op": "node_pack_info", "id", "content"?}          → 分析一个节点包:注册表里的状态(被标记 / 封禁 / 弃用)、谁发的、多少人用、
                                                          依赖会不会动到 torch、和这台机器合不合、装了哪一版、能补上图里缺的哪几个

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

import canvas
import canvas_edit
import diagnose
import install
import library
import lookup
import managed
import model_search
import models
import node_packs
import node_types
import pinned
import previews
import run
import server
import service
import shared_models
import sources
import templates
import tooling
import versions
import workflow_import
import workbench
import workflow_library
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
    if op == "library":
        return library.library(payload, comfy, locale)
    if op == "detail":
        return library.detail(payload, comfy, locale)
    if op == "resolve":
        return sources.resolve(payload, comfy, locale)
    if op == "search_sources":
        return model_search.search(payload, comfy, locale)
    if op == "download":
        return install.download(payload, comfy, locale, emit)
    if op == "node_folders":
        return workbench.node_folders(payload, comfy, locale)
    if op == "lookup":
        return lookup.lookup(payload, comfy, locale)
    if op == "save_preview":
        return previews.save(payload, comfy, locale)
    if op == "install_nodes":
        return workflow_import.install_nodes(payload, comfy, locale, emit)
    if op in _WORKFLOW_LIBRARY:
        return _WORKFLOW_LIBRARY[op](payload, comfy, locale)
    if op in _AGENT:
        return _AGENT[op](payload, comfy, locale)
    raise ComfyError(say(locale, f"不认识的操作:{op}", f"Unknown op: {op}"))


#: 工作流库的 op(ADR 0035)。
_WORKFLOW_LIBRARY: dict[str, Callable[[dict[str, Any], Comfy, str], dict[str, Any]]] = {
    "workflows": workflow_library.workflows,
    "workflow": workflow_library.workflow,
    "copy_workflow": workflow_library.copy_workflow,
    "rename_workflow": workflow_library.rename_workflow,
    "trash_workflow": workflow_library.trash_workflow,
    "restore_workflow": workflow_library.restore_workflow,
    "make_folder": workflow_library.make_folder,
    "rename_folder": workflow_library.rename_folder,
    "trash_folder": workflow_library.trash_folder,
    "app": workflow_library.app,
    "annotate": workflow_library.annotate,
    "app_marks": workbench.app_marks,
    "inspect_import": workflow_import.inspect_import,
    "save_workflow": workflow_import.save_workflow,
    "reboot": workflow_import.reboot,
}

#: 工作台里的智能体要问的(ADR 0042),都只读(改画布的计划也只是算出来,改由画布的桥做)。
_AGENT: dict[str, Callable[[dict[str, Any], Comfy, str], dict[str, Any]]] = {
    "canvas_summary": canvas.canvas_summary,
    "check_graph": diagnose.check_graph,
    "edit_plan": canvas_edit.edit_plan,
    "templates": templates.templates,
    "template": templates.template,
    "node_types": node_types.node_types,
    "node_packs": node_packs.node_packs,
    "node_pack_search": node_packs.node_pack_search,
    "node_pack_info": node_packs.node_pack_info,
}

#: 本机服务的一问一答(ADR 0041):选目录那一种的五个在 service,「让 Mosael 装」的安装计划、卸载前问的在 managed,换版本在 versions。
#: 起之前先经 versions 看一眼:让 Mosael 装的那一份换版本换到一半(被强行打断)就不起它。
_SERVICE: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    **service.OPS, "service_launch": versions.launch, "service_plan": managed.plan, "service_versions": versions.versions,
    "service_uninstall": managed.uninstall,
}
#: 流式的本机服务操作:一步一行进度(`{"event": "step", …}`),宿主建取消文件就停。
_SERVICE_STREAMING: dict[str, Callable[[dict[str, Any], str, run.Emit], dict[str, Any]]] = {
    "service_install": managed.install,
    "service_update": versions.update,
    "service_rollback": versions.rollback,
}

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
        if tool == "comfyui_generation" and payload.get("op") in _SERVICE:
            # 本机服务的操作(ADR 0041):只描述、不起进程,也不和那台服务器说话 —— 问怎么起的时候它当然还没起
            output = _SERVICE[payload["op"]](payload, locale)
            emit({"ok": True, "output": output})
            return
        if tool == "comfyui_generation" and payload.get("op") == "service_model_folders":
            # 共用的模型文件夹:认每一处;它在跑的话顺带问那台 ComfyUI 加载了没有、从那里看到几个模型
            comfy = Comfy(env_base_url(), locale, env_access_token()) if env_base_url() else None
            emit({"ok": True, "output": shared_models.model_folders(payload, locale, comfy=comfy)})
            return
        if tool == "comfyui_generation" and payload.get("op") == "service_busy":
            # 闲置自动停之前:它的任务队列里有没有在跑、在排的
            emit({"ok": True, "output": service.busy(payload, locale, comfy=Comfy(env_base_url(), locale, env_access_token()))})
            return
        if tool == "comfyui_generation" and payload.get("op") in _SERVICE_STREAMING:
            # 让 Mosael 装、换版本(流式:一步一行,宿主建取消文件就停在那一步,下次接着来)
            emit({"ok": True, "output": _SERVICE_STREAMING[payload["op"]](payload, locale, emit)})
            return
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
        #: 两种语言都交:连接的出错原因会被宿主存下来,给人看时按读的人的语言挑(见 lines)。
        emit({"ok": False, "error": exc.said})
    except pinned.Cancelled:
        # 宿主建了取消文件:它自己知道是取消,这一行只是交代一声
        emit({"ok": False, "error": {"zh": "取消了", "en": "Cancelled"}})
    except Exception as exc:  # noqa: BLE001 — 插件自己的 bug:把原因交回去,别只留一个退出码
        traceback.print_exc(file=sys.stderr)
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
