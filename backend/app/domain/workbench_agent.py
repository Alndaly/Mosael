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
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, get_current_locale, render_message
from app.db.models import PluginInstance, User
from app.domain import browser
from app.domain.permissions import ensure_workspace_access
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.manifest import WORKFLOW_LIBRARY

#: 问插件的上限:取模板要把几张模板的整图取一遍、问下载地址多大;注册表在公网上。
PLUGIN_TIMEOUT_SECONDS = 120
#: 画布上节点的写法:根图上的编号,子图里的从根图往里走的编号(冒号隔开)。
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


def _ask(db: Session, instance: PluginInstance, payload: dict[str, Any]) -> dict[str, Any]:
    return tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, payload, timeout=PLUGIN_TIMEOUT_SECONDS, record=False)


# --- 画布(经主进程的那条路) ----------------------------------------------------------------

#: 桥回「这一页没有工作台」的几种原因:会话不在(视图收起了)、桥没注入、视图停在别的站点、前端还没起来。
_NOT_OPEN = {"closed", "missing", "elsewhere", "notReady"}
#: 动作排不上 / 执行器不在了:桌面端没开、网页版 —— 对用户来说都是「工作台没开着」。
_NO_EXECUTOR = {"browserErr_actionNotClaimed", "browserErr_actionQueueTimeout", "browserErr_executorLost"}


def _workbench(db: Session, user: User, workspace_id: str, instance: PluginInstance, call: dict[str, Any]) -> dict[str, Any]:
    """在这个连接开着的工作台上做一件事,回桥的回答(`ok: true` 的那种)。"""
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
_FINDING_KEYS = ("ref", "type", "severity", "kind", "input", "cause", "fix")
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
    撤销)。改完再读一遍、诊断一遍,说修好了几个、多出来几个。"""
    instance = connection(db, user, str(payload.get("instance_id") or ""))
    proposed = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
    graph, plan = plan_edit(db, user, workspace_id, instance, payload.get("ops"))
    now = _opened(graph.get("info"))
    if now["key"] != str(proposed.get("key") or ""):
        raise WorkbenchAgentError("workbenchErr_editOtherTab", name=str(proposed.get("name") or proposed.get("key") or ""))
    if (plan.get("changes") or []) != (payload.get("changes") or []):
        raise WorkbenchAgentError("workbenchErr_editStale", name=now["name"])
    answer = _workbench(db, user, workspace_id, instance, {"op": "applyOps", "ops": plan["ops"]})
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
             ops: list[Any] | None = None, instance_id: str = "") -> dict[str, Any]:
    """`comfy_canvas_new`:在新标签页开一张整图 —— 一张官方模板(照这台机器改好的)、模板上再改一批、从空白搭一批;或者打开存着的
    那一张(`path`)。不动开着的那几张,**不存盘**(存不存、存在哪是用户的事)。开好之后读一遍、诊断一遍。"""
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
    if path:
        answer = _workbench(db, user, workspace_id, instance, {"op": "openWorkflow", "path": path})
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
            "workbenchNewWorkflowName", get_current_locale(), {})}
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
    return _ask(db, instance, {"op": "node_packs", **({"content": graph} if graph is not None else {})})


def node_pack_search(db: Session, user: User, query: str = "", node_types: list[str] | None = None,
                     instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    return _ask(db, instance, {"op": "node_pack_search", "query": query, "node_types": [str(one) for one in node_types or []][:30]})


def node_pack_info(db: Session, user: User, workspace_id: str, pack_id: str, instance_id: str = "") -> dict[str, Any]:
    instance = connection(db, user, instance_id)
    graph = _canvas_if_open(db, user, workspace_id, instance)
    return _ask(db, instance, {"op": "node_pack_info", "id": pack_id, **({"content": graph} if graph is not None else {})})


__all__ = [
    "WorkbenchAgentError",
    "apply_edit",
    "canvas",
    "check",
    "connection",
    "locate",
    "node_pack_info",
    "node_pack_search",
    "node_packs",
    "node_types",
    "open_new",
    "plan_edit",
    "propose_edit",
    "read_graph",
    "template",
    "templates",
]
