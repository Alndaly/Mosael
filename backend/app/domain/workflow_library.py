"""工作流库(ADR 0035):认领 `workflow_library` 的连接上存着哪些工作流 —— 宿主这一侧。

插件回答「这台服务器上存着哪些工作流、每张长什么样、缺什么」,替宿主改那台机器上的工作流文件(复制、改名、挪进 / 挪出
回收目录)。宿主做的是插件做不了、也不该做的:

- **规整**:插件报的每一条都过一遍(没有路径的丢掉、长文本截断、图摘要限量),界面拿到的形状只有一种;
- **它在 Mosael 里的样子**:这张工作流是不是这个连接下的一个生成模型(用它生成要它)、这个工作区里最近一次用它生成的
  产出、这个工作区里哪些工作流节点 / 画板格子选的是它(引用表,见 db/references 的 `generation_model`);
- **路径先查一遍**:只认 `workflows/` 里的相对路径(`.json`,不带 `..`、反斜杠、控制字符和 Windows 不收的字符),
  回收目录里的只认插件报过的那种形状 —— 不交给插件猜;
- **改完马上刷新**:这个连接的生成目录和工具清单重拉一遍(`host_capabilities.notify(refresh=True)`),不等一分钟的指纹;
- **在哪里编辑**:插件可以报一个编辑器(种类 + 网页地址,「在编辑器里打开」用),这里只认简单的种类名和不带用户名密码
  的 http(s) 地址,不对就当没有。

**不覆盖**:复制、改名、恢复撞了名,插件回 `conflict` 和一个建议名,这里翻成 409(带着建议名),界面要求换名。

**导入**(ADR 0035 §5):要导入的东西只给一样(一段文字 / 一个文件 / 一个链接),太大的不交;插件认出来、换成界面格式,
这里规整预览(和列出来的每一张同一套);存进去和别的写操作同一套,原文以 JSON 字符串交给插件 —— 调用记录里只留截断的
一段,不把整张图存进记录。

**补齐缺的节点**:装节点包是一个后台任务(`node_install`,经插件交给 ComfyUI-Manager,进度照插件说的),装完要重启
ComfyUI 才加载;重启经插件(等它停下再起来),回来以后这个连接的目录重拉一遍。包名先在这里过一遍(几个、多长、没有控制字符)。

**应用表单**(ADR 0038 §2):作者从一张工作流全部能填的项里挑几项、起名、排序、收窄可选值,标哪个输出节点是结果,存进
那张工作流自己的 JSON。读(`app_form`)给编辑器全部能填的项、文件里的标记和读到时的改动时间;写(`annotate`)是 Mosael
**唯一覆盖写一张已有工作流**的地方:只改 `mosael` 那几处标记,带着读到时的改动时间去 —— 那台机器上的文件在这之间被改过,
插件不写、回 stale,这里翻成 409(`WorkflowStale`)。形状先在这里过一遍(根图上的节点号、几项、多长),界面每次都先确认。

**这里不认识 ComfyUI**:任何认领 `workflow_library` 的连接,插件页上都有「工作流库」。列表不存库,每次现问插件。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, fragment, pick_text
from app.core.unit_of_work import unit_of_work
from app.db.models import Board, GenerationJob, Job, PluginInstance, ProviderProfile, User, Workflow
from app.db.references import generation_model_key
from app.domain import capabilities
from app.domain.jobs import create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.plugins import generation as plugin_generation
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import WORKFLOW_LIBRARY
from app.domain.plugins.runtime import PluginRuntimeError, StreamHooks
from app.domain.plugins.tools import MAX_GENERATION_TIMEOUT_SECONDS
from app.domain.providers import models as provider_models
from app.domain.references import referrers

#: 列一遍最多等多久:要取每张工作流、转一遍、再列一遍模型目录。
LIBRARY_TIMEOUT_SECONDS = 600
#: 取一张、存一张、挪一张:一两个请求的事。
QUICK_TIMEOUT_SECONDS = 120
#: 重启:插件等 ComfyUI 停下再起来,最多 4 分钟,再留一点余量。
REBOOT_TIMEOUT_SECONDS = 300
#: 装节点包的任务种类(见 job_catalog);工作流库列这个连接最近几次。
NODE_INSTALL_KIND = "node_install"
RECENT_INSTALLS = 5
_MAX_PACKS = 10

_MAX_WORKFLOWS = 2000
_MAX_LIST = 200
_MAX_GRAPH_NODES = 400
_MAX_GRAPH_LINKS = 1200
_MAX_GRAPH_GROUPS = 60
_MAX_USES = 50
_ROLES = {"input", "model", "sampler", "text", "output", "note", "missing", "other"}
#: Windows 上文件名里不能有的字符(那台 ComfyUI 可能在 Windows 上):路径段里一个都不收。
_BAD_SEGMENT = re.compile(r'[\x00-\x1f<>:"|?*\\]')
#: 回收目录里的一张:`.mosael-trash/workflows/<时刻>/<原来的相对路径>`(ADR 0035 §3)。
_TRASH_PATH = re.compile(r"^\.mosael-trash/workflows/\d{8}-\d{6}(-\d+)?/(?P<original>.+)$")
#: 要导入的东西最多多长(字符):文件是 base64,30 MB 的文件约 40 M 个字符。
MAX_IMPORT_CHARS = 40 * 1024 * 1024
_IMPORT_FORMATS = {"ui", "api"}
_IMPORT_SOURCES = {"json", "png", "webp", "zip", "url"}
#: 编辑器的种类名(界面按它决定怎么打开那一张,如 `comfyui`)。
_EDITOR_KIND = re.compile(r"[a-z][a-z0-9-]{0,39}")


class WorkflowLibraryError(LocalizedError, ValueError):
    """工作流库这一侧说不行(这个连接不提供工作流库、路径不对)。带文案 key(`workflowLibErr_*`)。"""


class WorkflowStale(WorkflowLibraryError):
    """要改的那张在那台服务器上被改过了(改动时间和读到时的对不上):应用表单没存,重新打开再改。"""

    def __init__(self, path: str, modified: float | None) -> None:
        super().__init__("workflowLibErr_stale", path=path)
        self.path = path
        self.modified = modified


class WorkflowConflict(WorkflowLibraryError):
    """撞名了:那台服务器上已经有这个名字。`suggestion` 是一个不撞名的建议。"""

    def __init__(self, path: str, suggestion: str) -> None:
        super().__init__("workflowLibErr_exists", path=path)
        self.path = path
        self.suggestion = suggestion


def _require(db: Session, instance: PluginInstance) -> None:
    if WORKFLOW_LIBRARY not in inst.manifest_for(db, instance).provides:
        raise WorkflowLibraryError("workflowLibErr_notProvided", name=instance.name)


def _text(value: Any, limit: int = 500) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def workflow_path(value: str) -> str:
    """`workflows/` 里的一张:相对路径、`.json` 结尾、`/` 分段,每段不空、不是 `.` / `..`、不以点开头(那是隐藏的)、
    没有 Windows 不收的字符。不合格就拒,不交给插件。"""
    text = (value or "").strip()
    segments = text.split("/")
    if not text.lower().endswith(".json") or len(text) > 500 or any(
        not one or one in (".", "..") or one.startswith(".") or one != one.strip() or _BAD_SEGMENT.search(one)
        for one in segments
    ):
        raise WorkflowLibraryError("workflowLibErr_badPath", path=text)
    return text


def trash_path(value: str) -> str:
    text = (value or "").strip()
    found = _TRASH_PATH.match(text)
    if found is None or ".." in text.split("/"):
        raise WorkflowLibraryError("workflowLibErr_badPath", path=text)
    workflow_path(found.group("original"))
    return text


# --- 列出来 ------------------------------------------------------------------

def _graph(raw: Any) -> dict[str, Any]:
    """画缩略图用的图摘要:节点(位置、大小、种类、是否旁路、标题)、连线(节点下标)、分组。限量,坏条目丢掉。"""
    raw = raw if isinstance(raw, dict) else {}
    nodes: list[dict[str, Any]] = []
    for one in raw.get("nodes") or []:
        if not isinstance(one, dict) or len(nodes) >= _MAX_GRAPH_NODES:
            continue
        x, y, w, h = (_number(one.get(key)) for key in ("x", "y", "w", "h"))
        if x is None or y is None:
            continue
        role = _text(one.get("role"), 20)
        nodes.append({
            "x": x, "y": y, "w": max(w or 0.0, 20.0), "h": max(h or 0.0, 20.0),
            "role": role if role in _ROLES else "other",
            "muted": one.get("muted") is True,
            "title": _text(one.get("title"), 120),
        })
    links: list[list[int]] = []
    for one in raw.get("links") or []:
        if len(links) >= _MAX_GRAPH_LINKS:
            break
        if isinstance(one, list) and len(one) >= 2 and all(isinstance(i, int) and not isinstance(i, bool) for i in one[:2]) \
                and 0 <= one[0] < len(nodes) and 0 <= one[1] < len(nodes):
            links.append([one[0], one[1]])
    groups: list[dict[str, Any]] = []
    for one in raw.get("groups") or []:
        if not isinstance(one, dict) or len(groups) >= _MAX_GRAPH_GROUPS:
            continue
        x, y, w, h = (_number(one.get(key)) for key in ("x", "y", "w", "h"))
        if None in (x, y, w, h):
            continue
        color = _text(one.get("color"), 20)
        groups.append({"x": x, "y": y, "w": w, "h": h, "title": _text(one.get("title"), 120),
                       "color": color if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color) else ""})
    return {
        "nodes": nodes,
        "links": links,
        "groups": groups,
        "auto_layout": raw.get("auto_layout") is True,
        "truncated": raw.get("truncated") is True or len(raw.get("nodes") or []) > _MAX_GRAPH_NODES,
    }


def _items(value: Any, keys: dict[str, int]) -> list[dict[str, str]]:
    """一串 `{键: 字}`:只留认得的键,截断;一个都没有的条目丢掉。"""
    out: list[dict[str, str]] = []
    for one in value if isinstance(value, list) else []:
        if isinstance(one, dict):
            item = {key: _text(one.get(key), limit) for key, limit in keys.items()}
            if any(item.values()):
                out.append(item)
    return out[:_MAX_LIST]


def _missing_nodes(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for one in value if isinstance(value, list) else []:
        if not isinstance(one, dict) or not _text(one.get("type"), 200):
            continue
        packs = [
            {"id": _text(pack.get("id"), 300), "title": _text(pack.get("title"), 200) or _text(pack.get("id"), 300),
             "installed": pack.get("installed") is True}
            for pack in one.get("packs") or [] if isinstance(pack, dict) and _text(pack.get("id"), 300)
        ][:10]
        out.append({"type": _text(one.get("type"), 200), "count": int(_number(one.get("count")) or 1), "packs": packs})
    return out[:_MAX_LIST]


def _workflow(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        path = workflow_path(_text(raw.get("path"), 500))
    except WorkflowLibraryError:
        return None
    size = _number(raw.get("size"))
    return {
        "path": path,
        "label": path[:-5].rsplit("/", 1)[-1],
        "folder": path.rsplit("/", 1)[0] if "/" in path else "",
        "size": int(size) if size is not None else None,
        "modified": _number(raw.get("modified")),
        "kind": _text(raw.get("kind"), 20),
        "problem": _text(raw.get("problem"), 2000),
        "node_count": int(_number(raw.get("node_count")) or 0),
        "graph": _graph(raw.get("graph")),
        "inputs": _items(raw.get("inputs"), {"node": 40, "title": 200, "media": 20, "role": 40}),
        "parameters": _items(raw.get("parameters"), {"key": 200, "title": 200, "type": 20}),
        "outputs": _items(raw.get("outputs"), {"node": 40, "title": 200, "media": 20}),
        "models": [
            {"folder": item["folder"], "name": item["name"], "present": bool(one.get("present"))}
            for one in raw.get("models") or [] if isinstance(one, dict)
            for item in [{"folder": _text(one.get("folder"), 200), "name": _text(one.get("name"), 1000)}]
            if item["folder"] and item["name"]
        ][:_MAX_LIST],
        "missing_nodes": _missing_nodes(raw.get("missing_nodes")),
        "missing_models": [
            one for one in _items(raw.get("missing_models"), {"folder": 200, "name": 1000, "url": 4000})
            if one["folder"] and one["name"]
        ],
        "app": _app_summary(raw.get("app")),
    }


#: 应用表单(ADR 0038):有没有、版本认不认。
_APP_STATUSES = {"none", "ok", "unsupported"}
#: 一张表最多几项、一项最多几个可选值、最多标几个结果;名字、标题、说明最长多少字(和插件那一侧同一套数)。
MAX_APP_ITEMS = 200
MAX_APP_CHOICES = 1000
MAX_APP_RESULTS = 64
_MAX_APP_LABEL = 120
_MAX_APP_DESCRIPTION = 1000
_GRAPH_ITEMS = {"seed", "size", "runs"}
#: 根图上的节点号(子图里面的节点 —— `12:5` 这种 —— 这一版不能放进应用表单)。
_ROOT_NODE = re.compile(r"\d{1,9}")
#: 一格输入的名字:不收控制字符,不太长。
_INPUT_NAME = re.compile(r"[^\x00-\x1f]{1,200}")


def _app_summary(raw: Any) -> dict[str, Any] | None:
    """插件说的这张工作流的应用表单(有没有、版本、标题、每一项和对不上的原因、标成结果的节点),规整一遍。没说就是 None。"""
    if not isinstance(raw, dict):
        return None
    status = _text(raw.get("status"), 20)
    items: list[dict[str, Any]] = []
    for one in raw.get("items") or []:
        if not isinstance(one, dict) or len(items) >= MAX_APP_ITEMS:
            continue
        node, name = _text(one.get("node"), 20), _text(one.get("input"), 200)
        if not name or (node and not _ROOT_NODE.fullmatch(node)):
            continue
        item: dict[str, Any] = {"key": f"{node}.{name}" if node else name, "node": node, "input": name,
                                "label": _text(one.get("label"), _MAX_APP_LABEL), "main": one.get("main") is True,
                                "title": _text(one.get("title"), 200), "problem": _text(one.get("problem"), 500)}
        if isinstance(one.get("choices"), list):
            item["choices"] = [str(choice)[:1000] for choice in one["choices"][:MAX_APP_CHOICES]
                               if isinstance(choice, (str, int, float)) and not isinstance(choice, bool)]
        items.append(item)
    version = raw.get("version")
    return {
        "status": status if status in _APP_STATUSES else "none",
        "version": str(version)[:20] if isinstance(version, (int, float, str)) and not isinstance(version, bool) else "",
        "app": raw.get("app") is True,
        "title": _text(raw.get("title"), _MAX_APP_LABEL),
        "description": _text(raw.get("description"), _MAX_APP_DESCRIPTION),
        "items": items,
        "results": [_text(one, 20) for one in raw.get("results") or []
                    if isinstance(one, str) and _ROOT_NODE.fullmatch(one)][:MAX_APP_RESULTS],
        "invalid": int(_number(raw.get("invalid")) or 0),
        "fields": int(_number(raw.get("fields")) or 0),
    }


def _trash(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for one in value if isinstance(value, list) else []:
        if not isinstance(one, dict):
            continue
        try:
            path = trash_path(_text(one.get("path"), 600))
        except WorkflowLibraryError:
            continue
        original = _TRASH_PATH.match(path).group("original")  # type: ignore[union-attr]
        out.append({"path": path, "original": original, "label": original[:-5].rsplit("/", 1)[-1],
                    "deleted_at": _number(one.get("deleted_at"))})
    return out[:_MAX_WORKFLOWS]


def _profile(db: Session, instance: PluginInstance) -> ProviderProfile | None:
    return db.scalar(select(ProviderProfile).where(ProviderProfile.plugin_instance_id == instance.id))


def _in_mosael(db: Session, instance: PluginInstance, workspace_id: str, workflows: list[dict[str, Any]]) -> None:
    """每张工作流在 Mosael 里的样子:是不是这个连接下的生成模型、这个工作区里最近一次用它生成的产出、谁在用它。"""
    profile = _profile(db, instance)
    rows = {row.model_id: row for row in provider_models.list_models(db, profile.id)} if profile is not None else {}
    for flow in workflows:
        flow["generation"] = None
        flow["last_output"] = None
        flow["used_by"] = []
        row = rows.get(flow["path"])
        if profile is None or row is None:
            continue
        kinds = [kind for kind in row.capability_ids or [] if kind in ("image", "video", "audio")]
        if row.enabled and kinds:
            flow["generation"] = {"provider_profile_id": profile.id, "kind": kinds[0], "model": row.model_id}
        if not workspace_id:
            continue
        last = db.scalar(
            select(GenerationJob)
            .where(GenerationJob.workspace_id == workspace_id, GenerationJob.provider_profile_id == profile.id,
                   GenerationJob.model == row.model_id, GenerationJob.result_asset_id.is_not(None))
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        if last is not None:
            flow["last_output"] = {"asset_id": last.result_asset_id, "created_at": last.created_at}
        key = generation_model_key(profile.id, row.model_id)
        uses: list[dict[str, str]] = [
            {"kind": "workflow", "id": workflow.id, "name": workflow.name}
            for workflow in db.scalars(select(Workflow).where(
                Workflow.workspace_id == workspace_id, Workflow.id.in_(referrers("generation_model", key, "workflow"))))
        ]
        uses += [
            {"kind": "board", "id": board.id, "name": board.name}
            for board in db.scalars(select(Board).where(
                Board.workspace_id == workspace_id, Board.id.in_(referrers("generation_model", key, "board"))))
        ]
        flow["used_by"] = uses[:_MAX_USES]


def _editor(raw: Any) -> dict[str, str] | None:
    """插件说这些工作流在哪里编辑。地址会在桌面版的内嵌浏览器 / 网页版的新标签页里打开:只认 http(s)、有主机名、
    不带「用户名:密码@」(凭据不该出现在地址里,见插件的连接配置)。"""
    if not isinstance(raw, dict):
        return None
    kind, url = raw.get("kind"), raw.get("url")
    if not isinstance(kind, str) or not _EDITOR_KIND.fullmatch(kind) or not isinstance(url, str) or len(url) > 500:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        return None
    return {"kind": kind, "url": url.strip()}


def library(db: Session, user: User, instance: PluginInstance, *, workspace_id: str = "") -> dict[str, Any]:
    """现问插件:这个连接上存着的全部工作流(连同图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺什么)、不是工作流的
    文件、回收目录里的;再补上它们在 Mosael 里的样子(只看 `workspace_id` 这个工作区,`user` 得进得去)。"""
    if workspace_id:
        ensure_workspace_access(db, user, workspace_id)
    _require(db, instance)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "workflows"},
                               timeout=LIBRARY_TIMEOUT_SECONDS, record=False)
    workflows = [one for one in (_workflow(raw) for raw in (output.get("workflows") or [])[:_MAX_WORKFLOWS]) if one]
    _in_mosael(db, instance, workspace_id, workflows)
    manager = output.get("manager") if isinstance(output.get("manager"), dict) else {}
    return {
        "workflows": workflows,
        "others": [one for one in _items(output.get("others"), {"path": 500, "reason": 2000}) if one["path"]],
        "trash": _trash(output.get("trash")),
        "manager": {"version": _text(manager.get("version"), 40)},
        "editor": _editor(output.get("editor")),
        "installs": node_installs(db, instance),
    }


# --- 一张的原文 ----------------------------------------------------------------

def content(db: Session, instance: PluginInstance, path: str) -> dict[str, Any]:
    """一张工作流的原文(导出成 JSON 用)。"""
    _require(db, instance)
    path = workflow_path(path)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "workflow", "path": path},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    graph = output.get("content")
    if not isinstance(graph, dict):
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    return {"path": path, "content": graph}


# --- 改那台机器上的文件 ---------------------------------------------------------

def _write(db: Session, instance: PluginInstance, request: dict[str, Any], *, wanted: str) -> str:
    """一次写操作:交给插件,撞名翻成 WorkflowConflict;成了就让这个连接的目录重拉一遍。回改完之后的路径。"""
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, request, timeout=QUICK_TIMEOUT_SECONDS)
    if output.get("conflict") is True:
        suggestion = _text(output.get("suggestion"), 500)
        raise WorkflowConflict(wanted, suggestion if suggestion.lower().endswith(".json") else "")
    path = _text(output.get("path"), 600)
    if not path:
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    # 生成选项、工具清单里的那张跟着变(新的一张、换了名字的、删掉的),不等那一分钟的指纹
    host_capabilities.notify(db, instance, refresh=True)
    return path


def copy(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """复制一张:存成 `new_path`(已有就撞名,不覆盖)。插件给副本换一个新的图 id —— 两张同 id 的图,工具名会撞。"""
    _require(db, instance)
    path, new_path = workflow_path(path), workflow_path(new_path)
    return {"path": _write(db, instance, {"op": "copy_workflow", "path": path, "new_path": new_path}, wanted=new_path)}


def rename(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """改名 / 挪目录(已有就撞名,不覆盖)。"""
    _require(db, instance)
    path, new_path = workflow_path(path), workflow_path(new_path)
    if path == new_path:
        return {"path": path}
    return {"path": _write(db, instance, {"op": "rename_workflow", "path": path, "new_path": new_path}, wanted=new_path)}


def trash(db: Session, instance: PluginInstance, path: str) -> dict[str, str]:
    """「删除」:挪进回收目录(ADR 0035 §3),不硬删。回回收目录里的路径。"""
    _require(db, instance)
    path = workflow_path(path)
    return {"path": _write(db, instance, {"op": "trash_workflow", "path": path}, wanted=path)}


def restore(db: Session, instance: PluginInstance, path: str, new_path: str = "") -> dict[str, str]:
    """从回收目录挪回去:默认回原处,原处被占了就撞名(界面要求换名,再带着 `new_path` 来)。"""
    _require(db, instance)
    path = trash_path(path)
    target = workflow_path(new_path) if new_path else _TRASH_PATH.match(path).group("original")  # type: ignore[union-attr]
    return {"path": _write(db, instance, {"op": "restore_workflow", "path": path, "new_path": target}, wanted=target)}


# --- 应用表单(ADR 0038 §2)----------------------------------------------------------

_ITEM_KINDS = {"text", "media", "model", "number", "choice", "toggle", "seed", "size", "runs"}
#: 编辑器一次最多列多少项(一张工作流 115 项是见过的最多的)。
_MAX_APP_FOUND = 1000


def _app_item(raw: Any, text: Any) -> dict[str, Any] | None:
    """编辑器要的一项能填的项:锚点、种类、名字(按看的人的语言挑好)、节点是谁、常用与否、JSON Schema 片段
    (和生成目录同一套规整,见 plugins/generation.parameters —— 预览和真的表单是同一个形状)。"""
    if not isinstance(raw, dict):
        return None
    node, name, kind = _text(raw.get("node"), 40), _text(raw.get("input"), 200), _text(raw.get("kind"), 20)
    if not name or kind not in _ITEM_KINDS:
        return None
    key = f"{node}.{name}" if node else name
    title = raw.get("title")
    item: dict[str, Any] = {
        "key": key, "node": node, "input": name, "kind": kind,
        "title": _text(pick_text(title) if isinstance(title, dict) else title, 200) or key,
        "node_title": _text(raw.get("node_title"), 200),
        "class_type": _text(raw.get("class_type"), 200),
        "common": raw.get("common") is True,
        "role": _text(raw.get("role"), 40),
        "media": _text(raw.get("media"), 20),
        "folder": _text(raw.get("folder"), 64),
        # 子图里面的节点(`12:5`)这一版不能放进应用表单(ADR 0038「这一版不做」),照样列出来、标着
        "exposable": not node or bool(_ROOT_NODE.fullmatch(node)),
    }
    if isinstance(raw.get("schema"), dict):
        schema = plugin_generation.parameters({key: raw["schema"]}, text).get(key)
        if schema is not None:
            item["spec"] = {field: pick_text(value) if isinstance(value, dict) and field in ("title", "description")
                              else value for field, value in schema.items()}
    return item


def app_form(db: Session, instance: PluginInstance, path: str) -> dict[str, Any]:
    """一张工作流的应用表单,给编辑器(工作流库详情里的「应用」):这张图全部能填的项、交回结果的输出节点、文件里的标记
    (对不上的带着原因)、读到时的改动时间(存的时候带回来)。"""
    _require(db, instance)
    path = workflow_path(path)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "app", "path": path},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    if not isinstance(output.get("items"), list):
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    text = inst.manifest_for(db, instance).text
    items = [one for one in (_app_item(raw, text) for raw in output["items"][:_MAX_APP_FOUND]) if one]
    return {
        "path": path,
        "modified": _number(output.get("modified")),
        "kind": _text(output.get("kind"), 20),
        "editable": output.get("editable") is True,
        "items": items,
        "outputs": _items(output.get("outputs"), {"node": 40, "title": 200, "class_type": 200, "media": 20}),
        "app": _app_summary(output.get("app")) or _app_summary({"status": "none"}),
    }


def _too_big() -> WorkflowLibraryError:
    return WorkflowLibraryError("workflowLibErr_appTooBig", items=str(MAX_APP_ITEMS), choices=str(MAX_APP_CHOICES),
                                results=str(MAX_APP_RESULTS))


def _form_payload(app: dict[str, Any] | None, results: list[str]) -> dict[str, Any] | None:
    """要写进去的应用表单先在这里过一遍:几项、每项是根图上的节点(或图级的种子 / 尺寸 / 跑几遍)、名字多长、可选值几个。"""
    if len(results) > MAX_APP_RESULTS:
        raise _too_big()
    for one in results:
        if not _ROOT_NODE.fullmatch(one):
            raise WorkflowLibraryError("workflowLibErr_badAppItem", item=one[:200])
    if app is None:
        return None
    entries = app.get("items") or []
    if not isinstance(entries, list) or len(entries) > MAX_APP_ITEMS:
        raise _too_big()
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        node = str(entry.get("node") or "") if isinstance(entry, dict) else ""
        name = str(entry.get("input") or "") if isinstance(entry, dict) else ""
        key = f"{node}.{name}" if node else name
        if not isinstance(entry, dict) or not _INPUT_NAME.fullmatch(name) or key in seen or (
                node and not _ROOT_NODE.fullmatch(node)) or (not node and name not in _GRAPH_ITEMS):
            raise WorkflowLibraryError("workflowLibErr_badAppItem", item=key[:200])
        seen.add(key)
        item: dict[str, Any] = {"node": node, "input": name, "label": _text(entry.get("label"), _MAX_APP_LABEL)}
        if node and entry.get("main") is True:
            item["main"] = True
        choices = entry.get("choices")
        if node and isinstance(choices, list) and choices:
            if len(choices) > MAX_APP_CHOICES:
                raise _too_big()
            item["choices"] = [str(one)[:1000] for one in choices
                               if isinstance(one, (str, int, float)) and not isinstance(one, bool)]
        clean.append(item)
    return {"title": _text(app.get("title"), _MAX_APP_LABEL),
            "description": _text(app.get("description"), _MAX_APP_DESCRIPTION), "items": clean}


def annotate(db: Session, instance: PluginInstance, path: str, *, modified: float, app: dict[str, Any] | None,
             results: list[str]) -> dict[str, Any]:
    """改那台服务器上一张工作流的应用表单和结果标记:**只改 `mosael` 那几处**,带着读到时的改动时间去(`modified`)。
    那张在这之间被改过就不写(`WorkflowStale`,翻成 409)。成了让这个连接的目录马上重拉一遍(生成表单、工具跟着变),
    回写完之后的改动时间(接着改用它)。界面每次都先确认:写明哪台服务器上的哪个文件、只改这几处标记。"""
    _require(db, instance)
    path = workflow_path(path)
    results = [str(one) for one in results]
    form = _form_payload(app, results)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY,
                               {"op": "annotate", "path": path, "modified": modified, "app": form, "results": results},
                               timeout=QUICK_TIMEOUT_SECONDS)
    if output.get("stale") is True:
        raise WorkflowStale(path, _number(output.get("modified")))
    if _text(output.get("path"), 600) != path:
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    # 生成选项、工具清单跟着变(只剩表单那几项、名字换成作者起的),不等那一分钟的指纹
    host_capabilities.notify(db, instance, refresh=True)
    return {"path": path, "modified": _number(output.get("modified"))}


# --- 导入 ---------------------------------------------------------------------

def inspect_import(db: Session, instance: PluginInstance, *, text: str = "", data: str = "", filename: str = "",
                   url: str = "") -> dict[str, Any]:
    """让插件认一遍要导入的东西,规整成预览:换成界面格式的那张图、从哪儿来、什么格式、建议的路径、要告诉人的话,
    加上和列出来的每一张同一套的描述(图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺的节点和模型)。"""
    _require(db, instance)
    if len([one for one in (text, data, url) if one]) != 1:
        raise WorkflowLibraryError("workflowLibErr_importOne")
    if max(len(text), len(data), len(url)) > MAX_IMPORT_CHARS:
        raise WorkflowLibraryError("workflowLibErr_importTooBig", mb=str(MAX_IMPORT_CHARS * 3 // 4 // (1024 * 1024)))
    if url and not re.match(r"^https?://\S+$", url.strip()):
        raise WorkflowLibraryError("workflowLibErr_importBadUrl")
    request: dict[str, Any] = {"op": "inspect_import"}
    if text:
        request["text"] = text
    if data:
        request["data"] = data
    if url:
        request["url"] = url.strip()
    if filename:
        request["filename"] = _text(filename, 300)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, request, timeout=QUICK_TIMEOUT_SECONDS, record=False)
    workflow = output.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    try:
        suggested = workflow_path(_text(output.get("suggested_path"), 500))
    except WorkflowLibraryError:
        suggested = ""  # 界面自己给一个
    described = _workflow({**output, "path": suggested or "imported.json"}) or {}
    for key in ("path", "label", "folder", "size", "modified"):
        described.pop(key, None)
    fmt, source = _text(output.get("format"), 10), _text(output.get("source"), 10)
    return {
        **described,
        "format": fmt if fmt in _IMPORT_FORMATS else "ui",
        "source": source if source in _IMPORT_SOURCES else "json",
        "workflow": workflow,
        "suggested_path": suggested,
        "notes": [_text(one, 1000) for one in (output.get("notes") or []) if isinstance(one, str) and one.strip()][:10],
    }


def save(db: Session, instance: PluginInstance, path: str, content: dict[str, Any]) -> dict[str, str]:
    """把导入的那张(界面格式)存进那台服务器的 workflows/:只新建、不覆盖,撞名 409 带建议名。"""
    _require(db, instance)
    path = workflow_path(path)
    if not isinstance(content.get("nodes"), list):
        raise WorkflowLibraryError("workflowLibErr_notUiWorkflow")
    text = json.dumps(content, ensure_ascii=False)
    if len(text) > MAX_IMPORT_CHARS:
        raise WorkflowLibraryError("workflowLibErr_importTooBig", mb=str(MAX_IMPORT_CHARS * 3 // 4 // (1024 * 1024)))
    return {"path": _write(db, instance, {"op": "save_workflow", "path": path, "content": text}, wanted=path)}


# --- 补齐缺的节点 ------------------------------------------------------------------

def _packs(value: list[str]) -> list[str]:
    packs = [one.strip() for one in value if isinstance(one, str)]
    if not packs or len(packs) > _MAX_PACKS or any(
        not one or len(one) > 300 or any(ord(char) < 32 for char in one) for one in packs
    ):
        raise WorkflowLibraryError("workflowLibErr_badPacks", most=str(_MAX_PACKS))
    return list(dict.fromkeys(packs))


def start_node_install(db: Session, user: User, instance: PluginInstance, *, workspace_id: str,
                       packs: list[str]) -> Job:
    """经这个连接(ComfyUI-Manager)装几个节点包:一个后台任务。装完要重启 ComfyUI 才加载 —— 任务的结果里写着。"""
    _require(db, instance)
    packs = _packs(packs)
    ensure_workspace_perm(db, user, workspace_id, "edit")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    subject = "、".join(packs)
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="node_install",  # 和 NODE_INSTALL_KIND 同一个;任务目录的测试按字面量扫
        created_by=user.id,
        payload={"instance_id": instance.id, "packs": packs, "subject": subject},
        message="jobMsg_nodeInstallQueued",
        message_params={"name": subject},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: run_job_guarded(job_id, lambda: _install(job_id), what="装节点包"))
    return job


def _install(job_id: str) -> None:
    """装节点包的任务身子。和模型下载一样,每一步一个短的 unit_of_work,状态都经 finish_job 写。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        subject = str(payload.get("subject") or "")
        if db.get(PluginInstance, str(payload.get("instance_id") or "")) is None:
            if finish_job(db, job, status="failed", error="", error_key="modelLibErr_instanceGone", error_params={}):
                say(job, "jobMsg_nodeInstallFailed", name=subject)
            return
        if not finish_job(db, job, status="running", progress=0.01):
            return
        say(job, "jobMsg_nodeInstallRunning", name=subject)
        emit_job_event(db, job.id, "job.running", {})

    def on_progress(fraction: float, message: str) -> None:
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None or not finish_job(db, job, status="running"):
                return
            job.progress = min(0.99, max(float(job.progress or 0.0), float(fraction)))
            if message:
                say(job, message[:200])

    def cancelled() -> bool:
        from app.domain.jobs import was_cancelled

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            return job is None or was_cancelled(job) or job.status not in ("queued", "running")

    hooks = StreamHooks(on_progress=on_progress, on_task=lambda _receipt: None, is_cancelled=cancelled)
    try:
        with unit_of_work() as db:
            output = tools.invoke_host(db, str(payload["instance_id"]), WORKFLOW_LIBRARY,
                                       {"op": "install_nodes", "packs": payload["packs"]}, hooks=hooks,
                                       timeout=MAX_GENERATION_TIMEOUT_SECONDS)
    except (PluginDomainError, PluginRuntimeError) as exc:
        from app.domain.jobs import blame

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_nodeInstallFailed", name=subject)
                emit_job_event(db, job.id, "job.failed", {})
        return
    installed = [_text(one, 300) for one in output.get("installed") or [] if isinstance(one, str)]
    result = {"installed": installed or list(payload["packs"]), "restart": output.get("restart") is not False}
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_nodeInstallDone", name=subject)
            emit_job_event(db, job.id, "job.succeeded", dict(result))


def node_installs(db: Session, instance: PluginInstance) -> list[Job]:
    """这个连接最近的几次装节点包(在跑的总在里面),新的在前。"""
    rows = db.scalars(select(Job).where(Job.kind == NODE_INSTALL_KIND).order_by(Job.created_at.desc()).limit(100))
    mine = [job for job in rows if (job.payload or {}).get("instance_id") == instance.id]
    active = [job for job in mine if job.status in ("queued", "running")]
    finished = [job for job in mine if job.status not in ("queued", "running")]
    return active + finished[: max(0, RECENT_INSTALLS - len(active))]


def reboot(db: Session, instance: PluginInstance) -> dict[str, bool]:
    """经插件(ComfyUI-Manager)重启那台 ComfyUI,等它回来;回来以后这个连接的目录重拉一遍 —— 新装的节点包这时才加载。"""
    _require(db, instance)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "reboot"}, timeout=REBOOT_TIMEOUT_SECONDS)
    host_capabilities.notify(db, instance, refresh=True)
    return {"back": output.get("back") is True}


def register_uses() -> None:
    capabilities.register_use(capabilities.Use(WORKFLOW_LIBRARY, "app", fragment("capUse_workflowLibrary")))


#: 能力表里的 `workflow_library`(ADR 0035):不走挑法(每个连接各有各的工作流),登记它是为了叫得出名字、说得出用在哪。
CAPABILITY = capabilities.Capability(
    name=WORKFLOW_LIBRARY,
    label_key="capability_workflow_library",
    description_key="capability_workflow_library",
    pickable=False,
)


__all__ = [
    "CAPABILITY",
    "WorkflowConflict",
    "WorkflowLibraryError",
    "WorkflowStale",
    "annotate",
    "app_form",
    "content",
    "copy",
    "inspect_import",
    "library",
    "node_installs",
    "reboot",
    "register_uses",
    "rename",
    "restore",
    "save",
    "start_node_install",
    "trash",
    "trash_path",
    "workflow_path",
]
