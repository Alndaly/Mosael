"""工作台里的智能体(ADR 0042:读和诊断、改和新建)—— 宿主这一侧。工具在 mcp_server 的 `comfy_*`。

两条路:

- **碰画布的**(读这张图、在画布上指出一个节点):画布的桥只在桌面版主进程里,后端够不着。照浏览器动作的样子走
  「后端 → 主进程 → 页面」:这里排一条工作台动作(browser.workbench_session / run_workbench,租约、超时、执行器掉线都是那一套),
  执行器交给**那个连接开着的工作台**,报回桥的回答。工作台没开着(用户回到了 Mosael、桌面端没开、网页版)就说「先在工作台里
  打开这台 ComfyUI」。
- **问插件的**(摘要、诊断、模板、节点类型、节点包):ComfyUI 的知识在插件里(ADR 0042 §3),这里经 `workflow_library` 那个
  工具问,规整出口。

连接归人(和插件页同一条):只认**调用的人自己接的**那个连接;没说是哪一个、他又只接了一台,就是那一台。

**改画布**(第二步):一批改动先由插件对着画布上这张算一遍(edit_plan:每一条都查、在拷贝上改一遍、改前改后各诊断一次),
说不通或者改完多出错误的不开卡;开卡时画布一点不动,卡上是改动清单。批准之后对着**现在**的画布再算一遍,对得上才交给桥
(一批只占一步撤销)。**新标签页**(`comfy_canvas_new`)不动开着的那几张、不开卡;两样都不存盘、不写那台机器上的文件、不排任务。
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, get_current_locale, render_message
from app.db.models import PluginInstance, User
from app.domain import browser
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.plugins import instances as inst
from app.domain.plugins import runtime, tools
from app.domain.plugins.manifest import WORKFLOW_LIBRARY

#: 问插件的上限:取模板要把几张模板的整图取一遍、问下载地址多大;注册表在公网上。
PLUGIN_TIMEOUT_SECONDS = 120
#: 画布上节点的写法:根图上的编号,子图里的从根图往里走的编号(冒号隔开,最多 16 段;只有第一段可以带负号)。
#: 它是 **`contracts/node-shapes.json` 的 `canvas_path`** —— 插件 `canvas_edit._PATH`、前端 `nodeRefs.NODE_REF`
#: 和这里是同一套判据,两侧的跑手读同一份语料(`backend/tests/test_node_shapes_parity.py`)。桥那一侧把它
#: 拆成了 `CANVAS_NODE` + `NODE_PATH` 两条(见契约的 `divergence`)。
_NODE_REF = re.compile(r"^-?\d{1,10}(?::\d{1,10}){0,16}$")
#: 子图定义的 id(前端给的是 UUID 那样的串)。
_SUBGRAPH_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: 回给智能体的字最多多少(各项加起来;摘要、问题单本来就截过)。
_JOB_ERROR_CHARS = 20000


class WorkbenchAgentError(LocalizedError, ValueError):
    """工作台的智能体这一侧说不行(没开着工作台、连接不对、节点指不到)。带文案 key(`workbenchErr_*`)。"""


# --- 哪个连接 -----------------------------------------------------------------------------

def connection(db: Session, user: User, instance_id: str = "") -> PluginInstance:
    """调用的人自己接的、认领了工作流库的那个连接(ComfyUI)。没说是哪个、又只有一台 → 那一台。"""
    mine = [one for one in db.scalars(select(PluginInstance).where(PluginInstance.owner_user_id == user.id))
            if WORKFLOW_LIBRARY in inst.manifest_for(db, one).provides]
    if instance_id:
        found = next((one for one in mine if one.id == instance_id), None)
        if found is None:
            raise WorkbenchAgentError("workbenchErr_noConnection")
        return found
    if len(mine) == 1:
        return mine[0]
    if not mine:
        raise WorkbenchAgentError("workbenchErr_noComfy")
    names = "; ".join(f"{one.name} = {one.id}" for one in mine[:10])
    raise WorkbenchAgentError("workbenchErr_whichConnection", names=names)


def _ask(db: Session, instance: PluginInstance, payload: dict[str, Any], *,
         output_budget: int | None = None) -> dict[str, Any]:
    """问插件一句。`output_budget` 只给**目录类回答**(见 `runtime.CATALOG_OUTPUT_BYTES`):这一问返回的是
    「这台机器上现在有什么」的一整份清单时,才用它;别的问法一个字节都不放宽。"""
    return tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, payload, timeout=PLUGIN_TIMEOUT_SECONDS,
                             record=False, output_budget=output_budget)


# --- 画布(经主进程的那条路) ----------------------------------------------------------------

#: 桥回「这一页没有工作台」的几种原因:会话不在(视图收起了)、桥没注入、视图停在别的站点、前端还没起来。
_NOT_OPEN = {"closed", "missing", "elsewhere", "notReady"}
#: 动作排不上 / 执行器不在了:桌面端没开、网页版 —— 对用户来说都是「工作台没开着」。
_NO_EXECUTOR = {"browserErr_actionNotClaimed", "browserErr_actionQueueTimeout", "browserErr_executorLost"}


def _workbench(db: Session, user: User, workspace_id: str, instance: PluginInstance, call: dict[str, Any],
               *, name: str = "") -> dict[str, Any]:
    """在这个连接开着的工作台上做一件事,回桥的回答(`ok: true` 的那种)。`name`:改的是画布上叫什么的那一张(桥说已经换了一张、
    读过之后又改过的时候写进原因里)。"""
    ensure_workspace_access(db, user, workspace_id)
    session_id = browser.workbench_session(workspace_id=workspace_id, connection_id=instance.id)
    try:
        result = browser.run_workbench(session_id, call)
    except browser.BrowserDomainError as exc:
        if exc.key in _NO_EXECUTOR:
            raise WorkbenchAgentError("workbenchErr_notOpen", name=instance.name) from exc
        raise WorkbenchAgentError("workbenchErr_bridge", detail=str(exc)) from exc
    answer = result.get("value") if isinstance(result.get("value"), dict) else {}
    if answer.get("ok") is True:
        return answer
    error = str(answer.get("error") or "failed")
    if error in _NOT_OPEN:
        raise WorkbenchAgentError("workbenchErr_notOpen", name=instance.name)
    if error == "noNode":
        raise WorkbenchAgentError("workbenchErr_noNode", node=str(call.get("node") or ""))
    if error == "inSubgraph":
        raise WorkbenchAgentError("workbenchErr_inSubgraph", node=str(call.get("node") or ""))
    if error == "unsupported":
        raise WorkbenchAgentError("workbenchErr_unsupported", detail=str(answer.get("message") or call.get("op")))
    if error == "noWorkflow":
        raise WorkbenchAgentError("workbenchErr_noWorkflow", path=str(call.get("path") or ""))
    problems = "; ".join(str(one) for one in answer.get("problems") or [])[:1500]
    opened = answer.get("workflow") if isinstance(answer.get("workflow"), dict) else None
    if opened is not None and call.get("op") == "openWorkflow":
        # 新标签页开了、上面那一批没改上:标签页留着(只有起始的那张图),说清楚
        raise WorkbenchAgentError("workbenchErr_newPartly", name=str(opened.get("name") or ""),
                                  detail=problems or str(answer.get("message") or error)[:500])
    if error == "invalid":
        raise WorkbenchAgentError("workbenchErr_editRefused", detail=problems)
    if error == "otherWorkflow":
        raise WorkbenchAgentError("workbenchErr_editOtherTab", name=name)
    if error == "changed":
        raise WorkbenchAgentError("workbenchErr_editStale", name=name)
    raise WorkbenchAgentError("workbenchErr_bridge", detail=str(answer.get("message") or error)[:500])


def read_graph(db: Session, user: User, workspace_id: str, instance: PluginInstance) -> dict[str, Any]:
    """画布上现在这张(含没存的改动):界面格式的整图(子图的定义在 `definitions.subgraphs` 里)、选中的节点、改没改、
    开着的是哪一张、画布停在哪一层。"""
    answer = _workbench(db, user, workspace_id, instance, {"op": "readGraph"})
    graph = answer.get("graph") if isinstance(answer.get("graph"), dict) else None
    if graph is None or not isinstance(graph.get("workflow"), dict):
        raise WorkbenchAgentError("workbenchErr_bridge", detail="readGraph")
    return graph


def canvas(db: Session, user: User, workspace_id: str, instance_id: str = "") -> dict[str, Any]:
    """`comfy_canvas_read`:画布上这张的摘要(插件压的,见插件的 canvas.py)加上选中了谁、改没改、开着哪一张。"""
    instance = connection(db, user, instance_id)
    graph = read_graph(db, user, workspace_id, instance)
    summary = _ask(db, instance, {"op": "canvas_summary", "content": graph["workflow"]})
    layer = str(graph.get("layer") or "")
    #: 选中的节点:桥给的是画布**这一层**里的编号;停在子图里时换成从根图往里走的写法(按第一个用它的节点,和摘要一致)
    prefix = ""
    if layer:
        inside = next((one for one in summary.get("layers") or [] if one.get("id") == layer), None)
        prefix = f"{inside['instances'][0]}:" if inside and inside.get("instances") else ""
    return {
        "instance_id": instance.id,
        "workflow": graph.get("info") or {},
        "modified": bool(graph.get("modified")),
        "selection": [f"{prefix}{one}" for one in graph.get("selection") or []],
        **({"open_layer": layer} if layer else {}),
        **summary,
    }


def locate(db: Session, user: User, workspace_id: str, node: str, subgraph: str = "", instance_id: str = "") -> dict[str, Any]:
    """`comfy_locate`:在画布上选中、移到中间。`node` 用画布摘要里的写法(`12`、子图里的 `12:5`,桥先打开那一层);或者给
    子图定义的 id 加那一层里的编号。"""
    node = str(node or "").strip().lstrip("#")
    subgraph = str(subgraph or "").strip()
    if not _NODE_REF.match(node) or (subgraph and (not _SUBGRAPH_ID.match(subgraph) or ":" in node)):
        raise WorkbenchAgentError("workbenchErr_badNode", node=node[:40])
    instance = connection(db, user, instance_id)
    _workbench(db, user, workspace_id, instance, {"op": "locate", "node": node, "subgraph": subgraph or None})
    return {"located": node, **({"subgraph": subgraph} if subgraph else {})}


def _job_error(db: Session, user: User, job_id: str) -> str:
    """那次运行的失败原因(按读的人的语言);没失败是空串。"""
    from app.domain.job_center import use_cases as job_center

    job = job_center.readable(db, user, job_id)
    if job.status != "failed":
        return ""
    if job.error_key:
        return render_message(job.error_key, get_current_locale(), job.error_params or {})[:_JOB_ERROR_CHARS]
    return str(job.error or "")[:_JOB_ERROR_CHARS]


def check(db: Session, user: User, workspace_id: str, instance_id: str = "", job_id: str = "",
          error: str = "") -> dict[str, Any]:
    """`comfy_check`:诊断画布上这张(见插件的 diagnose.py)。给了那次运行的任务号就把它的报错拆到节点。"""
    instance = connection(db, user, instance_id)
    said = _job_error(db, user, job_id) if job_id else ""
    if error:
        said = f"{said}\n{error}".strip()
    graph = read_graph(db, user, workspace_id, instance)
    out = _ask(db, instance, {"op": "check_graph", "content": graph["workflow"], **({"error": said} if said else {})})
    return {"instance_id": instance.id, "workflow": graph.get("info") or {}, **out}


# --- 改画布、开新标签(ADR 0042 第二步) -------------------------------------------------------------

#: 问题单里交给智能体 / 写上确认卡的,每条只留这几样(原因和改法是插件按语言写好的)。
_FINDING_KEYS = ("ref", "type", "severity", "kind", "input", "cause", "fix", "model")
#: 新建时从空白搭:一张空的界面格式图。
EMPTY_GRAPH: dict[str, Any] = {"last_node_id": 0, "last_link_id": 0, "nodes": [], "links": [], "groups": [], "config": {},
                               "extra": {}, "version": 0.4}


def _compact(findings: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    return [{key: one[key] for key in _FINDING_KEYS if key in one} for one in findings[:limit]]


def _opened(info: dict[str, Any] | None) -> dict[str, Any]:
    """画布上开着的那一张(桥的 readGraph 规整过的 `info`):名字、存过的相对路径(没存过是空串)、认哪一张的 key。"""
    info = info or {}
    return {"name": str(info.get("name") or ""), "path": str(info.get("path") or ""), "key": str(info.get("key") or ""),
            "temporary": bool(info.get("temporary"))}


def plan_edit(db: Session, user: User, workspace_id: str, instance: PluginInstance, ops: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """读画布上这张,插件对着它算这一批:(画布上这张, 计划)。一条说不通整批不交(插件把每一条的原因列出来)。"""
    if not isinstance(ops, list) or not ops:
        raise WorkbenchAgentError("workbenchErr_noOps")
    graph = read_graph(db, user, workspace_id, instance)
    return graph, _ask(db, instance, {"op": "edit_plan", "content": graph["workflow"], "ops": ops})


def propose_edit(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> None:
    """`comfy_canvas_edit` 开卡之前(确认卡的 validate):对着画布上这张算一遍,说不通、改完多出错误的不开卡;能开就把卡上要写的
    事实写回 `payload` —— 改的是哪一张、改动清单、子图用了几处、改前改后的诊断。画布这时一点没动。"""
    instance = connection(db, user, str(payload.get("instance_id") or ""))
    graph, plan = plan_edit(db, user, workspace_id, instance, payload.get("ops"))
    check = plan.get("check") or {}
    worse = [one for one in check.get("introduced") or [] if one.get("severity") == "error"]
    if worse:
        lines = "; ".join(f"#{one.get('ref') or '?'} {one.get('cause') or one.get('kind')}" for one in worse[:8])
        raise WorkbenchAgentError("workbenchErr_editIntroduces", count=len(worse), findings=lines[:1500])
    payload.update({
        "instance_id": instance.id,
        "workflow": _opened(graph.get("info")),
        "changes": plan.get("changes") or [],
        "subgraphs": plan.get("subgraphs") or [],
        "structural": bool(plan.get("structural")),
        "check": {"before": check.get("before") or {}, "after": check.get("after") or {},
                  "fixed": _compact(check.get("fixed") or []), "introduced": _compact(check.get("introduced") or [])},
    })


def apply_edit(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """批准之后:对着**现在**的画布再算一遍 —— 换了一张、或者清单对不上了(批之前画布又改过)就不改;对得上才交给桥(一批一步
    撤销),桥那边再核对一次画布上还是重读的那一张、重读之后没再改过(插件算的那一下里换了一张也不改)。改完再读一遍、诊断一遍,
    说修好了几个、多出来几个。"""
    instance = connection(db, user, str(payload.get("instance_id") or ""))
    proposed = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
    graph, plan = plan_edit(db, user, workspace_id, instance, payload.get("ops"))
    now = _opened(graph.get("info"))
    if now["key"] != str(proposed.get("key") or ""):
        raise WorkbenchAgentError("workbenchErr_editOtherTab", name=str(proposed.get("name") or proposed.get("key") or ""))
    if (plan.get("changes") or []) != (payload.get("changes") or []):
        raise WorkbenchAgentError("workbenchErr_editStale", name=now["name"])
    # 重读到交给桥之间还隔着插件算的那一下:桥在页面里再比一次还是不是读的那一张、读过之后改没改
    expect = {"key": now["key"], "revision": int(graph.get("revision") or 0)}
    answer = _workbench(db, user, workspace_id, instance, {"op": "applyOps", "ops": plan["ops"], "expect": expect},
                        name=now["name"])
    after = read_graph(db, user, workspace_id, instance)
    checked = _ask(db, instance, {"op": "check_graph", "content": after["workflow"],
                                  "baseline": (plan.get("check") or {}).get("baseline") or []})
    return {
        "applied": len(plan.get("changes") or []),
        "workflow": now,
        "created": answer.get("created") or {},
        "counts": checked.get("counts") or {},
        "fixed": _compact(checked.get("fixed") or []),
        "introduced": _compact(checked.get("introduced") or []),
        "undo": "Ctrl+Z",
    }


def open_new(db: Session, user: User, workspace_id: str, template: str = "", pack: str = "", path: str = "", name: str = "",
             ops: list[Any] | None = None, instance_id: str = "", opened_by: str = "") -> dict[str, Any]:
    """`comfy_canvas_new`:在新标签页开一张整图 —— 一张官方模板(照这台机器改好的)、模板上再改一批、从空白搭一批;或者打开存着的
    那一张(`path`)。不动开着的那几张,**不存盘**(存不存、存在哪是用户的事)。开好之后读一遍、诊断一遍。

    `opened_by`:是哪段对话开的(工具调用的凭据认出来的会话)。随动作交给主进程,开好之后它随状态报给工作台,让新标签页
    那一处接住这段对话(ADR 0044 §6)—— 不进页面。"""
    ensure_workspace_access(db, user, workspace_id)
    template, pack, path, name = (str(one or "").strip() for one in (template, pack, path, name))
    ops = list(ops or [])
    if template and path:
        raise WorkbenchAgentError("workbenchErr_newTemplateOrPath")
    if path and ops:
        raise WorkbenchAgentError("workbenchErr_newOpsOnSaved")
    if not (template or path or ops):
        raise WorkbenchAgentError("workbenchErr_newNothing")
    instance = connection(db, user, instance_id)
    out: dict[str, Any] = {"saved": False}
    opener = {"openedBy": opened_by} if opened_by else {}
    if path:
        answer = _workbench(db, user, workspace_id, instance, {"op": "openWorkflow", "path": path, **opener})
    else:
        graph: dict[str, Any] = EMPTY_GRAPH
        if template:
            adapted = _ask(db, instance, {"op": "template", "name": template, **({"pack": pack} if pack else {})})
            graph = adapted.pop("workflow")
            adapted.pop("summary", None)
            out["template"] = {key: adapted[key] for key in ("name", "title", "models", "changes", "missing_size", "missing_types",
                                                             "min_comfyui", "version_ok") if key in adapted}
            name = name or str(adapted.get("title") or template)
        call: dict[str, Any] = {"op": "openWorkflow", "graph": graph, "name": name or render_message(
            "workbenchNewWorkflowName", get_current_locale(), {}), **opener}
        if ops:
            plan = _ask(db, instance, {"op": "edit_plan", "content": graph, "ops": ops})
            call["ops"] = plan["ops"]
            out["changes"] = len(plan.get("changes") or [])
        answer = _workbench(db, user, workspace_id, instance, call)
    opened = answer.get("workflow") if isinstance(answer.get("workflow"), dict) else {}
    out["opened"] = {"name": str(opened.get("name") or ""), "temporary": bool(opened.get("temporary")),
                     "path": str(opened.get("path") or "").removeprefix("workflows/") if not opened.get("temporary") else ""}
    if answer.get("created"):
        out["created"] = answer["created"]
    after = read_graph(db, user, workspace_id, instance)
    checked = _ask(db, instance, {"op": "check_graph", "content": after["workflow"]})
    out["check"] = {"counts": checked.get("counts") or {}, "findings": _compact(checked.get("findings") or [])}
    return out


# --- 只问插件的 --------------------------------------------------------------------------------

def templates(db: Session, user: User, query: str = "", task: str = "", model: str = "", limit: int = 6,
              instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    return _ask(db, instance, {"op": "templates", "query": query, "task": task, "model": model,
                               "limit": max(1, min(12, int(limit or 6)))})


def template(db: Session, user: User, name: str, pack: str = "", instance_id: str = "") -> dict[str, Any]:
    """一张模板照这台机器改好的样子。整图(几十 KB 到几百 KB)不交给智能体:要的是改了什么、缺什么、多大、它的摘要。"""
    instance = connection(db, user, instance_id)
    out = _ask(db, instance, {"op": "template", "name": name, **({"pack": pack} if pack else {})})
    out.pop("workflow", None)
    return out


def node_types(db: Session, user: User, query: str = "", classes: list[str] | None = None, limit: int = 10,
               instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    payload: dict[str, Any] = {"op": "node_types", "limit": max(1, min(30, int(limit or 10)))}
    if classes:
        payload["classes"] = [str(one) for one in classes][:30]
    else:
        payload["query"] = query
    return _ask(db, instance, payload)


def _canvas_if_open(db: Session, user: User, workspace_id: str, instance: PluginInstance) -> dict[str, Any] | None:
    """工作台开着就带上画布上这张(节点包要说图里的节点来自哪、缺的谁能补);没开着不算错。桌面端的执行器不在(网页版)就
    不去排 —— 排了也只是白等那十几秒。"""
    if not browser.executor_online():
        return None
    try:
        return read_graph(db, user, workspace_id, instance)["workflow"]
    except WorkbenchAgentError:
        return None


def node_packs(db: Session, user: User, workspace_id: str, instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    graph = _canvas_if_open(db, user, workspace_id, instance)
    #: 一整份节点包清单是**目录类回答**(这台机器装了哪些包,每个最多 60 个节点类型,随装包数线性变大):
    #: 和工具清单 / 模型清单 / 模型库 / 工作流库同一份预算(见 runtime.CATALOG_OUTPUT_BYTES)。
    #: 别的问法(templates / node_types / node_pack_search …)照旧 1MB,一个字节都不放宽。
    return _ask(db, instance, {"op": "node_packs", **({"content": graph} if graph is not None else {})},
                output_budget=runtime.CATALOG_OUTPUT_BYTES)


def node_pack_search(db: Session, user: User, query: str = "", node_types: list[str] | None = None,
                     instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    return _ask(db, instance, {"op": "node_pack_search", "query": query, "node_types": [str(one) for one in node_types or []][:30]})


def node_pack_info(db: Session, user: User, workspace_id: str, pack_id: str, instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    graph = _canvas_if_open(db, user, workspace_id, instance)
    return _ask(db, instance, {"op": "node_pack_info", "id": pack_id, **({"content": graph} if graph is not None else {})})


# --- 模型、节点包、试跑(ADR 0042 第三步:由智能体起头,都要点头) ----------------------------------
#
# 三件事的底层都早就有(`model_library` / `workflow_library`),这里只做智能体这一侧缺的那一层:
# 认哪台连接、开卡之前先把事实查清楚(链接是哪个文件、包是哪一版、画布上这张存没存过),批准之后照做,
# 并把智能体接下来该知道的交回去(任务号、装完重启、目录里现在是什么)。

#: 等装节点包那一次任务落终态:每拍多久、最多等多久。装完要重启,所以「任务还在跑」时绝不重启。
NODE_INSTALL_POLL_SECONDS = 0.2
NODE_INSTALL_TIMEOUT_SECONDS = 900
#: 节点包 id 的样子(和插件 `node_packs._PACK_ID` 同一条):注册表里的 id,不是一个地址、也不是 `user/repo`。
_PACK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
#: 注册表把「这一版能不能装」写在版本状态里(和插件同一个词)。
_ACTIVE, _BANNED = "NodeVersionStatusActive", "NodeVersionStatusBanned"
#: 最新一版被标记(Flagged)也是「不能装那一版」:有正常版本时插件把 `install_version` 指回它,那时才装。
_FLAGGED = "NodeVersionStatusFlagged"
_BANNED_PACKS = {"NodeStatusBanned", "NodeStatusDeleted"}


def bytes_text(size: Any) -> str:
    """字节数写给卡上看(`17.2 GB`)。说不清就是空串 —— 卡上不编一个大小。"""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def _plain(value: str, *, key: str) -> str:
    """文件名、目录名只能是一段(和 `model_library.start_download` 同一套判据,只是要在开卡之前就拒)。"""
    text = (value or "").strip()
    if not text or text in (".", "..") or any(mark in text for mark in ("/", "\\", ":", "\x00")) or \
            any(ord(char) < 32 for char in text):
        raise WorkbenchAgentError(key, name=text)
    return text


def model_search(db: Session, user: User, filename: str, folder: str = "", hash: str = "", hash_type: str = "",
                 instance_id: str = "") -> dict[str, Any]:
    """`comfy_model_search`:按文件名去模型站上找下载地址(插件搜,宿主规整)。只读,不改那台机器。"""
    from app.domain import model_library

    name = str(filename or "").strip()
    if not name:
        raise WorkbenchAgentError("workbenchErr_noModelName")
    instance = connection(db, user, instance_id)
    found = model_library.search_sources(db, instance, name, str(folder or "").strip(), str(hash or "").strip(),
                                         str(hash_type or "").strip())
    return {"instance_id": instance.id, "instance": instance.name, **found}


def model_resolve(db: Session, user: User, url: str, instance_id: str = "") -> dict[str, Any]:
    """`comfy_model_resolve`:一个链接指的是哪个文件、多大、建议放哪个目录、是不是已经有了。只读。"""
    from app.domain import model_library

    instance = connection(db, user, instance_id)
    return {"instance_id": instance.id, "instance": instance.name, "url": str(url or "").strip(),
            **model_library.resolve(db, instance, str(url or ""))}


def propose_download(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> None:
    """`comfy_model_download` 开卡之前(确认卡的 validate):链接要认得出是哪个文件、下到哪、多大、那台机器上还没有。

    认不出、文件名对不上的不开卡 —— 卡上写的必须是待会儿真要下的那一个文件。事实写回 `payload`,`summarize` 只说这些。
    """
    from app.domain import model_library

    instance = connection(db, user, str(payload.get("instance_id") or ""))
    url = str(payload.get("url") or "").strip()
    if not url:
        raise WorkbenchAgentError("workbenchErr_modelUrl")
    filename = _plain(str(payload.get("filename") or ""), key="modelLibErr_badFilename")
    folder = _plain(str(payload.get("folder") or ""), key="modelLibErr_badFolder")
    digest = str(payload.get("sha256") or "").strip().lower()
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise WorkbenchAgentError("modelLibErr_badHash", hash=str(payload.get("sha256") or "").strip()[:64])
    #: 认不出的链接、不是 http(s) 的链接由它按自己的话说(见 model_library.resolve)。
    found = model_library.resolve(db, instance, url)
    known = str(found.get("filename") or "")
    if known and known != filename:
        raise WorkbenchAgentError("workbenchErr_modelOtherFile", name=known, other=filename)
    if found.get("exists"):
        raise WorkbenchAgentError("workbenchErr_modelExists", name=filename, folder=folder)
    ensure_workspace_perm(db, user, workspace_id, "edit")
    payload.update({
        "instance_id": instance.id,
        "instance": instance.name,
        "url": url,
        "filename": filename,
        "folder": folder,
        "size": found.get("size"),
        "source": str(found.get("source") or ""),
        "sha256": digest,
    })


def start_model_download(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """批准之后:在那台机器上排一个下载任务(进度、取消、下完刷新目录都是任务那一侧的)。返回任务号。"""
    from app.domain import model_library

    instance = connection(db, user, str(payload.get("instance_id") or ""))
    job = model_library.start_download(
        db, user, instance, workspace_id=workspace_id, url=str(payload["url"]), folder=str(payload["folder"]),
        filename=str(payload["filename"]), sha256=str(payload.get("sha256") or ""),
    )
    return {
        "job_id": job.id,
        "kind": job.kind,
        "instance": instance.name,
        "filename": str(payload["filename"]),
        "folder": str(payload["folder"]),
        "size": payload.get("size"),
        "source": str(payload.get("source") or ""),
        "url": str(payload["url"]),
    }


def propose_node_install(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> None:
    """`comfy_node_pack_install` 开卡之前(确认卡的 validate):只装注册表里**现在**有正常版本的那一个包。

    git 地址、`Flagged` / `Banned`、没有正常版本的、已经装着同一版的、装着但停用的,都不开卡 —— 每一条都有确切原因
    (ADR 0042 §7)。版本、发布者、要不要动 PyTorch、和这台机器合不合写回 `payload`,卡上照这些说。
    """
    instance = connection(db, user, str(payload.get("instance_id") or ""))
    raw = str(payload.get("pack_id") or "").strip()
    if not raw:
        raise WorkbenchAgentError("workbenchErr_noPack")
    if not _PACK_ID.fullmatch(raw):
        #: git 地址、`user/repo` 之流:注册表里没有,也不该由智能体贴一个来源不明的仓库(ADR 0042 §7)。
        raise WorkbenchAgentError("workbenchErr_gitPack", pack=raw[:200])
    #: **现查**注册表:卡上写的必须是这一刻那一版的状态,不是搜索时记下的。
    info = node_pack_info(db, user, workspace_id, raw, instance.id)
    pack = str(info.get("id") or raw)
    newest = info.get("newest_version") if isinstance(info.get("newest_version"), dict) else {}
    newest_version, status = str(newest.get("version") or ""), str(newest.get("status") or "")
    version = str(info.get("install_version") or "")
    if str(info.get("pack_status") or "") in _BANNED_PACKS or status == _BANNED:
        raise WorkbenchAgentError("workbenchErr_packBanned", pack=pack, version=newest_version or version)
    if str(info.get("pack_status") or ""):
        #: 包本身在注册表里不是 Active(被标记、待审、已删):不管版本列表里写了什么,这里没有能装的那一版。
        raise WorkbenchAgentError("workbenchErr_packNoActive", pack=pack)
    if not version or (version == newest_version and (status != _ACTIVE or bool(newest.get("deprecated")))):
        #: 只有被标记 / 封禁 / 弃用的版本(插件把 `install_version` 退回到 latest):没有能装的那一版。
        raise WorkbenchAgentError("workbenchErr_packNoActive", pack=pack)
    wanted = str(payload.get("version") or "").strip()
    if wanted and wanted != version:
        #: 给的那一版不是注册表里现在正常的那个:不替它猜(装错版本那台 ComfyUI 可能起不来)。
        raise WorkbenchAgentError("workbenchErr_packVersion", pack=pack, version=wanted, active=version)
    installed = info.get("installed") if isinstance(info.get("installed"), dict) else {}
    if installed.get("enabled") is False:
        raise WorkbenchAgentError("workbenchErr_packDisabled", pack=pack)
    if str(installed.get("version") or "") == version:
        raise WorkbenchAgentError("workbenchErr_packInstalled", pack=pack, version=version)
    compat = info.get("compatibility") if isinstance(info.get("compatibility"), dict) else {}
    payload.update({
        "instance_id": instance.id,
        "instance": instance.name,
        "pack": pack,
        "name": str(info.get("name") or pack),
        "publisher": str(info.get("publisher") or ""),
        "version": version,
        "dependency_risk": str(info.get("dependency_risk") or ""),
        "torch_touching": [str(one) for one in info.get("torch_touching") or [] if isinstance(one, str)][:10],
        "mismatched": sorted(key for key in ("os", "accelerator", "comfyui")
                             if isinstance(compat.get(key), dict) and compat[key].get("ok") is False),
        "newest_version": newest_version,
        "newest_note": "flagged" if status == _FLAGGED else "deprecated" if bool(newest.get("deprecated")) else "",
        "installed_version": str(installed.get("version") or ""),
    })


def _wait_job(db: Session, job_id: str, *, timeout: float) -> Any:
    """等一个后台任务落终态。**等待期间把会话交还**(connection_handed_back):
    派发登记在 after_commit 上的线程要先有那一次提交才起得来;装节点包可能几分钟,攥着事务也就攥着写锁。"""
    from app.core.db import SessionLocal
    from app.db.models import Job
    from app.domain.jobs import TERMINAL_STATUSES
    from app.domain.workflows.executors.common import connection_handed_back

    with connection_handed_back(db):
        deadline = time.monotonic() + timeout
        while True:
            with SessionLocal() as fresh:
                job = fresh.get(Job, job_id)
                if job is None:
                    raise WorkbenchAgentError("workbenchErr_jobGone", job=job_id)
                if job.status in TERMINAL_STATUSES:
                    fresh.expunge(job)
                    return job
            if time.monotonic() >= deadline:
                raise WorkbenchAgentError("workbenchErr_jobTimeout", job=job_id, minutes=str(max(1, int(timeout // 60))))
            time.sleep(NODE_INSTALL_POLL_SECONDS)


def install_node_pack(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """批准之后:装那一个包 → **等它落终态** → 重启那台 ComfyUI → 读目录说现在装的是哪一版。

    装的那一下失败 / 被取消,就**不重启**(正在装的时候重启会把装了一半的包留在那台机器上);等太久也不重启,
    任务还在跑,回任务中心看它。
    """
    # 确认卡可能隔天才被批准:卡的 validate 只代表开卡那一刻。
    # 执行前必须重查注册表,否则已被 Flagged/Banned 的包也会装上机器。
    approved = dict(payload)
    propose_node_install(db, user, workspace_id, approved)
    pack, version = str(approved["pack"]), str(approved["version"])
    if pack != str(payload["pack"]) or version != str(payload.get("version") or ""):
        raise WorkbenchAgentError(
            "workbenchErr_packVersion",
            pack=pack,
            version=f"{payload.get('version') or ''} → {version}",
        )

    from app.domain import workflow_library
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.runtime import PluginRuntimeError
    from app.domain.workflow_library import WorkflowLibraryError

    instance = connection(db, user, str(approved.get("instance_id") or ""))
    job = workflow_library.start_node_install(db, user, instance, workspace_id=workspace_id, packs=[pack],
                                              versions={pack: version} if version else None)
    job_id = job.id
    final = _wait_job(db, job_id, timeout=NODE_INSTALL_TIMEOUT_SECONDS)
    if final.status != "succeeded":
        #: 失败原因整句带着(任务那一侧已经收过上限):按位置裁掉的往往正是写着原因的那一段。
        raise WorkbenchAgentError("workbenchErr_nodeInstallFailed", name=pack,
                                  detail=_job_error(db, user, job_id) or str(final.message or ""))
    result = final.result if isinstance(final.result, dict) else {}
    installed = [str(one) for one in result.get("installed") or [] if isinstance(one, str)] or [pack]
    #: 装完才重启(插件/Manager 那一侧也一样要求):新装的节点包这时才加载,目录这时才重拉。
    #: 重启没成有两种说法:插件当场报错(没装 Manager、Manager 不让重启)和它回来了 `back: false` —— 对用户是同一件事,
    #: 而**包已经装上了**,那句必须说出来,不能让卡只写着「失败」。
    try:
        rebooted = workflow_library.reboot(db, instance)
    except (WorkflowLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise WorkbenchAgentError("workbenchErr_rebootFailed", name=instance.name, pack=pack, detail=str(exc)) from exc
    if not rebooted.get("back"):
        raise WorkbenchAgentError("workbenchErr_rebootFailed", name=instance.name, pack=pack,
                                  detail=render_message("workbenchErr_rebootNoAnswer", get_current_locale(), {}))
    #: 重启之后目录里到底有没有它、是哪一版 —— 不拿 Manager 的「装好了」当结论(它也可能装进了没被加载的目录)。
    catalog = _ask(db, instance, {"op": "node_packs"}, output_budget=runtime.CATALOG_OUTPUT_BYTES)
    loaded = next((str(one.get("version") or "") for one in catalog.get("packs") or []
                   if isinstance(one, dict) and str(one.get("id") or "").lower() == pack.lower()), "")
    if not loaded:
        raise WorkbenchAgentError("workbenchErr_packNotLoaded", pack=pack, name=instance.name)
    return {"pack": pack, "version": version, "installed": installed, "job_id": job_id,
            "restarted": True, "catalog_version": loaded}


def propose_canvas_run(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> None:
    """`comfy_canvas_run` 开卡之前(确认卡的 validate):画布上这张**存过**才跑(运行要一张这个连接下的生成模型);
    从没存过的新标签页先让用户存(Ctrl+S)。卡上写开的是哪一张。"""
    instance = connection(db, user, str(payload.get("instance_id") or ""))
    info = _opened(read_graph(db, user, workspace_id, instance).get("info"))
    if info["temporary"] or not info["path"]:
        raise WorkbenchAgentError("workbenchErr_canvasUnsaved", name=info["name"])
    payload.update({"instance_id": instance.id, "instance": instance.name, "workflow": info})
    node_id = str(payload.get("node_id") or "").strip()
    if node_id:
        payload["node_id"] = node_id


def _run_controls(db: Session, user: User, workspace_id: str, instance: PluginInstance, phase: str) -> None:
    """「运行」前后照前端自己的「生成后怎样」换种子(和界面同一条)。桥做不了(主进程是旧的、这一下没排上)不拦着跑 ——
    紧跟着的 export 会把「工作台没开着」说清楚。"""
    try:
        _workbench(db, user, workspace_id, instance, {"op": "runControls", "phase": phase})
    except WorkbenchAgentError:
        return


def run_canvas(db: Session, user: User, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """批准之后:跑画布上现在这张(含没存的改动,见 `workflow_library.run_canvas`)。

    开卡之后画布上换了一张就不跑(跑的是用户没看过的那张);导出前后各让桥走一遍前端自己的「生成后怎样」。
    """
    from app.domain import workflow_library

    instance = connection(db, user, str(payload.get("instance_id") or ""))
    proposed = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
    info = _opened(read_graph(db, user, workspace_id, instance).get("info"))
    if info["temporary"] or not info["path"]:
        raise WorkbenchAgentError("workbenchErr_canvasUnsaved", name=info["name"])
    if proposed.get("key") and info["key"] != str(proposed.get("key")):
        raise WorkbenchAgentError("workbenchErr_runOtherTab",
                                  name=str(proposed.get("name") or proposed.get("key") or ""))
    _run_controls(db, user, workspace_id, instance, "before")
    answer = _workbench(db, user, workspace_id, instance, {"op": "export"})
    exported = answer.get("export") if isinstance(answer.get("export"), dict) else None
    if exported is None or not isinstance(exported.get("prompt"), dict) or not isinstance(exported.get("workflow"), dict):
        raise WorkbenchAgentError("workbenchErr_bridge", detail="export")
    #: 重读和导出之间用户在标签栏里换了一张:导出的那份带着是**哪一张**(桥的 `at.key`)。不是卡上这一张就不跑 ——
    #: 跑的是用户没看过的那张图,而这条卡上写的是另一张。
    at = exported.get("at") if isinstance(exported.get("at"), dict) else {}
    exported_key = str(at.get("key") or "")
    if exported_key and proposed.get("key") and exported_key != str(proposed["key"]):
        raise WorkbenchAgentError("workbenchErr_runOtherTab",
                                  name=str(proposed.get("name") or proposed.get("key") or ""))
    node_id = str(payload.get("node_id") or "").strip()
    if node_id and node_id not in exported["prompt"]:
        raise WorkbenchAgentError("workbenchErr_runNodeMissing", node=node_id)
    created, job = workflow_library.run_canvas(
        db, user, instance, workspace_id=workspace_id, path=info["path"], prompt=exported["prompt"],
        workflow=exported["workflow"], client_id=str(exported.get("clientId") or ""),
        targets=[node_id] if node_id else None,
    )
    #: 生成任务这一笔先落库:跑它的线程要读到这一行才起得来;而「运行」之后那一下是**另一个会话**里的工作台动作
    #: (browser 那条路自己开会话),攥着这笔写事务排它就会等到写锁超时(实测 31 秒,SQlite)。
    from app.domain.workflows.executors.common import connection_handed_back
    db.flush()
    with connection_handed_back(db):
        pass
    _run_controls(db, user, workspace_id, instance, "after")
    return {"job_id": job.id, "generation_id": created.id, "workflow": info,
            "kind": str(getattr(created, "kind", "") or "")}


__all__ = [
    "NODE_INSTALL_TIMEOUT_SECONDS",
    "WorkbenchAgentError",
    "apply_edit",
    "bytes_text",
    "canvas",
    "check",
    "connection",
    "install_node_pack",
    "locate",
    "model_resolve",
    "model_search",
    "node_pack_info",
    "node_pack_search",
    "node_packs",
    "node_types",
    "open_new",
    "plan_edit",
    "propose_canvas_run",
    "propose_download",
    "propose_edit",
    "propose_node_install",
    "read_graph",
    "run_canvas",
    "start_model_download",
    "template",
    "templates",
]
